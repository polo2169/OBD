"""One supervised lane-change request after two seconds of a physical signal.

This module has no CAN output. Lane geometry is only a candidate: the current
model does not establish travel direction, legal crossing or rear clearance.
Those independent, time-stamped inputs default to UNKNOWN and refuse departure.
"""
from dataclasses import dataclass
import math

from opendbc.car.psa.lateral_profiles import signal

DELAY_NS = 2_000_000_000
STABILITY_NS = 300_000_000
FRESH_NS = 150_000_000
MANEUVER_TIMEOUT_NS = 10_000_000_000


@dataclass(frozen=True)
class LaneContext:
  direction: int = 0
  timestamp_ns: int = 0
  same_direction: bool | None = None
  crossing_allowed: bool | None = None
  rear_clear: bool | None = None
  target_lane_reached: bool | None = None


@dataclass(frozen=True)
class LaneEvidence:
  direction: int = 0
  model_ns: int = 0
  model_valid: bool = False
  adjacent_lane: bool = False
  centred: bool = False


@dataclass(frozen=True)
class LaneChangeDecision:
  phase: str
  direction: int
  start: bool
  abort: bool
  reason: str


def geometry(model, direction, model_ns, valid):
  """Four lane boundaries, checked at 0/10/20 m; no road-edge substitution."""
  try:
    probs, lines = tuple(model.laneLineProbs), model.laneLines
    if direction not in (1, 2) or len(probs) != 4 or len(lines) != 4:
      return LaneEvidence(direction, model_ns)
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs):
      return LaneEvidence(direction, model_ns)
    indices = (0, 1, 2) if direction == 1 else (1, 2, 3)
    if any(len(line.x) != len(line.y) or len(line.x) < 3 for line in lines):
      return LaneEvidence(direction, model_ns)
    adjacent = min(probs[i] for i in indices) >= .75
    centred = False
    for distance in (0., 10., 20.):
      ys = []
      for line in lines:
        xs = list(line.x)
        if any(not math.isfinite(v) for v in (*xs, *line.y)) or any(b <= a for a, b in zip(xs, xs[1:])):
          return LaneEvidence(direction, model_ns)
        if xs[0] > distance + 1. or xs[-1] < distance:
          return LaneEvidence(direction, model_ns)
        k = min(range(len(xs)), key=lambda i: abs(xs[i] - distance))
        if abs(xs[k] - distance) > 2.:
          return LaneEvidence(direction, model_ns)
        ys.append(float(line.y[k]))
      if not all(a < b for a, b in zip(ys, ys[1:])):
        return LaneEvidence(direction, model_ns)
      widths = [ys[2] - ys[1], ys[1] - ys[0] if direction == 1 else ys[3] - ys[2]]
      adjacent &= all(2.4 <= width <= 4.5 for width in widths)
      if distance == 0.:
        centred = ys[1] < 0 < ys[2] and abs((ys[1] + ys[2]) / 2) <= .4
    return LaneEvidence(direction, model_ns, bool(valid), bool(adjacent), bool(centred))
  except (AttributeError, IndexError, TypeError, ValueError):
    return LaneEvidence(direction, model_ns)


class T9TimedLaneChange:
  def __init__(self, min_speed_kph=67.1):
    self.min_speed_kph = min_speed_kph
    self.phase = 'idle'
    self.direction = self.last_signal = 0
    self.last_clock = self.request_ns = self.started_ns = 0
    self.stable_since = self.last_model = 0
    self.reason = 'no_request'

  def finish(self):
    self.phase, self.reason = 'consumed', 'completed_one_lane_change'

  def _problem(self, now, car, active, evidence, context, *, departing):
    if not active:
      return 'lateral_inactive'
    if not math.isfinite(car.vEgo) or not self.min_speed_kph <= round(car.vEgo * 3.6, 4) <= 140.:
      return 'speed_outside_profile'
    if car.brakePressed or car.gasPressed:
      return 'pedal_intervention'
    if car.steeringPressed or not math.isfinite(car.steeringTorque) or abs(car.steeringTorque) > 15:
      return 'driver_intervention'
    if (car.leftBlindspot if self.direction == 1 else car.rightBlindspot):
      return 'blindspot_occupied'
    if not evidence.model_valid or not 0 < evidence.model_ns <= now or now - evidence.model_ns > FRESH_NS:
      return 'model_stale_or_invalid'
    if departing and (evidence.direction != self.direction or not evidence.adjacent_lane):
      return 'adjacent_lane_unconfirmed'
    if departing and (not self.stable_since or now - self.stable_since < STABILITY_NS):
      return 'lane_not_stable'
    if context.direction != self.direction or not 0 < context.timestamp_ns <= now or now - context.timestamp_ns > FRESH_NS:
      return 'road_and_rear_context_unknown_or_stale'
    if context.same_direction is not True:
      return 'travel_direction_unconfirmed'
    if context.crossing_allowed is not True:
      return 'crossing_permission_unconfirmed'
    if context.rear_clear is not True:
      return 'rear_clearance_unconfirmed'
    return None

  def update(self, now, car, active, evidence, context=LaneContext()):
    current = signal(car.leftBlinker, car.rightBlinker)
    start = abort = False
    clock_ok = type(now) is int and now > 0 and (not self.last_clock or 0 <= now - self.last_clock <= FRESH_NS)
    if not clock_ok:
      abort = self.phase == 'running'
      self.phase, self.reason = 'consumed', 'control_clock_invalid'
    elif current == 0:
      abort = self.phase == 'running'
      self.phase, self.reason = 'idle', 'signal_cancelled' if self.last_signal else 'no_request'
      self.direction = self.request_ns = self.stable_since = self.last_model = 0
    elif current == 3 or current != self.direction and self.phase in ('waiting', 'running', 'consumed'):
      abort = self.phase == 'running'
      self.phase, self.reason = 'consumed', 'hazards_or_direction_changed'
    elif self.phase == 'idle' and self.last_signal == 0:
      self.direction, self.request_ns = current, now
      self.phase, self.reason = 'waiting', 'waiting_two_seconds'
    if clock_ok and self.phase == 'waiting':
      fresh = evidence.model_valid and evidence.direction == self.direction and evidence.adjacent_lane and 0 < evidence.model_ns <= now and now - evidence.model_ns <= FRESH_NS
      if not fresh or evidence.model_ns < self.last_model:
        self.stable_since = self.last_model = 0
      elif evidence.model_ns > self.last_model:
        if not self.stable_since:
          self.stable_since = now
        self.last_model = evidence.model_ns
      elif now - evidence.model_ns > FRESH_NS:
        self.stable_since = 0
      # Inactivity/intervention consumes the request immediately. Missing lane
      # context may become available before the deadline, never after refusal.
      intervention = not active or car.brakePressed or car.gasPressed or car.steeringPressed or abs(car.steeringTorque) > 15
      if intervention or now - self.request_ns >= DELAY_NS:
        problem = self._problem(now, car, active, evidence, context, departing=True)
        if problem:
          self.phase, self.reason = 'consumed', problem
        else:
          self.phase, self.reason = 'running', 'one_lane_change_requested'
          self.started_ns, start = now, True
    elif clock_ok and self.phase == 'running':
      problem = self._problem(now, car, active, evidence, context, departing=False)
      if evidence.model_ns < self.last_model:
        problem = problem or 'model_time_reversed'
      self.last_model = evidence.model_ns
      if now - self.started_ns >= MANEUVER_TIMEOUT_NS:
        problem = problem or 'maneuver_timeout'
      if problem:
        self.phase, self.reason, abort = 'consumed', problem, True
    self.last_clock = now if type(now) is int and now > 0 else self.last_clock
    self.last_signal = current
    return LaneChangeDecision(self.phase, self.direction, start, abort, self.reason)
