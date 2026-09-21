import os
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from opendbc.car import structs
from opendbc.car.psa.interface import CarInterface
from opendbc.car.psa.values import CAR
from opendbc.car.vehicle_model import VehicleModel
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque


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

  def test_factory_sign_is_negative_feedback(self):
    self.assertLess(self.run_control(.01, 0.), 0.)
    self.assertGreater(self.run_control(-.01, 0.), 0.)

  def test_equal_can_response_and_target_need_matching_feedforward(self):
    # Native curvature is opposite factory CAN yaw/torque convention.
    self.assertAlmostEqual(self.run_control(.01, -.0005), .2/.42, delta=.02)
    self.assertAlmostEqual(self.run_control(-.01, .0005), -.2/.42, delta=.02)

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


if __name__ == '__main__': unittest.main()
