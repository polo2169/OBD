"""Curve anticipation for the optional cristianku-style EPS renewal schedule.

The lifecycle enforces the 3 s cooldown and 12 s deadline. This gate only
selects an earlier straight-road opportunity before a predicted curve.
"""
import math

MODEL_TIMEOUT_NS = 150_000_000
STRAIGHT_LAT_ACCEL = .30
CURVE_LAT_ACCEL = .50
PREDICTION_SECONDS = 5.


def preempt_problem(car, model):
  try:
    if not math.isfinite(car.yawRate * car.vEgo):
      return 'nonfinite_lateral_accel'
    # CarState/model values cross float32 serialization; keep the exact
    # inclusive threshold from changing due to its representation noise.
    if round(abs(car.yawRate * car.vEgo), 6) > STRAIGHT_LAT_ACCEL:
      return 'current_curve'
    times, yaw, speeds = model.orientationRate.t, model.orientationRate.z, model.velocity.x
    if not 2 <= len(times) == len(yaw) == len(speeds):
      return 'prediction_shape_invalid'
    previous = None
    curve = False
    for t, rate, speed in zip(times, yaw, speeds, strict=True):
      if not all(math.isfinite(v) for v in (t, rate, speed)) or t < 0 or speed < 0:
        return 'prediction_nonfinite_or_negative'
      if previous is None:
        if t > .1:
          return 'prediction_start_missing'
      elif not 0 < t - previous <= .5:
        return 'prediction_time_invalid'
      previous = t
      if 0 < t <= PREDICTION_SECONDS and round(abs(rate * speed), 6) >= CURVE_LAT_ACCEL:
        curve = True
      if t >= PREDICTION_SECONDS:
        return None if curve else 'no_upcoming_curve'
    return 'prediction_too_short'
  except (AttributeError, TypeError, ValueError):
    return 'prediction_invalid'


class T9EpsCycleGate:
  def __init__(self):
    self.last_clock = self.last_model = 0
    self.ready = False
    self.reason = 'initializing'

  def update(self, now, *, eligible, car, model, model_valid, model_ns):
    clock_ok = type(now) is int and now > 0 and (not self.last_clock or 0 <= now - self.last_clock <= 150_000_000)
    fresh = model_valid and 0 < model_ns <= now and now - model_ns <= MODEL_TIMEOUT_NS
    driver = float(car.steeringTorque)
    self.reason = ('ineligible' if not eligible else 'clock_invalid' if not clock_ok
      else 'model_stale_or_invalid' if not fresh else 'model_time_reversed' if model_ns < self.last_model
      else 'blinker' if car.leftBlinker or car.rightBlinker
      else 'driver_override' if car.steeringPressed or not math.isfinite(driver) or abs(driver) > 15
      else 'lateral_paused' if car.psaLateralPaused else preempt_problem(car, model))
    self.last_clock = now if type(now) is int and now > 0 else self.last_clock
    self.last_model = model_ns if fresh else 0
    self.ready = self.reason is None
    if self.ready:
      self.reason = 'early_curve_ready'
    return self.ready
