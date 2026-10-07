"""Observation/replay of the timed T9 lane change; never feeds model desires.

The candidate follows openpilot's normal fade-out/fade-in sequencing. A
completed change also needs positive target-lane evidence. Until road/rear
context is integrated and validated, the runtime supplies UNKNOWN context.
"""
from dataclasses import asdict
import math

from opendbc.car.psa.lane_change import LaneContext, T9TimedLaneChange, geometry
from opendbc.car.psa.lateral_profiles import signal


class T9LaneChangePreview:
  def __init__(self, min_speed_kph):
    self.gate = T9TimedLaneChange(min_speed_kph)
    self.stage = 'off'
    self.ll_prob = 1.
    self.last_clock = 0

  def update(self, now, car, active, model, model_ns, model_valid, lane_change_prob, context=LaneContext()):
    evidence = geometry(model, signal(car.leftBlinker, car.rightBlinker), model_ns, model_valid)
    if not math.isfinite(lane_change_prob) or not 0 <= lane_change_prob <= 1.:
      evidence = geometry(model, 0, model_ns, False)
    decision = self.gate.update(now, car, active, evidence, context)
    dt = min(.15, max(0., (now - self.last_clock) / 1e9)) if self.last_clock else 0.
    if decision.abort:
      self.stage, self.ll_prob = 'off', 1.
    elif decision.start:
      self.stage, self.ll_prob = 'starting', 1.
    elif decision.phase == 'running':
      if self.stage == 'starting':
        self.ll_prob = max(0., self.ll_prob - 2. * dt)
        if lane_change_prob < .02 and self.ll_prob < .01:
          self.stage = 'finishing'
      elif self.stage == 'finishing':
        self.ll_prob = min(1., self.ll_prob + dt)
        if self.ll_prob > .99 and evidence.centred and context.target_lane_reached is True:
          self.gate.finish()
          self.stage = 'off'
    elif decision.phase != 'running':
      self.stage, self.ll_prob = 'off', 1.
    self.last_clock = now
    desire = ('laneChangeLeft' if decision.direction == 1 else 'laneChangeRight') if self.stage in ('starting', 'finishing') else 'none'
    return asdict(decision) | {'candidate_desire': desire, 'candidate_stage': self.stage,
      'phase': self.gate.phase, 'reason': self.gate.reason,
      'candidate_ll_prob': self.ll_prob, 'adjacent_lane_candidate': evidence.adjacent_lane,
      'observation_only': True, 'mono_ns': now}
