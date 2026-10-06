#!/usr/bin/env python3
"""Summarize closed T9 rlogs for RVV distance and lateral-envelope tuning.

This is a read-only offline tool. It never opens Panda and never emits CAN.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict, deque
import json
import math
from pathlib import Path
import struct
import sys


SPEED_BINS = ((40, 60), (60, 80), (80, 100), (100, 120), (120, 140), (140, 161))


def finite(value):
  return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def quantiles(values):
  values = sorted(v for v in values if finite(v))
  if not values:
    return None
  def q(frac):
    pos = frac * (len(values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)
  return {"count": len(values), "min": values[0], "p05": q(.05), "p25": q(.25),
          "p50": q(.5), "p75": q(.75), "p95": q(.95), "max": values[-1]}


def speed_bin(speed_kph):
  for low, high in SPEED_BINS:
    if low <= speed_kph < high:
      return f"{low}-{high}"
  return None


def decode_steering(data):
  if len(data) != 8:
    return None
  raw = (data[3] << 3) | (data[4] >> 5)
  return {"torque": raw - 2048 if raw & 1024 else raw,
          "state": (data[4] >> 2) & 7, "factor": data[5] >> 1}


def prior(rows, now, delay_ns=0, max_age_ns=150_000_000):
  target = now - delay_ns
  i = bisect_right([r["ns"] for r in rows], target) - 1
  if i < 0 or target - rows[i]["ns"] > max_age_ns:
    return None
  return rows[i]


class Bucket:
  def __init__(self):
    self.counts = Counter()
    self.values = defaultdict(list)

  def value(self, name, value):
    if finite(value):
      self.values[name].append(float(value))

  def export(self):
    return {"counts": dict(self.counts),
            "values": {name: quantiles(values) for name, values in sorted(self.values.items())}}


class Report:
  def __init__(self):
    self.counts = Counter()
    self.lateral = defaultdict(Bucket)
    self.following = defaultdict(Bucket)
    self.wire = defaultdict(Bucket)
    self.torque_response = defaultdict(Bucket)
    self.alerts = Counter()
    self.following_reasons = Counter()
    self.examples = {"highest_requested_lateral_accel": [], "shortest_headway": [],
                     "highest_closing_speed": []}
    self.routes = defaultdict(lambda: {"segments": 0, "complete_segments": 0,
                                       "duration_s": 0., "max_speed_kph": 0.})

  def keep_example(self, name, row, key, reverse=False, limit=30):
    rows = self.examples[name]
    rows.append(row)
    rows.sort(key=lambda x: x[key], reverse=reverse)
    del rows[limit:]

  def export(self):
    return {
      "scope": "read-only analysis of closed rlogs; no CAN output",
      "speed_bins_kph": [list(b) for b in SPEED_BINS],
      "counts": dict(self.counts), "alerts": dict(self.alerts),
      "following_reasons": dict(self.following_reasons),
      "routes": dict(self.routes),
      "lateral_by_speed": {k: v.export() for k, v in sorted(self.lateral.items())},
      "following_by_speed": {k: v.export() for k, v in sorted(self.following.items())},
      "rvv_wire_by_speed": {k: v.export() for k, v in sorted(self.wire.items())},
      "torque_response_150ms_by_abs_command": {k: v.export() for k, v in sorted(self.torque_response.items())},
      "examples": self.examples,
    }


def audit(path, route, segment, log, report):
  import capnp
  import zstandard

  with zstandard.ZstdDecompressor().stream_reader(path.open("rb")) as stream:
    raw = stream.read()

  car = None
  lateral_plan = None
  model = None
  commands = deque(maxlen=40)
  first_car_ns = last_car_ns = None
  complete = True
  route_stats = report.routes[route]
  route_stats["segments"] += 1

  try:
    events = log.Event.read_multiple_bytes(raw)
    for event in events:
      now = int(event.logMonoTime)
      kind = event.which()
      if kind == "carState":
        s = event.carState
        car = {"ns": now, "valid": bool(event.valid and s.canValid and not s.canTimeout),
               "speed_kph": float(s.vEgoRaw) * 3.6, "speed_ms": float(s.vEgoRaw),
               "yaw_rate": float(s.yawRate), "driver": float(s.steeringTorque),
               "steering_pressed": bool(s.steeringPressed),
               "cruise": bool(s.cruiseState.enabled),
               "setpoint_kph": float(s.cruiseState.speed) * 3.6}
        first_car_ns = now if first_car_ns is None else first_car_ns
        last_car_ns = now
        route_stats["max_speed_kph"] = max(route_stats["max_speed_kph"], car["speed_kph"])

      elif kind == "lateralManeuverPlan":
        lateral_plan = {"ns": now, "valid": bool(event.valid),
                        "curvature": float(event.lateralManeuverPlan.desiredCurvature)}

      elif kind == "modelV2":
        model = {"ns": now, "valid": bool(event.valid),
                 "curvature": float(event.modelV2.action.desiredCurvature)}

      elif kind == "sendcan":
        for frame in event.sendcan:
          if int(frame.address) == 0x3F2 and int(frame.src) == 0:
            decoded = decode_steering(bytes(frame.dat))
            if decoded:
              commands.append({"ns": now, **decoded})
              report.counts["steering_frames"] += 1

      elif kind == "can":
        for frame in event.can:
          if int(frame.address) == 0x3F2 and int(frame.src) == 192:
            report.counts["panda_rejected_steering_frames"] += 1

      elif kind == "controlsState" and car and car["valid"] and now - car["ns"] <= 150_000_000:
        state = event.controlsState
        if state.lateralControlState.which() != "torqueState":
          continue
        torque = state.lateralControlState.torqueState
        if not (event.valid and torque.active):
          continue
        speed_kph = car["speed_kph"]
        key = speed_bin(speed_kph)
        if key is None:
          continue
        bucket = report.lateral[key]
        bucket.counts["active_samples"] += 1
        desired = float(state.desiredCurvature)
        desired_accel = abs(desired * car["speed_ms"] ** 2)
        actual_accel = abs(float(torque.actualLateralAccel))
        output = abs(float(torque.output))
        bucket.value("speed_kph", speed_kph)
        bucket.value("desired_lateral_accel_ms2", desired_accel)
        bucket.value("actual_lateral_accel_ms2", actual_accel)
        bucket.value("controller_output_normalized", output)
        if desired_accel >= .625:
          bucket.counts["at_0p63_envelope"] += 1
        if bool(torque.saturated):
          bucket.counts["controller_saturated"] += 1
        if output >= .99:
          bucket.counts["output_at_limit"] += 1

        source = lateral_plan if lateral_plan and lateral_plan["valid"] and now - lateral_plan["ns"] <= 500_000_000 else model
        if source and source["valid"] and now - source["ns"] <= 500_000_000:
          requested = float(source["curvature"])
          requested_accel = abs(requested * car["speed_ms"] ** 2)
          bucket.value("requested_lateral_accel_before_t9_envelope_ms2", requested_accel)
          if abs(requested) > abs(desired) + 1e-7 and requested_accel > .63:
            bucket.counts["request_clipped_by_t9_envelope"] += 1
          if abs(requested) > 1e-8:
            bucket.value("requested_radius_m", 1. / abs(requested))
          row = {"route": route, "segment": segment, "t_s": now / 1e9,
                 "speed_kph": speed_kph, "requested_lateral_accel_ms2": requested_accel,
                 "desired_lateral_accel_ms2": desired_accel, "actual_lateral_accel_ms2": actual_accel,
                 "output": output, "saturated": bool(torque.saturated)}
          report.keep_example("highest_requested_lateral_accel", row,
                              "requested_lateral_accel_ms2", reverse=True)

        cmd = None
        target_ns = now - 150_000_000
        for candidate in reversed(commands):
          if candidate["ns"] <= target_ns:
            cmd = candidate
            break
        if cmd and target_ns - cmd["ns"] <= 100_000_000 and cmd["state"] == 4 and cmd["factor"] == 100 \
            and not car["steering_pressed"] and abs(car["driver"]) <= 5 and abs(cmd["torque"]) >= 1:
          raw_key = str(min(15, abs(cmd["torque"])))
          response = report.torque_response[raw_key]
          response.counts["samples"] += 1
          response.value("actual_lateral_accel_abs_ms2", actual_accel)
          response.value("gain_abs_ms2_per_raw", actual_accel / abs(cmd["torque"]))

      elif kind == "radarState" and car and car["valid"] and now - car["ns"] <= 150_000_000:
        lead = event.radarState.leadOne
        if not (event.valid and car["cruise"] and lead.status and lead.modelProb >= .75 and car["speed_kph"] >= 40):
          continue
        key = speed_bin(car["speed_kph"])
        if key is None:
          continue
        d_rel, v_rel = float(lead.dRel), float(lead.vRel)
        if d_rel <= 0 or car["speed_ms"] <= 0:
          continue
        bucket = report.following[key]
        headway = d_rel / car["speed_ms"]
        current_gap = 5. + 2. * car["speed_ms"]
        bucket.counts["confident_lead_samples"] += 1
        bucket.value("distance_m", d_rel)
        bucket.value("headway_s", headway)
        bucket.value("relative_speed_ms", v_rel)
        bucket.value("distance_minus_current_2s_plus_5m_gap_m", d_rel - current_gap)
        if abs(v_rel) <= .5:
          bucket.counts["matched_speed_samples"] += 1
          bucket.value("matched_speed_headway_s", headway)
          bucket.value("matched_speed_distance_m", d_rel)
        if v_rel < -.5:
          bucket.counts["closing_samples"] += 1
          bucket.value("closing_speed_kph", -v_rel * 3.6)
          bucket.value("closing_ttc_s", d_rel / -v_rel)
        base = {"route": route, "segment": segment, "t_s": now / 1e9,
                "speed_kph": car["speed_kph"], "distance_m": d_rel,
                "headway_s": headway, "relative_speed_kph": v_rel * 3.6,
                "stock_setpoint_kph": car["setpoint_kph"]}
        report.keep_example("shortest_headway", base, "headway_s")
        report.keep_example("highest_closing_speed", base, "relative_speed_kph")

      elif kind == "customReservedRawData0" and car and now - car["ns"] <= 200_000_000:
        data = bytes(event.customReservedRawData0)
        if len(data) == 32 and data[:4] == b"RVV2":
          _, target_kph, flags, _reserved, *_ = struct.unpack("<4sBBHQQQ", data)
          key = speed_bin(car["speed_kph"])
          if key:
            bucket = report.wire[key]
            bucket.counts["messages"] += 1
            bucket.counts["nonzero_target"] += int(target_kph > 0)
            bucket.value("target_kph", target_kph)
            bucket.value("target_minus_stock_setpoint_kph", target_kph - car["setpoint_kph"])
            bucket.value("flags", flags)

      elif kind == "selfdriveState":
        alert = str(event.selfdriveState.alertType)
        if alert:
          report.alerts[alert] += 1

      elif kind == "logMessage":
        try:
          outer = json.loads(str(event.logMessage))
          message = outer.get("msg", outer.get("msg$s", ""))
          prefix = "psa_t9_rvv_following "
          if isinstance(message, str) and message.startswith(prefix):
            decision = json.loads(message[len(prefix):])
            report.following_reasons[str(decision.get("reason", "unknown"))] += 1
        except (ValueError, TypeError, AttributeError):
          pass
  except capnp.KjException:
    complete = False

  if first_car_ns is not None and last_car_ns is not None:
    route_stats["duration_s"] += max(0., (last_car_ns - first_car_ns) / 1e9)
  route_stats["complete_segments"] += int(complete)
  report.counts["segments"] += 1
  report.counts["complete_segments"] += int(complete)
  return complete


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--schema", type=Path, required=True)
  parser.add_argument("--log-root", type=Path, required=True)
  parser.add_argument("--minimum-route-hex", default="38")
  parser.add_argument("--maximum-route-hex", default="3c")
  parser.add_argument("--output", type=Path, required=True)
  args = parser.parse_args()
  sys.path.insert(0, str(args.schema.resolve()))
  from cereal import log

  low, high = int(args.minimum_route_hex, 16), int(args.maximum_route_hex, 16)
  paths = []
  for path in args.log_root.glob("*/rlog.zst"):
    try:
      route, _, segment = path.parent.name.split("--")
      number, segment = int(route, 16), int(segment)
    except ValueError:
      continue
    if low <= number <= high:
      paths.append((number, segment, route, path))

  report = Report()
  for _number, segment, route, path in sorted(paths):
    complete = audit(path, route, segment, log, report)
    print(f"{path.parent.name}: complete={complete}", file=sys.stderr, flush=True)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(report.export(), indent=2, allow_nan=False) + "\n")
  print(args.output)


if __name__ == "__main__":
  main()
