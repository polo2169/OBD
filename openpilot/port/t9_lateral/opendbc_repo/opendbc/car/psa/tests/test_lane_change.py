from dataclasses import replace
from types import SimpleNamespace as NS
import unittest

from opendbc.car import structs
from opendbc.car.psa.lane_change import LaneContext, LaneEvidence, T9TimedLaneChange, geometry
from opendbc.car.psa.tests.test_lka_lifecycle import nanos
from openpilot.selfdrive.controls.lib.t9_lane_change import T9LaneChangePreview


class TestTimedLaneChange(unittest.TestCase):
  def setUp(self):
    self.gate = T9TimedLaneChange(50.)
    self.car = structs.CarState(vEgo=55./3.6, leftBlinker=True)

  def tick(self, ms, *, context=True, evidence=None, active=True):
    lane = evidence or LaneEvidence(1, nanos(ms), True, True, True)
    road = LaneContext(1, nanos(ms), True, True, True, True) if context is True else context
    return self.gate.update(nanos(ms), self.car, active, lane, road)

  def until(self, ms, **kwargs):
    result = None
    for tick in range(0, ms+1, 50):
      result = self.tick(tick, **kwargs)
    return result

  def test_two_seconds_exact_and_one_departure_until_real_signal_off(self):
    self.assertFalse(self.until(1950).start)
    self.assertTrue(self.tick(2000).start)
    self.assertFalse(self.tick(2050).start)
    self.gate.finish()
    for ms in range(2100, 4101, 50):
      self.assertFalse(self.tick(ms).start)
    self.car.leftBlinker = False
    self.tick(4150)
    self.car.leftBlinker = True
    for ms in range(4200, 6200, 50):
      self.assertFalse(self.tick(ms).start)
    self.assertTrue(self.tick(6200).start)

  def test_unknown_road_context_refuses_at_deadline_without_late_departure(self):
    result = self.until(2000, context=LaneContext())
    self.assertEqual(result.phase, 'consumed')
    self.assertIn('unknown', result.reason)
    for ms in range(2050, 4001, 50):
      self.assertFalse(self.tick(ms).start)

  def test_clear_road_and_rear_are_independent_requirements(self):
    for field in ('same_direction', 'crossing_allowed', 'rear_clear'):
      for value in (None, False):
        self.setUp()
        for ms in range(0, 2001, 50):
          road = replace(LaneContext(1, nanos(ms), True, True, True), **{field: value})
          result = self.tick(ms, context=road)
        self.assertEqual(result.phase, 'consumed')
        self.assertFalse(result.start)

  def test_brief_signal_hazards_and_direction_changes_never_depart(self):
    for change in ('cancel', 'hazards', 'opposite'):
      self.setUp()
      self.until(500)
      self.car.leftBlinker = change == 'hazards'
      self.car.rightBlinker = change != 'cancel'
      for ms in range(550, 3001, 50):
        self.assertFalse(self.tick(ms).start)

  def test_missing_lane_frozen_model_and_control_gap_refuse(self):
    for problem in ('missing', 'frozen', 'gap'):
      self.setUp()
      for ms in range(0, 2001, 50):
        if problem == 'gap' and 400 <= ms <= 700:
          continue
        evidence = LaneEvidence(1, nanos(0 if problem == 'frozen' else ms), True, problem != 'missing', True)
        result = self.tick(ms, evidence=evidence)
      self.assertFalse(result.start)
      self.assertEqual(result.phase, 'consumed')

  def test_abort_releases_desire_and_requires_new_request(self):
    for intervention in ('driver', 'pedal', 'blindspot', 'perception', 'context', 'inactive', 'cancel'):
      self.setUp()
      self.assertTrue(self.until(2000).start)
      if intervention == 'driver': self.car.steeringTorque = 16
      if intervention == 'pedal': self.car.gasPressed = True
      if intervention == 'blindspot': self.car.leftBlindspot = True
      if intervention == 'cancel': self.car.leftBlinker = False
      result = self.tick(2050, context=LaneContext() if intervention == 'context' else True,
        evidence=LaneEvidence() if intervention == 'perception' else None, active=intervention != 'inactive')
      self.assertTrue(result.abort)
      self.assertFalse(result.start)

  def test_geometry_uses_lane_boundaries_and_checks_both_sides(self):
    model = NS(laneLineProbs=[.95]*4, laneLines=[NS(x=[0.,10.,20.], y=[y]*3) for y in (-5.4,-1.8,1.8,5.4)])
    for direction in (1,2):
      self.assertTrue(geometry(model, direction, nanos(0), True).adjacent_lane)
    model.laneLineProbs[0] = .1
    self.assertFalse(geometry(model, 1, nanos(0), True).adjacent_lane)
    self.assertTrue(geometry(model, 2, nanos(0), True).adjacent_lane)
    model.laneLines[3].y = [2.2]*3
    self.assertFalse(geometry(model, 2, nanos(0), True).adjacent_lane)

  def test_preview_proposes_a_single_maneuver_and_runtime_unknown_context_cannot_start(self):
    model = NS(laneLineProbs=[.95]*4, laneLines=[NS(x=[0.,10.,20.], y=[y]*3) for y in (-5.4,-1.8,1.8,5.4)])
    for known in (False, True):
      preview = T9LaneChangePreview(50.)
      starts = []
      rows = []
      for ms in range(0, 5001, 50):
        context = LaneContext(1, nanos(ms), True, True, True, True) if known else LaneContext()
        row = preview.update(nanos(ms), self.car, True, model, nanos(ms), True, 0., context)
        rows.append(row)
        if row['start']: starts.append(ms)
        self.assertTrue(row['observation_only'])
      self.assertEqual(starts, [2000] if known else [])
      if known:
        self.assertTrue(any(r['candidate_desire'] == 'laneChangeLeft' for r in rows))
        self.assertEqual(rows[-1]['reason'], 'completed_one_lane_change')
      self.assertEqual(rows[-1]['candidate_desire'], 'none')


if __name__ == '__main__':
  unittest.main()
