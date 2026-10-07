"""Exercise the compiled C policy using independent physical CAN inputs."""
import unittest

from opendbc.safety.tests import test_psa_t9_split as split_tests


class TestT9LateralExperiments(unittest.TestCase):
  TX_MSGS = None

  def prepare(self, param, speed=55., stock=2, blinker=0):
    self.h = split_tests.TestT9SplitSafety()
    self.h.setUp()
    self.h.safety.set_timer(0)
    self.assertEqual(self.h.safety.set_safety_hooks(31, param), 0)
    self.h.safety.init_tests()
    self.h.now = 0
    self.h.template = bytes([0, 0, 0x12, 0, stock << 2, 0, 0, 0])
    for _ in range(45):
      self.h.feed(speed=speed, blinker=blinker)

  def activate(self):
    self.h.engage()
    self.assertTrue(self.h.tx(1))

  def test_low_speed_requires_fresh_eps_ack_and_exact_speed_floor(self):
    for param in (0x1318, 0x131C):
      for speed, allowed in ((49.99, False), (50., True), (55., True), (67.09, True)):
        with self.subTest(param=param, speed=speed):
          self.prepare(param, speed)
          self.h.feed(cruise=True)
          self.assertEqual(bool(self.h.safety.get_t9_split_lateral_allowed()), allowed)
          self.assertTrue(self.h.safety.get_t9_split_rvv_allowed())
          self.assertFalse(self.h.tx(1))
          if allowed:
            self.assertTrue(self.h.tx(0, 3, 0))
            self.h.feed()
            self.assertTrue(self.h.tx(0, 4, 1))
            self.assertFalse(self.h.tx(1))
            self.h.feed(eps=3)
            self.assertTrue(self.h.tx(0))
            self.h.feed()
            self.assertTrue(self.h.tx(1))

  def test_factory_threshold_and_unknown_stock_state_are_not_silently_bypassed(self):
    for stock, speed in ((2, 67.1), (0, 55.), (1, 55.), (5, 55.)):
      self.prepare(0x1318, speed, stock)
      self.h.feed(cruise=True)
      self.assertFalse(self.h.safety.get_t9_split_lateral_allowed())
      self.assertFalse(self.h.tx(1))

  def test_old_profiles_still_refuse_low_speed_and_single_indicator_torque(self):
    for param in (0x1314, 0x1316, 0x131A):
      self.prepare(param)
      self.h.feed(cruise=True)
      self.assertFalse(self.h.safety.get_t9_split_lateral_allowed())
      self.assertFalse(self.h.tx(1))
    for param in (0x1314, 0x1316, 0x1318):
      self.prepare(param, 75., 3)
      self.activate()
      self.h.feed(blinker=1)
      self.assertFalse(self.h.tx(1))

  def test_both_indicators_supported_individually_and_hazards_stop(self):
    for param, speed in ((0x131A, 75.), (0x131C, 55.)):
      for blinker in (1, 2):
        self.prepare(param, speed)
        if speed == 75.:
          self.h.template = bytes.fromhex('000012000c000000')
          self.h.feed()
        self.activate()
        self.h.feed(blinker=blinker)
        self.h.template = bytes.fromhex('0000120008000000')
        self.h.feed()
        self.assertTrue(self.h.tx(0))
        self.h.feed()
        self.assertTrue(self.h.tx(1))
        self.h.feed(blinker=3)
        self.assertFalse(self.h.tx(1))
        self.h.assert_axes(False, True)
        self.h.feed(blinker=blinker)
        self.assertFalse(self.h.tx(1))

  def test_stock_drop_before_signal_is_zero_only_and_bounded(self):
    for confirm in (True, False):
      self.prepare(0x131A, 75., 3)
      self.activate()
      self.h.template = bytes.fromhex('0000120008000000')
      self.h.feed()
      self.assertFalse(self.h.tx(1))
      self.assertTrue(self.h.tx(0))
      if confirm:
        self.h.feed(blinker=1)
        self.assertTrue(self.h.tx(1))
      else:
        for _ in range(4):
          self.h.feed()
        self.assertFalse(self.h.safety.get_t9_split_lateral_allowed())
        self.h.feed(blinker=1)
        self.assertFalse(self.h.tx(1))

  def test_eps_withdrawal_and_speed_drop_are_latched_axis_local_stops(self):
    for change in ({'eps': 0}, {'eps': 1}, {'eps': 4}, {'speed': 49.99}):
      self.prepare(0x131C)
      self.activate()
      self.h.feed(blinker=1, **change)
      self.assertFalse(self.h.tx(1))
      self.h.assert_axes(False, True)
      self.h.feed(eps=3, speed=55.)
      self.assertFalse(self.h.tx(1))

  def test_pedal_behavior_and_driver_priority_are_preserved(self):
    for change in ({'pedal': 1}, {'brake': True}):
      self.prepare(0x131C)
      self.activate()
      self.h.feed(**change)
      self.h.assert_axes(False, False)
      self.assertFalse(self.h.tx(1))
      self.h.feed(pedal=0, brake=False)
      self.h.assert_axes(False, False)
    self.prepare(0x131C)
    self.activate()
    self.h.feed(driver=16, blinker=1)
    self.assertFalse(self.h.tx(1))
    self.assertTrue(self.h.tx(0))

  def test_new_probes_never_transmit_and_capability_query_is_read_only(self):
    for param in (0x1319, 0x131B, 0x131D):
      self.prepare(param, 75., 3)
      self.h.feed(cruise=True)
      before = self.h.safety.test_t9_rvv_permission_bits()
      self.assertEqual(self.h.safety.test_t9_rvv_control_request(0, 6), 10)
      self.assertEqual(self.h.safety.test_t9_rvv_permission_bits(), before)
      for state in (2, 3, 4):
        self.assertFalse(self.h.tx(0, state, 0))


if __name__ == '__main__':
  unittest.main()
