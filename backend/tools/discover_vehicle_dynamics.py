#!/usr/bin/env python3
"""Rank passive CAN fields against vehicle dynamics already validated in a replay.

The tool never transmits on CAN.  It samples each observed payload at 10 Hz and
compares byte-aligned 8/16-bit fields with three independent references:
four-wheel differential yaw, steering-model yaw and map-route yaw.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Callable


SAMPLE_US = 100_000
TRACK_WIDTH_M = 1.56
WHEELBASE_M = 2.62
STEERING_RATIO = 15.3


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 30 or len(xs) != len(ys):
        return None
    mean_x = fmean(xs)
    mean_y = fmean(ys)
    xx = sum((value - mean_x) ** 2 for value in xs)
    yy = sum((value - mean_y) ** 2 for value in ys)
    if xx <= 1e-12 or yy <= 1e-12:
        return None
    xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return xy / math.sqrt(xx * yy)


def _route_yaw(points: list[dict]) -> list[float | None]:
    headings: list[float] = []
    radius = 10  # chord over roughly two seconds to suppress OSM vertex noise
    for index in range(len(points)):
        before = points[max(0, index - radius)]
        after = points[min(len(points) - 1, index + radius)]
        headings.append(math.atan2(
            float(after["x_m"]) - float(before["x_m"]),
            float(after["y_m"]) - float(before["y_m"]),
        ))

    result: list[float | None] = []
    for index in range(len(points)):
        before_index = max(0, index - radius)
        after_index = min(len(points) - 1, index + radius)
        elapsed_s = (
            float(points[after_index]["t_ms"]) - float(points[before_index]["t_ms"])
        ) / 1000
        if elapsed_s <= 0:
            result.append(None)
            continue
        delta = (headings[after_index] - headings[before_index] + math.pi) % (2 * math.pi) - math.pi
        result.append(math.degrees(delta / elapsed_s))
    return result


def _references(points: list[dict]) -> dict[str, list[float | None]]:
    road = _route_yaw(points)
    wheel: list[float | None] = []
    steering: list[float | None] = []
    lateral: list[float | None] = []
    for point in points:
        speed_kph = float(point.get("speed_kph") or 0)
        wheels = [
            point.get("wheel_front_left_kph"),
            point.get("wheel_rear_left_kph"),
            point.get("wheel_front_right_kph"),
            point.get("wheel_rear_right_kph"),
        ]
        wheel_yaw = None
        if all(isinstance(value, (int, float)) for value in wheels):
            left = (float(wheels[0]) + float(wheels[1])) / 2
            right = (float(wheels[2]) + float(wheels[3])) / 2
            wheel_yaw = math.degrees((right - left) / 3.6 / TRACK_WIDTH_M)
        wheel.append(wheel_yaw)

        angle = point.get("steering_angle_deg")
        steer_yaw = None
        if isinstance(angle, (int, float)):
            road_angle = -(float(angle) - 1.5) / STEERING_RATIO
            steer_yaw = math.degrees(
                (speed_kph / 3.6) / WHEELBASE_M * math.tan(math.radians(road_angle))
            )
        steering.append(steer_yaw)
        lateral.append(
            (speed_kph / 3.6) * math.radians(wheel_yaw)
            if wheel_yaw is not None
            else None
        )
    return {"route_yaw_deg_s": road, "wheel_yaw_deg_s": wheel, "steering_yaw_deg_s": steering, "lateral_accel_ms2": lateral}


def _decoders(length: int) -> list[tuple[str, Callable[[bytes], float]]]:
    result: list[tuple[str, Callable[[bytes], float]]] = []
    for index in range(length):
        result.append((f"byte{index}_u8", lambda data, i=index: float(data[i])))
        result.append((
            f"byte{index}_s8",
            lambda data, i=index: float(data[i] - 256 if data[i] >= 128 else data[i]),
        ))
    for index in range(length - 1):
        for byteorder in ("big", "little"):
            result.append((
                f"byte{index}_{byteorder}_u16",
                lambda data, i=index, order=byteorder: float(
                    int.from_bytes(data[i:i + 2], order, signed=False)
                ),
            ))
            result.append((
                f"byte{index}_{byteorder}_s16",
                lambda data, i=index, order=byteorder: float(
                    int.from_bytes(data[i:i + 2], order, signed=True)
                ),
            ))
    return result


def _sample_frames(path: Path) -> tuple[int, dict[int, dict[int, bytes]], dict[int, int]]:
    first_frame_us: int | None = None
    samples: dict[int, dict[int, bytes]] = defaultdict(dict)
    counts: dict[int, int] = defaultdict(int)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if event.get("type") != "can_frame" or event.get("bus") == "diagnostic":
                continue
            try:
                timestamp_us = int(event["timestamp_us"])
                arbitration_id = int(event["arbitration_id"])
                payload = bytes.fromhex(str(event.get("data_hex") or ""))
            except (KeyError, TypeError, ValueError):
                continue
            if first_frame_us is None:
                first_frame_us = timestamp_us
            sample_index = max(0, (timestamp_us - first_frame_us) // SAMPLE_US)
            samples[arbitration_id][sample_index] = payload
            counts[arbitration_id] += 1
    if first_frame_us is None:
        raise ValueError("Aucune trame CAN exploitable.")
    return first_frame_us, samples, counts


def discover(capture_path: Path, replay_path: Path) -> dict:
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    points = replay["points"]
    references = _references(points)
    _, samples_by_id, frame_counts = _sample_frames(capture_path)

    controls = {
        "route_vs_wheels": _paired_correlation(references["route_yaw_deg_s"], references["wheel_yaw_deg_s"], points),
        "route_vs_steering": _paired_correlation(references["route_yaw_deg_s"], references["steering_yaw_deg_s"], points),
        "wheels_vs_steering": _paired_correlation(references["wheel_yaw_deg_s"], references["steering_yaw_deg_s"], points),
    }
    candidates: list[dict] = []
    for arbitration_id, indexed_payloads in samples_by_id.items():
        if not indexed_payloads:
            continue
        payload_length = max(len(payload) for payload in indexed_payloads.values())
        usable = [
            (index, payload)
            for index, payload in indexed_payloads.items()
            if index < len(points)
            and len(payload) == payload_length
            and float(points[index].get("speed_kph") or 0) >= 10
        ]
        if len(usable) < 100:
            continue
        for field, decoder in _decoders(payload_length):
            values: list[float] = []
            target_values = {name: [] for name in references}
            for index, payload in usable:
                value = decoder(payload)
                if not math.isfinite(value):
                    continue
                refs = {name: series[index] for name, series in references.items()}
                if any(ref is None or not math.isfinite(float(ref)) for ref in refs.values()):
                    continue
                values.append(value)
                for name, ref in refs.items():
                    target_values[name].append(float(ref))
            if len(values) < 100 or max(values) == min(values):
                continue
            correlations = {
                name: _correlation(values, target)
                for name, target in target_values.items()
            }
            wheel_corr = abs(correlations["wheel_yaw_deg_s"] or 0)
            steer_corr = abs(correlations["steering_yaw_deg_s"] or 0)
            lateral_corr = abs(correlations["lateral_accel_ms2"] or 0)
            route_corr = abs(correlations["route_yaw_deg_s"] or 0)
            yaw_score = 0.45 * wheel_corr + 0.40 * steer_corr + 0.15 * route_corr
            lateral_score = 0.70 * lateral_corr + 0.15 * wheel_corr + 0.15 * route_corr
            if max(yaw_score, lateral_score) < 0.48:
                continue
            candidates.append({
                "arbitration_id": f"0x{arbitration_id:03X}",
                "field": field,
                "frame_count": frame_counts[arbitration_id],
                "sample_count": len(values),
                "minimum": min(values),
                "maximum": max(values),
                "correlations": {
                    name: round(value, 4) if value is not None else None
                    for name, value in correlations.items()
                },
                "yaw_score": round(yaw_score, 4),
                "lateral_score": round(lateral_score, 4),
            })
    candidates.sort(key=lambda item: max(item["yaw_score"], item["lateral_score"]), reverse=True)
    return {
        "capture": capture_path.name,
        "replay": replay_path.name,
        "route_method": replay.get("route_method"),
        "controls": controls,
        "candidates": candidates[:80],
        "notes": [
            "Analyse passive uniquement : aucune trame n'est transmise.",
            "Une forte corrélation désigne un candidat, pas encore un décodage constructeur validé.",
            "Le lacet par différence des quatre roues et le modèle volant constituent deux références indépendantes.",
        ],
    }


def _paired_correlation(
    left: list[float | None],
    right: list[float | None],
    points: list[dict],
) -> float | None:
    pairs = [
        (float(x), float(y))
        for x, y, point in zip(left, right, points)
        if x is not None and y is not None and float(point.get("speed_kph") or 0) >= 10
    ]
    value = _correlation([item[0] for item in pairs], [item[1] for item in pairs])
    return round(value, 4) if value is not None else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    replay_path = args.replay or args.capture.with_suffix(".replay.json")
    report = discover(args.capture, replay_path)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
