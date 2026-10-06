import math
from types import SimpleNamespace as NS
import unittest

from opendbc.car import structs
from opendbc.car.psa.lateral_pause import T9LateralPause, lanes_ready
from opendbc.car.psa.lka import LkaPhase
from opendbc.car.psa.tests.test_lka_lifecycle import active_machine, inputs, nanos


def model():
  return NS(laneLineProbs=[.1, .95, .95, .1], laneLines=[NS(y=[y]) for y in (-5.4, -1.8, 1.8, 5.4)],
            meta=NS(laneChangeState='off'))


class TestPauseGate(unittest.TestCase):
  def setUp(self):
    self.gate = T9LateralPause()
    self.car = structs.CarState()
    self.model = model()

  def tick(self, ms, **changes):
    values = dict(eligible=True, car=self.car, model=self.model, model_valid=True, model_ns=nanos(ms))
    return self.gate.update(nanos(ms), **(values | changes))

  def begin(self):
    self.car.leftBlinker = True
    self.assertTrue(self.tick(0))
    self.car.leftBlinker = False

  def test_signed_threshold_includes_fifteen(self):
    for value in (-16, -15, -11, -10, 0, 10, 11, 15, 16):
      self.setUp()
      self.car.steeringTorque = value
      self.assertEqual(self.tick(0), abs(value) > 15)

  def test_each_blinker_and_hazards_suspend(self):
    for left, right in ((True, False), (False, True), (True, True)):
      self.setUp()
      self.car.leftBlinker, self.car.rightBlinker = left, right
      for ms in range(0, 1001, 50):
        self.assertTrue(self.tick(ms))

  def test_resume_requires_three_tenths_of_new_good_models(self):
    self.begin()
    for ms in range(50, 350, 50):
      self.assertTrue(self.tick(ms))
    self.assertFalse(self.tick(350))

  def test_frozen_stale_future_or_invalid_models_never_resume(self):
    for changes in ({'model_ns': nanos(50)}, {'model_ns': 1}, {'model_ns': nanos(9999)}, {'model_valid': False}):
      self.setUp(); self.begin()
      for ms in range(50, 1001, 50):
        self.assertTrue(self.tick(ms, **changes))

  def test_low_confidence_and_repeated_driver_input_reset_stability(self):
    self.begin()
    for ms in range(50, 251, 50):
      self.assertTrue(self.tick(ms))
    self.model.laneLineProbs[1] = .74
    self.assertTrue(self.tick(250))
    self.model.laneLineProbs[1] = .95
    self.assertTrue(self.tick(300))
    self.car.steeringTorque = 16
    self.assertTrue(self.tick(350))
    self.car.steeringTorque = 15
    for ms in range(400, 700, 50):
      self.assertTrue(self.tick(ms))
    self.assertFalse(self.tick(700))

  def test_lane_geometry_lane_change_and_bad_values_are_not_ready(self):
    for left, right in ((1., 3.), (-.5, .5), (-3., 3.), (-.1, 3.9), (math.nan, 1.8)):
      candidate = model()
      candidate.laneLines[1].y[0], candidate.laneLines[2].y[0] = left, right
      self.assertFalse(lanes_ready(candidate))
    for probability in (math.nan, math.inf, -1., 1.1, .749):
      candidate = model(); candidate.laneLineProbs[1] = probability
      self.assertFalse(lanes_ready(candidate))
    self.model.meta.laneChangeState = 'laneChangeFinishing'
    self.assertFalse(lanes_ready(self.model))
    self.assertFalse(lanes_ready(object()))

  def test_disabled_session_cannot_request_a_pause_or_resume(self):
    self.begin()
    self.assertFalse(self.tick(50, eligible=False))
    self.assertFalse(self.gate.paused)

  def test_restarted_observer_waits_again_for_a_reported_pause(self):
    self.car.psaLateralPaused = True
    for ms in range(0, 300, 50):
      self.assertTrue(self.tick(ms))
    self.assertFalse(self.tick(300))

  def test_update_gap_and_clock_reversal_restart_stability(self):
    self.begin()
    self.assertTrue(self.tick(50))
    self.assertTrue(self.tick(100))
    self.assertTrue(self.tick(700))
    self.assertTrue(self.tick(750))
    self.assertTrue(self.tick(740))
    for ms in range(800, 1100, 50):
      self.assertTrue(self.tick(ms))
    self.assertFalse(self.tick(1100))

  def test_reported_pause_survives_missed_trigger_and_resume_waits_for_consumption(self):
    self.assertFalse(self.tick(0))
    self.car.psaLateralPaused = True  # A brief raw override was seen by card.
    for ms in range(50, 350, 50):
      self.assertTrue(self.tick(ms))
    self.assertFalse(self.tick(350))
    self.assertTrue(self.gate.resume_requested)
    self.assertFalse(self.tick(400))  # Old carState cannot restart the timer.
    self.model.laneLineProbs[1] = .5
    self.assertTrue(self.tick(450))  # Withdraw an unconsumed resume on new bad data.
    self.assertFalse(self.gate.resume_requested)


class TestPauseLifecycle(unittest.TestCase):
  def tick(self, machine, ms, **changes):
    return machine.update(nanos(ms), inputs(ms, **(dict(eps=3, pause_supported=True) | changes)))

  def test_pause_and_resume_keep_ack_and_restart_torque_at_zero(self):
    machine = active_machine()
    result = self.tick(machine, 860, driver_torque_raw=16)
    self.assertEqual((result.phase, result.state, result.torque_raw), (LkaPhase.PAUSED, 4, 0))
    self.assertFalse(result.rearm_required)
    for ms in range(870, 1471, 10):
      self.assertEqual(self.tick(machine, ms, pause_requested=True).torque_raw, 0)
    result = self.tick(machine, 1480, resume_allowed=True)
    self.assertEqual((result.phase, result.torque_raw), (LkaPhase.ACTIVE, 0))
    self.assertEqual(self.tick(machine, 1530).torque_raw, 1)

  def test_driver_release_alone_cannot_resume_without_host_lane_authorization(self):
    machine = active_machine()
    self.tick(machine, 860, driver_torque_raw=16)
    for ms in range(870, 1871, 10):
      result = self.tick(machine, ms)
      self.assertEqual((result.phase, result.torque_raw), (LkaPhase.PAUSED, 0))

  def test_eps_withdrawal_during_pause_never_automatically_rearms(self):
    for eps in (0, 1, 2, 4, 7):
      machine = active_machine()
      self.tick(machine, 860, pause_requested=True)
      result = self.tick(machine, 870, pause_requested=True, eps=eps)
      self.assertEqual(result.phase, LkaPhase.BLOCKED)
      self.assertEqual(self.tick(machine, 880).phase, LkaPhase.BLOCKED)

  def test_recorded_stock_drop_waits_for_blinker_then_reactivates_from_released_eps(self):
    machine = active_machine()
    result = self.tick(machine, 860, stock_state=2)
    self.assertEqual((result.phase, result.state, result.torque_raw), (LkaPhase.BLINKER_PENDING, 2, 0))
    result = self.tick(machine, 900, stock_state=2, eps=2, blinker_pause_requested=True,
                       pause_requested=True)
    self.assertEqual(result.phase, LkaPhase.BLINKER_PAUSED)
    self.assertEqual(self.tick(machine, 950, stock_state=2, eps=0, blinker_pause_requested=True,
                               pause_requested=True).phase, LkaPhase.BLINKER_PAUSED)
    self.assertEqual(self.tick(machine, 1000, stock_state=3, eps=1).phase, LkaPhase.BLINKER_PAUSED)
    result = self.tick(machine, 1050, stock_state=3, eps=1, resume_allowed=True)
    self.assertEqual((result.phase, result.state), (LkaPhase.PREPARING, 3))
    self.assertEqual(self.tick(machine, 1100, stock_state=3, eps=1, resume_allowed=True).phase, LkaPhase.PREPARING)
    self.assertEqual(self.tick(machine, 1150, stock_state=3, eps=1, resume_allowed=True).phase, LkaPhase.WAITING_EPS)
    result = self.tick(machine, 1200, stock_state=3, eps=3, resume_allowed=True)
    self.assertEqual((result.phase, result.torque_raw), (LkaPhase.ACTIVE, 0))

  def test_stock_drop_without_blinker_confirmation_stays_zero_and_latches(self):
    machine = active_machine()
    self.assertEqual(self.tick(machine, 860, stock_state=2).phase, LkaPhase.BLINKER_PENDING)
    self.assertEqual(self.tick(machine, 1000, stock_state=2, eps=2).phase, LkaPhase.BLINKER_PENDING)
    result = self.tick(machine, 1010, stock_state=2, eps=2)
    self.assertEqual((result.phase, result.reason, result.torque_raw),
                     (LkaPhase.BLOCKED, 'stock_lka_not_authorized', 0))

  def test_brake_vehicle_fault_or_timeout_during_pause_remain_stops(self):
    for changes in ({'brake_pressed': True}, {'can_valid': False}, {'vehicle_ready': False}, {'speed_kph': 66.}):
      machine = active_machine()
      self.tick(machine, 860, pause_requested=True)
      self.assertEqual(self.tick(machine, 870, **changes).phase, LkaPhase.BLOCKED)
    machine = active_machine()
    self.tick(machine, 860, pause_requested=True)
    self.assertEqual(self.tick(machine, 1200).reason, 'control_update_timeout')
