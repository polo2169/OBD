import os
import unittest
from unittest.mock import patch

from opendbc.car import structs
from opendbc.car.psa import rvv_wire
from opendbc.car.psa.interface import CarInterface
from opendbc.car.psa.lateral_profiles import EXPERIMENTS, selected
from opendbc.car.psa.lateral_pause import T9LateralPause
from opendbc.car.psa.lka import LkaPhase, T9LkaLifecycle
from opendbc.car.psa.tests.test_lka_lifecycle import inputs, nanos
from opendbc.car.psa.tests.test_lateral_pause import model
from opendbc.car.psa.values import CAR
from opendbc.car.psa.tests import test_lateral_test as lateral_tests


class TestLateralProfiles(unittest.TestCase):
  def test_default_and_explicit_params_match_all_host_axes(self):
    for name in ('off', *EXPERIMENTS):
      with patch.dict(os.environ, {'PSA_T9_LATERAL_TEST': '1', 'PSA_T9_RVV_TEST': '1',
                                 'PSA_T9_SPLIT_AXES_TEST': '1', 'PSA_T9_EPS_CYCLE_TEST': '1',
                                 'PSA_T9_LATERAL_EXPERIMENT': name}):
        cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
      profile = selected(name)
      self.assertEqual(cp.safetyConfigs[0].safetyParam, profile.safety_param or 0x1316)
      self.assertAlmostEqual(cp.minSteerSpeed * 3.6, profile.min_speed_kph, places=4)
      self.assertTrue(rvv_wire.split(cp))
      self.assertTrue(rvv_wire.eps_cycle(cp))
      self.assertAlmostEqual(cp.minEnableSpeed * 3.6, 40., places=4)
      self.assertFalse(cp.openpilotLongitudinalControl)
      ci = CarInterface(cp)
      self.assertEqual(ci.CC.t9_lateral.profile, profile)

  def test_unknown_selector_or_incomplete_profile_cannot_fall_back_to_active(self):
    for name, cycle in (('typo', '1'), ('low_speed', '0')):
      with patch.dict(os.environ, {'PSA_T9_LATERAL_TEST': '1', 'PSA_T9_RVV_TEST': '1',
                                 'PSA_T9_SPLIT_AXES_TEST': '1', 'PSA_T9_EPS_CYCLE_TEST': cycle,
                                 'PSA_T9_LATERAL_EXPERIMENT': name}):
        with self.assertRaises(ValueError):
          CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)

  def active(self, name, speed=55., stock=2):
    machine = T9LkaLifecycle(20, profile=selected(name), cycle_supported=True)
    for ms in range(0, 1851, 50):
      decision = machine.update(nanos(ms), inputs(ms, eps=3 if ms >= 150 else 1,
        speed_kph=speed, stock_state=stock, pause_supported=True))
    self.assertEqual(decision.phase, LkaPhase.ACTIVE)
    self.assertEqual(decision.torque_raw, 20)
    return machine

  def test_low_speed_zero_until_ack_and_no_recovery_after_speed_cut(self):
    machine = self.active('low_speed')
    cut = machine.update(nanos(1900), inputs(1900, eps=3, speed_kph=49.99, stock_state=2, pause_supported=True))
    self.assertEqual((cut.torque_raw, cut.reason), (0, 'speed_below_lateral_envelope'))
    recovery = machine.update(nanos(1950), inputs(1950, eps=3, speed_kph=55., stock_state=2, pause_supported=True))
    self.assertEqual(recovery.phase, LkaPhase.BLOCKED)

  def test_blinker_does_not_grant_or_restore_eps_authority(self):
    machine = self.active('low_speed_blinker')
    good = machine.update(nanos(1900), inputs(1900, eps=3, speed_kph=55., stock_state=2,
      pause_supported=True, blinker_signal=1))
    self.assertGreater(good.torque_raw, 0)
    lost = machine.update(nanos(1950), inputs(1950, eps=0, speed_kph=55., stock_state=2,
      pause_supported=True, blinker_signal=1))
    self.assertEqual(lost.phase, LkaPhase.BLOCKED)
    self.assertEqual(lost.torque_raw, 0)
    restored = machine.update(nanos(2000), inputs(2000, eps=3, speed_kph=55., stock_state=2,
      pause_supported=True, blinker_signal=1))
    self.assertEqual(restored.phase, LkaPhase.BLOCKED)

  def test_factory_edge_grace_is_zero_and_requires_signal_within_150ms(self):
    for confirm in (True, False):
      machine = self.active('blinker', 75., 3)
      for ms in (1900, 1950, 2000):
        pending = machine.update(nanos(ms), inputs(ms, eps=3, stock_state=2, pause_supported=True))
        self.assertEqual(pending.torque_raw, 0)
      result = machine.update(nanos(2040 if confirm else 2050),
        inputs(2040 if confirm else 2050, eps=3, stock_state=2, pause_supported=True,
               blinker_signal=1 if confirm else 0))
      self.assertEqual(result.phase, LkaPhase.ACTIVE if confirm else LkaPhase.BLOCKED)

  def test_hazards_and_driver_effort_keep_priority(self):
    machine = self.active('low_speed_blinker')
    result = machine.update(nanos(1900), inputs(1900, eps=3, speed_kph=55., stock_state=2,
      pause_supported=True, blinker_signal=3))
    self.assertEqual((result.torque_raw, result.reason), (0, 'hazards_or_invalid_blinker'))
    car = structs.CarState()
    car.leftBlinker = True
    gate = T9LateralPause(blinker_assist=True)
    self.assertFalse(gate.update(nanos(0), eligible=True, car=car, model=model(), model_valid=True, model_ns=nanos(0)))
    car.steeringTorque = 16
    self.assertTrue(gate.update(nanos(50), eligible=True, car=car, model=model(), model_valid=True, model_ns=nanos(50)))

  def test_native_can_decoding_host_sender_and_panda_agree_at_55_and_while_signalling(self):
    h = lateral_tests.TestT9LateralIntegration()
    h.setUp()
    self.addCleanup(h.doCleanups)
    with patch.dict(os.environ, {'PSA_T9_LATERAL_TEST': '1', 'PSA_T9_RVV_TEST': '1',
                               'PSA_T9_SPLIT_AXES_TEST': '1', 'PSA_T9_EPS_CYCLE_TEST': '1',
                               'PSA_T9_LATERAL_EXPERIMENT': 'low_speed_blinker'}):
      h.cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
    h.ci = CarInterface(h.cp)
    h.safety.set_safety_hooks(31, 0x131C)
    h.safety.init_tests()
    for ms in range(0, 4001, 10):
      applied, _ = h.step(ms, speed=55., stock_lka=bytes.fromhex('0000120008000000'),
        blinker=1 if ms >= 3500 else 0)
    self.assertEqual(applied.torqueOutputCan, 20)
    self.assertFalse(h.ci.CS.out.psaLateralPaused)
    self.assertTrue(h.safety.get_t9_split_lateral_allowed())
    self.assertTrue(h.safety.get_t9_split_rvv_allowed())
    applied, _ = h.step(4010, speed=55., stock_lka=bytes.fromhex('0000120008000000'), blinker=1, eps=0)
    self.assertEqual(applied.torqueOutputCan, 0)
    self.assertFalse(h.safety.get_t9_split_lateral_allowed())
    self.assertTrue(h.safety.get_t9_split_rvv_allowed())
