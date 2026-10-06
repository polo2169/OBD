import math
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from opendbc.car import structs
from opendbc.car.psa.interface import CarInterface
from opendbc.car.psa.values import CAR
from opendbc.car.vehicle_model import VehicleModel
from openpilot.selfdrive.controls.lib.latcontrol_torque import (
  LatControlTorque,
  apply_t9_yaw_deadzone,
  clip_t9_curvature_to_torque_envelope,
)


class TestT9TorqueCoordinates(unittest.TestCase):
  def controller(self):
    with patch.dict(os.environ, {'PSA_T9_LATERAL_TEST': '1'}):
      cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
    cp.lateralTuning.torque.friction = 0.  # Isolate the conversion for this test.
    ci = CarInterface(cp)
    return LatControlTorque(cp.as_reader(), ci, .01), VehicleModel(cp)

  def run_control(self, yaw, curvature, roll=0., angle=0., active=True):
    controller, vm = self.controller()
    cs = structs.CarState(vEgo=20., yawRate=yaw, steeringAngleDeg=angle)
    params = SimpleNamespace(angleOffsetDeg=0., roll=roll)
    for _ in range(150):
      torque, _, _ = controller.update(active, cs, vm, params, False, curvature, False, .15)
    return torque

  def run_once(self, speed, yaw):
    controller, vm = self.controller()
    cs = structs.CarState(vEgo=speed, yawRate=yaw)
    params = SimpleNamespace(angleOffsetDeg=0., roll=0.)
    _, _, state = controller.update(True, cs, vm, params, False, 0., False, .15)
    return state

  def test_factory_sign_is_negative_feedback(self):
    self.assertLess(self.run_control(.01, 0.), 0.)
    self.assertGreater(self.run_control(-.01, 0.), 0.)

  def test_equal_can_response_and_target_need_matching_feedforward(self):
    # Native curvature is opposite factory CAN yaw/torque convention.
    self.assertAlmostEqual(self.run_control(.01, -.0005), .2/.82, delta=.02)
    self.assertAlmostEqual(self.run_control(-.01, .0005), -.2/.82, delta=.02)

  def test_measured_can_gain_does_not_receive_a_second_unidentified_roll_correction(self):
    a = self.run_control(.005, -.0004)
    b = self.run_control(.005, -.0004, roll=math.radians(2), angle=3.)
    self.assertAlmostEqual(a, b)

  def test_inactive_always_zero(self):
    self.assertEqual(self.run_control(.01, .0005, active=False), 0.)

  def test_pose_learner_cannot_replace_can_response_parameters(self):
    controller, _ = self.controller()
    before = controller.torque_params.to_dict()
    controller.update_live_torque_params(2.7, .3, .2)
    self.assertEqual(controller.torque_params.to_dict(), before)

  def test_high_speed_feedback_is_reduced_above_90_kph(self):
    # Hold the post-deadzone lateral-acceleration error equal to compare Kp.
    residual = .1
    low = self.run_once(25., -(residual + math.radians(.1) * 25.) / 25.)
    high = self.run_once(36., -(residual + math.radians(.1) * 36.) / 36.)
    self.assertAlmostEqual(abs(low.error), residual, places=5)
    self.assertAlmostEqual(abs(high.error), residual, places=5)
    self.assertLess(abs(high.p), abs(low.p) * .5)

  def test_one_yaw_count_is_removed_without_a_boundary_step(self):
    below = self.run_once(36., -.9 * math.radians(.1))
    above = self.run_once(36., -1.4 * math.radians(.1))
    self.assertEqual(below.error, 0.)
    self.assertAlmostEqual(abs(above.error), .4 * math.radians(.1) * 36., places=6)

  def test_t9_yaw_deadzone_is_symmetric(self):
    one_count = math.radians(.1) * 36.
    self.assertAlmostEqual(apply_t9_yaw_deadzone(1.5 * one_count, 36.), .5 * one_count)
    self.assertAlmostEqual(apply_t9_yaw_deadzone(-1.5 * one_count, 36.), -.5 * one_count)

  def test_curvature_envelope_scales_with_speed_squared(self):
    low, low_limited = clip_t9_curvature_to_torque_envelope(20., .01, .63)
    high, high_limited = clip_t9_curvature_to_torque_envelope(36., .01, .63)
    self.assertTrue(low_limited and high_limited)
    self.assertAlmostEqual(low, .63 / 20. ** 2)
    self.assertAlmostEqual(high, .63 / 36. ** 2)
    self.assertAlmostEqual(low / high, (36. / 20.) ** 2)

  def test_curvature_inside_torque_envelope_is_unchanged(self):
    value, limited = clip_t9_curvature_to_torque_envelope(36., -.0002, .63)
    self.assertEqual(value, -.0002)
    self.assertFalse(limited)

  def test_active_interface_uses_incremental_tight_curve_envelope(self):
    with patch.dict(os.environ, {'PSA_T9_LATERAL_TEST': '1'}):
      cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
    self.assertAlmostEqual(cp.maxLateralAccel, .82)
    self.assertAlmostEqual(cp.lateralTuning.torque.latAccelFactor, .82)


if __name__ == '__main__': unittest.main()
