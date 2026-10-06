import unittest

from opendbc.can.packer import CANPacker
from opendbc.can.parser import CANParser
from opendbc.car import structs
from opendbc.car.psa.interface import CarInterface
from opendbc.car.psa.values import CAR


class TestShadowIntegration(unittest.TestCase):
  def setUp(self):
    self.packer = CANPacker('psa_308_t9_2018')
    self.cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
    self.ci = CarInterface(self.cp)

  def step(self, ms, *, brake=False, gas=False, demand=0, pedal_raw=None, cruise=True, lat=True, long=True, gear=4, target_gear=5, omit=None):
    now = 1_000_000_000 + ms * 1_000_000
    values = {
      'T9_ENGINE_DYNAMICS_208': {'CruiseStateCandidate': 2 if cruise else 0, 'AcceleratorPositionPct': demand},
      'T9_ACCELERATOR_PEDAL_228': {'AcceleratorPedalPct': pedal_raw / 2 if pedal_raw is not None else 10 if gas else 0},
      'T9_STEERING_TORQUE_2F5': {'DriverTorqueRaw': 0},
      'T9_STEERING_DYNAMICS_305': {},
      'T9_WHEEL_SPEEDS_30D': {f'WheelSpeed{wheel}Kph': 72 for wheel in ('FrontLeft', 'FrontRight', 'RearLeft', 'RearRight')},
      'T9_ENGINE_GEAR_348': {'CurrentGear': gear},
      'T9_GEARBOX_TARGET_349': {'TargetGear': target_gear},
      'T9_EASY_MOVE_3AD': {},
      'T9_BRAKE_DYNAMICS_3CD': {},
      'T9_BODY_STATUS_412': {'BrakePedalActive': brake},
      'T9_DRIVER_CRUISE_COMMAND_452': {},
      'T9_CRUISE_SETPOINT_50E': {'CruiseMode': 1, 'CruiseSetpointKph': 90},
      'T9_RESTRAINTS_572': {'DriverSeatbeltState': 2},
    }
    frames = [self.packer.make_can_msg(name, 0, signals) for name, signals in values.items() if name != omit]
    frames += [(0x3F2, bytes.fromhex('000014000C000000'), 0),
               (0x495, bytes([0, 0, (3 if ms >= 150 else 1) << 2, 0]), 0)]
    self.ci.update([(now, frames)])
    control = structs.CarControl(enabled=True, latActive=lat, longActive=long)
    control.actuators.torque = 1.
    control.actuators.accel = -0.2
    applied, sends = self.ci.apply(control.as_reader(), now)
    self.assertEqual(sends, [])
    self.assertEqual((applied.torque, applied.accel, applied.steeringAngleDeg), (0., 0., 0.))
    status = self.ci.CC.t9_shadow.status
    self.assertFalse(status['tx_allowed'])
    return status

  def active(self):
    for ms in range(0, 851, 50):
      status = self.step(ms)
    self.assertEqual(status['lateral']['phase'], 'active')
    self.assertEqual(status['lateral']['torque_raw'], 1)
    self.assertEqual(status['longitudinal']['proposed_setpoint_kph'], 89)

  def test_both_proposals_calculate_without_actuation(self):
    self.active()
    self.assertTrue(self.cp.dashcamOnly)
    self.assertFalse(self.cp.openpilotLongitudinalControl)
    self.assertEqual(self.cp.safetyConfigs[0].safetyModel, structs.CarParams.SafetyModel.noOutput)

  def test_unknown_gear_never_becomes_drive_from_motion_or_target(self):
    status = self.step(0, gear=0, target_gear=4)
    self.assertFalse(status['drive_gear_confirmed'])
    self.assertEqual(status['lateral']['reason'], 'vehicle_not_ready')
    self.assertEqual(status['longitudinal']['reason'], 'vehicle_not_ready')

  def test_current_and_requested_ratios_are_distinct(self):
    status = self.step(0, gear=4, target_gear=5)
    self.assertEqual((status['current_gear'], status['target_gear']), (4, 5))
    self.assertTrue(status['drive_gear_confirmed'])
    status = self.step(50, gear=9, target_gear=1)
    self.assertEqual(self.ci.CS.out.gearShifter, structs.CarState.GearShifter.reverse)
    self.assertFalse(status['drive_gear_confirmed'])

  def test_recorded_gear_payloads_and_no_low_nibble_fallback(self):
    # Unmodified bus-0 payloads from the two September 17 comma routes.
    for payload, expected in (('4036474031037059', 4), ('901e5f4611036059', 9)):
      self.ci.update([(1_000_000_000, [(0x348, bytes.fromhex(payload), 0)])])
      self.assertEqual(self.ci.CS.t9_current_gear_raw, expected)
    self.ci.update([(1_010_000_000, [(0x348, bytes.fromhex('0436474031037059'), 0)])])
    self.assertEqual(self.ci.CS.t9_current_gear_raw, 0)
    self.assertEqual(self.ci.CS.out.gearShifter, structs.CarState.GearShifter.unknown)

  def test_target_checksum_rejects_each_single_bit_corruption(self):
    original = bytes.fromhex('22461a53464bc3fe')
    for bit in range(64):
      with self.subTest(bit=bit):
        cp = CANParser('psa_308_t9_2018', [(0x349, 100)], 0)
        cp.update([(1_000_000_000, [(0x349, original, 0)])])
        self.assertEqual(cp.vl[0x349]['TargetGear'], 5)
        damaged = bytearray(original)
        damaged[bit // 8] ^= 1 << (bit % 8)
        cp.update([(1_010_000_000, [(0x349, bytes(damaged), 0)])])
        self.assertEqual(cp.ts_nanos[0x349]['TargetGear'], 1_000_000_000)

  def test_unknown_target_codes_are_not_forward_gears(self):
    for target in (10, 15):
      status = self.step(0, target_gear=target)
      self.assertEqual(status['target_gear_raw'], target)
      self.assertIsNone(status['target_gear'])

  def test_stale_engaged_ratio_is_not_replaced_with_fresh_target(self):
    self.active()
    for ms in range(900, 1201, 50):
      status = self.step(ms, omit='T9_ENGINE_GEAR_348')
    self.assertIsNone(status['current_gear'])
    self.assertEqual(status['target_gear'], 5)
    self.assertFalse(status['drive_gear_confirmed'])
    self.assertEqual(status['lateral']['reason'], 'safety_rx_stale')

  def test_brake_cuts_both_and_does_not_resume_when_released(self):
    self.active()
    status = self.step(851, brake=True)
    self.assertEqual(status['lateral']['reason'], 'brake_pressed')
    self.assertEqual(status['longitudinal']['reason'], 'brake_pressed')
    status = self.step(900)
    self.assertEqual(status['lateral']['torque_raw'], 0)
    self.assertIsNone(status['longitudinal']['proposed_setpoint_kph'])

  def test_gas_or_rvv_off_does_not_disable_lateral(self):
    for changes in ({'gas': True}, {'cruise': False}, {'long': False}):
      with self.subTest(changes=changes):
        self.setUp()
        self.active()
        status = self.step(900, **changes)
        self.assertEqual(status['lateral']['phase'], 'active')
        self.assertEqual(status['lateral']['torque_raw'], 1)
        self.assertIsNone(status['longitudinal']['proposed_setpoint_kph'])

  def test_stale_body_frame_cuts_both(self):
    self.active()
    for ms in range(900, 1201, 50):
      status = self.step(ms, omit='T9_BODY_STATUS_412')
    self.assertEqual(status['lateral']['reason'], 'safety_rx_stale')
    self.assertEqual(status['longitudinal']['reason'], 'safety_rx_stale')

  def test_engine_demand_does_not_fake_driver_pedal(self):
    self.active()
    status = self.step(900, demand=30, gas=False)
    self.assertFalse(self.ci.CS.out.gasPressed)
    self.assertTrue(status['pedal_valid'])
    self.assertEqual(status['pedal_pct'], 0)
    self.assertEqual(status['engine_accelerator_demand_pct'], 30)
    self.assertIsNotNone(status['longitudinal']['proposed_setpoint_kph'])
    status = self.step(950, demand=0, gas=True)
    self.assertTrue(self.ci.CS.out.gasPressed)
    self.assertEqual(status['pedal_pct'], 10)
    self.assertEqual(status['longitudinal']['reason'], 'driver_accelerator')

  def test_missing_stale_and_reserved_pedal_never_imply_release(self):
    status = self.step(0, omit='T9_ACCELERATOR_PEDAL_228')
    self.assertFalse(status['pedal_valid'])
    self.assertTrue(self.ci.CS.out.gasPressed)
    self.setUp()
    self.active()
    status = self.step(1200, omit='T9_ACCELERATOR_PEDAL_228')
    self.assertFalse(status['pedal_valid'])
    self.assertTrue(self.ci.CS.out.gasPressed)
    for raw in (201, 254, 255):
      status = self.step(1250, pedal_raw=raw)
      self.assertFalse(status['pedal_valid'])
      self.assertIsNone(status['pedal_pct'])
      self.assertTrue(self.ci.CS.out.gasPressed)

  def test_recorded_pedal_payload_and_checksum_protection(self):
    original = bytes.fromhex('2a300014fec13200')
    for bit in range(64):
      with self.subTest(bit=bit):
        cp = CANParser('psa_308_t9_2018', [(0x228, 100)], 0)
        cp.update([(1_000_000_000, [(0x228, original, 0)])])
        self.assertEqual(cp.vl[0x228]['AcceleratorPedalPct'], 0)
        self.assertEqual(cp.ts_nanos[0x228]['AcceleratorPedalPct'], 1_000_000_000)
        damaged = bytearray(original)
        damaged[bit // 8] ^= 1 << (bit % 8)
        cp.update([(1_010_000_000, [(0x228, bytes(damaged), 0)])])
        self.assertEqual(cp.ts_nanos[0x228]['AcceleratorPedalPct'], 1_000_000_000)
