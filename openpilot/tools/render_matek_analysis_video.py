#!/usr/bin/env python3
"""Render synchronized GoPro/Matek analysis videos and a summary graph.

The renderer is strictly offline.  It reads an existing ``live-*`` recording
and the trace produced by ``simulate_t9_torque.py``; it never opens a serial
port and never sends CAN frames.

Each output video contains the road image, 20-second scrolling plots for GPS
speed, yaw rate, lateral acceleration and attitude, plus the current Matek/GPS
status.  CAN values are hidden whenever the simulator marked them stale.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Sequence

import cv2 as cv
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/matek_video_analysis"

BG = (13, 17, 22)
PANEL = (23, 29, 36)
GRID = (57, 66, 76)
WHITE = (238, 242, 245)
MUTED = (155, 165, 175)
CYAN = (245, 205, 70)
GREEN = (105, 220, 125)
AMBER = (70, 190, 245)
RED = (90, 105, 245)
BLUE = (240, 145, 75)
PURPLE = (215, 120, 220)


@dataclass(frozen=True)
class Line:
    label: str
    color: tuple[int, int, int]
    times: np.ndarray
    values: np.ndarray


@dataclass
class SessionData:
    session_dir: Path
    session_id: str
    label: str
    frame_times_s: np.ndarray
    trace_times_s: np.ndarray
    speed_can_kph: np.ndarray
    speed_gps_kph: np.ndarray
    yaw_can_deg_s: np.ndarray
    yaw_matek_deg_s: np.ndarray
    lateral_can_ms2: np.ndarray
    lateral_matek_ms2: np.ndarray
    lateral_matek_corrected_ms2: np.ndarray
    can_fresh: np.ndarray
    attitude_times_s: np.ndarray
    roll_deg: np.ndarray
    pitch_deg: np.ndarray
    gps_times_s: np.ndarray
    satellites: np.ndarray
    pdop: np.ndarray
    lateral_slope: float
    lateral_intercept: float
    lateral_correlation: float
    yaw_slope: float
    yaw_intercept: float
    yaw_correlation: float
    gps_speed_slope: float
    gps_speed_intercept: float
    gps_speed_correlation: float
    imu_samples: int
    imu_rate_hz: float
    gps_samples: int
    gps_rate_hz: float
    gps_fix_fraction: float
    gps_distance_km: float


def _float(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if x.size < 2 or float(np.std(x)) < 1e-9 or float(np.std(y)) < 1e-9:
        return math.nan, math.nan, math.nan, math.nan
    slope, intercept = np.polyfit(x, y, 1)
    correlation = float(np.corrcoef(x, y)[0, 1])
    rmse = float(np.sqrt(np.mean((y - (slope * x + intercept)) ** 2)))
    return float(slope), float(intercept), correlation, rmse


def _rate(times_s: Sequence[float]) -> float:
    if len(times_s) < 2:
        return 0.0
    duration = float(times_s[-1] - times_s[0])
    return len(times_s) / duration if duration > 0 else 0.0


def load_frame_times(session_dir: Path) -> tuple[np.ndarray, int]:
    timestamps: list[int] = []
    with (session_dir / "frames.jsonl").open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                payload = json.loads(line)
                timestamps.append(int(payload["timestamp_us"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"frames.jsonl:{line_number}: trame invalide") from exc
    if not timestamps:
        raise ValueError(f"Aucune trame dans {session_dir / 'frames.jsonl'}")
    first = timestamps[0]
    return (np.asarray([(value - first) / 1_000_000 for value in timestamps]), first)


def load_trace_rows(trace_path: Path, session_id: str) -> list[dict[str, str]]:
    with trace_path.open(encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get("session_id") == session_id]
    if not rows:
        raise ValueError(f"Aucune donnée {session_id} dans {trace_path}")
    return rows


def _haversine_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    radius_m = 6_371_000.0
    lat1 = math.radians(float(a["latitude_deg"]))
    lon1 = math.radians(float(a["longitude_deg"]))
    lat2 = math.radians(float(b["latitude_deg"]))
    lon2 = math.radians(float(b["longitude_deg"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(h)))


def load_auxiliary_sensors(
    session_dir: Path,
    first_frame_timestamp_us: int,
) -> dict[str, Any]:
    imu_times: list[float] = []
    attitude_times: list[float] = []
    rolls: list[float] = []
    pitches: list[float] = []
    gps_times: list[float] = []
    satellites: list[float] = []
    pdops: list[float] = []
    valid_gps: list[dict[str, Any]] = []

    with (session_dir / "sensors.jsonl").open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                payload = json.loads(line)
                timestamp_us = int(payload.get("received_timestamp_us", 0))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"sensors.jsonl:{line_number}: mesure invalide") from exc
            elapsed = (timestamp_us - first_frame_timestamp_us) / 1_000_000
            kind = payload.get("type")
            if kind == "imu":
                imu_times.append(elapsed)
            elif kind == "attitude":
                attitude_times.append(elapsed)
                rolls.append(_float(payload.get("roll_deg")))
                pitches.append(_float(payload.get("pitch_deg")))
            elif kind == "gps":
                gps_times.append(elapsed)
                satellites.append(_float(payload.get("satellites")))
                pdops.append(_float(payload.get("pdop")))
                if payload.get("fix_valid") and all(
                    math.isfinite(_float(payload.get(name)))
                    for name in ("latitude_deg", "longitude_deg")
                ):
                    valid_gps.append(payload)

    distance_m = 0.0
    for previous, current in zip(valid_gps, valid_gps[1:]):
        dt = (
            int(current["received_timestamp_us"])
            - int(previous["received_timestamp_us"])
        ) / 1_000_000
        step = _haversine_m(previous, current)
        if dt > 0 and step / dt < 60.0:
            distance_m += step

    return {
        "attitude_times": np.asarray(attitude_times, dtype=float),
        "rolls": np.asarray(rolls, dtype=float),
        "pitches": np.asarray(pitches, dtype=float),
        "gps_times": np.asarray(gps_times, dtype=float),
        "satellites": np.asarray(satellites, dtype=float),
        "pdops": np.asarray(pdops, dtype=float),
        "imu_samples": len(imu_times),
        "imu_rate_hz": _rate(imu_times),
        "gps_samples": len(gps_times),
        "gps_rate_hz": _rate(gps_times),
        "gps_fix_fraction": len(valid_gps) / len(gps_times) if gps_times else 0.0,
        "gps_distance_km": distance_m / 1000,
    }


def load_session(
    session_dir: Path,
    trace_path: Path,
    label: str,
) -> SessionData:
    session_dir = session_dir.resolve()
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    session_id = str(meta.get("session_id") or session_dir.name)
    frame_times, first_frame_timestamp_us = load_frame_times(session_dir)
    rows = load_trace_rows(trace_path, session_id)
    trace_times = np.asarray([_float(row["elapsed_s"]) for row in rows])
    speed_can = np.asarray([_float(row["speed_kph"]) for row in rows])
    speed_gps = np.asarray([_float(row["matek_gps_speed_mps"]) * 3.6 for row in rows])
    yaw_matek = np.asarray([_float(row["matek_yaw_rate_right_deg_s"]) for row in rows])
    lateral_can = np.asarray([_float(row["measured_lateral_accel_yaw_ms2"]) for row in rows])
    lateral_matek = np.asarray([_float(row["matek_lateral_accel_right_ms2"]) for row in rows])
    can_fresh = np.asarray(["can_stale" not in row.get("safety_reasons", "") for row in rows])

    speed_ms = speed_can / 3.6
    yaw_can = np.full(trace_times.shape, math.nan)
    yaw_mask = can_fresh & np.isfinite(lateral_can) & np.isfinite(speed_ms) & (speed_ms >= 1.0)
    yaw_can[yaw_mask] = lateral_can[yaw_mask] / speed_ms[yaw_mask] * 180 / math.pi

    speed_can_visible = speed_can.copy()
    lateral_can_visible = lateral_can.copy()
    speed_can_visible[~can_fresh] = math.nan
    lateral_can_visible[~can_fresh] = math.nan

    moving = can_fresh & np.isfinite(speed_can) & (speed_can >= 10.0)
    lateral_slope, lateral_intercept, lateral_corr, _ = _fit(
        lateral_can[moving], lateral_matek[moving]
    )
    dynamic_lateral = moving & (np.abs(lateral_can) >= 0.3)
    if int(np.count_nonzero(dynamic_lateral)) >= 200:
        dynamic_slope, _dynamic_intercept, _dynamic_corr, _dynamic_rmse = _fit(
            lateral_can[dynamic_lateral], lateral_matek[dynamic_lateral]
        )
        if math.isfinite(dynamic_slope) and abs(dynamic_slope) > 1e-6:
            lateral_slope = dynamic_slope
            # Estimate the zero offset from every fresh moving sample after
            # identifying scale on sufficiently exciting turns.  This avoids
            # the low-excitation slope bias visible in short CAN windows.
            residual = lateral_matek[moving] - lateral_slope * lateral_can[moving]
            lateral_intercept = float(np.median(residual[np.isfinite(residual)]))
    yaw_slope, yaw_intercept, yaw_corr, _ = _fit(yaw_can[moving], yaw_matek[moving])
    gps_slope, gps_intercept, gps_corr, _ = _fit(
        speed_can[moving] / 3.6, speed_gps[moving] / 3.6
    )
    lateral_corrected = np.full(lateral_matek.shape, math.nan)
    if math.isfinite(lateral_slope) and abs(lateral_slope) > 1e-6:
        lateral_corrected = (lateral_matek - lateral_intercept) / lateral_slope

    sensors = load_auxiliary_sensors(session_dir, first_frame_timestamp_us)
    return SessionData(
        session_dir=session_dir,
        session_id=session_id,
        label=label,
        frame_times_s=frame_times,
        trace_times_s=trace_times,
        speed_can_kph=speed_can_visible,
        speed_gps_kph=speed_gps,
        yaw_can_deg_s=yaw_can,
        yaw_matek_deg_s=yaw_matek,
        lateral_can_ms2=lateral_can_visible,
        lateral_matek_ms2=lateral_matek,
        lateral_matek_corrected_ms2=lateral_corrected,
        can_fresh=can_fresh,
        attitude_times_s=sensors["attitude_times"],
        roll_deg=sensors["rolls"],
        pitch_deg=sensors["pitches"],
        gps_times_s=sensors["gps_times"],
        satellites=sensors["satellites"],
        pdop=sensors["pdops"],
        lateral_slope=lateral_slope,
        lateral_intercept=lateral_intercept,
        lateral_correlation=lateral_corr,
        yaw_slope=yaw_slope,
        yaw_intercept=yaw_intercept,
        yaw_correlation=yaw_corr,
        gps_speed_slope=gps_slope,
        gps_speed_intercept=gps_intercept,
        gps_speed_correlation=gps_corr,
        imu_samples=sensors["imu_samples"],
        imu_rate_hz=sensors["imu_rate_hz"],
        gps_samples=sensors["gps_samples"],
        gps_rate_hz=sensors["gps_rate_hz"],
        gps_fix_fraction=sensors["gps_fix_fraction"],
        gps_distance_km=sensors["gps_distance_km"],
    )


def _put_text(
    image: np.ndarray,
    value: str,
    origin: tuple[int, int],
    scale: float = 0.5,
    color: tuple[int, int, int] = WHITE,
    thickness: int = 1,
) -> None:
    cv.putText(image, value, origin, cv.FONT_HERSHEY_DUPLEX, scale, color, thickness, cv.LINE_AA)


def _segments(points: np.ndarray, valid: np.ndarray) -> Iterable[np.ndarray]:
    start: int | None = None
    for index, is_valid in enumerate(valid):
        if is_valid and start is None:
            start = index
        if start is not None and (not is_valid or index == len(valid) - 1):
            end = index if not is_valid else index + 1
            if end - start >= 2:
                yield points[start:end]
            start = None


def draw_graph(
    image: np.ndarray,
    rect: tuple[int, int, int, int],
    title: str,
    unit: str,
    lines: Sequence[Line],
    start_s: float,
    end_s: float,
    y_limit: tuple[float, float],
    show_legend: bool = True,
) -> None:
    x, y, width, height = rect
    cv.rectangle(image, (x, y), (x + width, y + height), PANEL, -1)
    cv.rectangle(image, (x, y), (x + width, y + height), GRID, 1)
    _put_text(image, title, (x + 9, y + 18), 0.42, WHITE, 1)
    _put_text(image, unit, (x + width - 48, y + 18), 0.34, MUTED, 1)
    plot_left = x + 39
    plot_right = x + width - 8
    plot_top = y + 30
    plot_bottom = y + height - 21
    plot_width = max(1, plot_right - plot_left)
    plot_height = max(1, plot_bottom - plot_top)
    ymin, ymax = y_limit
    if ymax <= ymin:
        ymax = ymin + 1

    for index in range(5):
        gx = round(plot_left + index * plot_width / 4)
        cv.line(image, (gx, plot_top), (gx, plot_bottom), GRID, 1, cv.LINE_AA)
    for index in range(5):
        gy = round(plot_top + index * plot_height / 4)
        cv.line(image, (plot_left, gy), (plot_right, gy), GRID, 1, cv.LINE_AA)
    _put_text(image, f"{ymax:g}", (x + 3, plot_top + 5), 0.30, MUTED, 1)
    _put_text(image, f"{ymin:g}", (x + 3, plot_bottom + 4), 0.30, MUTED, 1)
    _put_text(image, f"-{max(0, round(end_s - start_s))}s", (plot_left, y + height - 5), 0.28, MUTED, 1)
    _put_text(image, "0s", (plot_right - 20, y + height - 5), 0.28, MUTED, 1)

    duration = max(0.001, end_s - start_s)
    for line in lines:
        lo = int(np.searchsorted(line.times, start_s, side="left"))
        hi = int(np.searchsorted(line.times, end_s, side="right"))
        if hi - lo < 2:
            continue
        times = line.times[lo:hi]
        values = line.values[lo:hi]
        px = plot_left + (times - start_s) / duration * plot_width
        py = plot_bottom - (values - ymin) / (ymax - ymin) * plot_height
        valid = np.isfinite(px) & np.isfinite(py) & (values >= ymin - 10 * (ymax - ymin)) & (
            values <= ymax + 10 * (ymax - ymin)
        )
        safe_px = np.where(valid, px, plot_left)
        safe_py = np.where(valid, np.clip(py, plot_top, plot_bottom), plot_bottom)
        points = np.column_stack((safe_px, safe_py)).round().astype(np.int32)
        for segment in _segments(points, valid):
            cv.polylines(image, [segment.reshape((-1, 1, 2))], False, line.color, 2, cv.LINE_AA)

    if show_legend:
        legend_x = x + max(104, 12 + len(title) * 7)
        for line in lines:
            cv.line(image, (legend_x, y + 14), (legend_x + 14, y + 14), line.color, 2, cv.LINE_AA)
            _put_text(image, line.label, (legend_x + 18, y + 18), 0.30, MUTED, 1)
            legend_x += 22 + len(line.label) * 7


def _nearest(times: np.ndarray, values: np.ndarray, when: float) -> float:
    if times.size == 0 or values.size == 0:
        return math.nan
    index = bisect.bisect_left(times, when)
    if index >= len(times):
        index = len(times) - 1
    elif index and abs(times[index - 1] - when) <= abs(times[index] - when):
        index -= 1
    return float(values[index])


def _format(value: float, digits: int = 1, suffix: str = "") -> str:
    return f"{value:.{digits}f}{suffix}" if math.isfinite(value) else "--"


def _symmetric_limit(values: Sequence[np.ndarray], minimum: float, cap: float) -> tuple[float, float]:
    finite = np.concatenate([value[np.isfinite(value)] for value in values if value.size])
    if finite.size:
        bound = float(np.percentile(np.abs(finite), 99.5)) * 1.15
    else:
        bound = minimum
    bound = min(cap, max(minimum, math.ceil(bound)))
    return -bound, bound


def graph_specs(data: SessionData) -> list[tuple[str, str, list[Line], tuple[float, float]]]:
    speed_values = np.concatenate(
        [data.speed_can_kph[np.isfinite(data.speed_can_kph)], data.speed_gps_kph[np.isfinite(data.speed_gps_kph)]]
    )
    speed_max = max(30.0, math.ceil(float(np.percentile(speed_values, 99.5)) / 10) * 10) if speed_values.size else 50.0
    return [
        (
            "VITESSE",
            "km/h",
            [
                Line("GPS", CYAN, data.trace_times_s, data.speed_gps_kph),
                Line("CAN", GREEN, data.trace_times_s, data.speed_can_kph),
            ],
            (0.0, speed_max),
        ),
        (
            "LACET",
            "deg/s",
            [
                Line("Matek", CYAN, data.trace_times_s, data.yaw_matek_deg_s),
                Line("CAN", GREEN, data.trace_times_s, data.yaw_can_deg_s),
            ],
            _symmetric_limit([data.yaw_matek_deg_s, data.yaw_can_deg_s], 8.0, 40.0),
        ),
        (
            "ACCEL. LATERALE",
            "m/s2",
            [
                Line("Matek corr.", CYAN, data.trace_times_s, data.lateral_matek_corrected_ms2),
                Line("CAN", GREEN, data.trace_times_s, data.lateral_can_ms2),
            ],
            _symmetric_limit([data.lateral_matek_corrected_ms2, data.lateral_can_ms2], 2.0, 8.0),
        ),
        (
            "ATTITUDE INAV",
            "deg",
            [
                Line("Roulis", BLUE, data.attitude_times_s, data.roll_deg),
                Line("Tangage", PURPLE, data.attitude_times_s, data.pitch_deg),
            ],
            _symmetric_limit([data.roll_deg, data.pitch_deg], 10.0, 45.0),
        ),
    ]


def draw_dashboard(
    road_frame: np.ndarray,
    data: SessionData,
    elapsed_s: float,
    output_size: tuple[int, int],
    window_s: float,
) -> np.ndarray:
    width, height = output_size
    image = np.full((height, width, 3), BG, dtype=np.uint8)
    graph_width = round(width * 0.30)
    video_width = width - graph_width
    video_height = round(video_width * 9 / 16)
    resized = cv.resize(road_frame, (video_width, video_height), interpolation=cv.INTER_AREA)
    image[:video_height, :video_width] = resized

    shadow = image[:57, :video_width].copy()
    shadow[:] = (0, 0, 0)
    cv.addWeighted(shadow, 0.62, image[:57, :video_width], 0.38, 0, image[:57, :video_width])
    _put_text(image, f"MATEK F722-SE + GPS 880  |  {data.label}", (16, 25), 0.58, WHITE, 1)
    minutes, seconds = divmod(max(0.0, elapsed_s), 60)
    _put_text(image, f"{int(minutes):02d}:{seconds:04.1f}", (16, 48), 0.48, CYAN, 1)

    trace_index = min(len(data.trace_times_s) - 1, int(np.searchsorted(data.trace_times_s, elapsed_s)))
    gps_speed = float(data.speed_gps_kph[trace_index])
    yaw = float(data.yaw_matek_deg_s[trace_index])
    lateral = float(data.lateral_matek_corrected_ms2[trace_index])
    can_ok = bool(data.can_fresh[trace_index])
    roll = _nearest(data.attitude_times_s, data.roll_deg, elapsed_s)
    pitch = _nearest(data.attitude_times_s, data.pitch_deg, elapsed_s)
    sats = _nearest(data.gps_times_s, data.satellites, elapsed_s)
    pdop = _nearest(data.gps_times_s, data.pdop, elapsed_s)

    bottom_y = video_height
    cv.rectangle(image, (0, bottom_y), (video_width, height), PANEL, -1)
    cards = [
        ("GPS", _format(gps_speed, 1, " km/h"), CYAN),
        ("LACET", _format(yaw, 1, " deg/s"), CYAN),
        ("LAT. CORR.", _format(lateral, 2, " m/s2"), CYAN),
        ("ATTITUDE INAV", f"R {_format(roll, 1)}  P {_format(pitch, 1)}", BLUE),
    ]
    card_width = video_width // len(cards)
    for index, (title, value, color) in enumerate(cards):
        left = index * card_width
        if index:
            cv.line(image, (left, bottom_y + 12), (left, bottom_y + 92), GRID, 1)
        _put_text(image, title, (left + 14, bottom_y + 27), 0.38, MUTED, 1)
        _put_text(image, value, (left + 14, bottom_y + 61), 0.55, color, 1)
    can_color = GREEN if can_ok else RED
    can_text = "CAN FRAIS" if can_ok else "CAN ABSENT/PERIME"
    _put_text(
        image,
        f"IMU {data.imu_rate_hz:.1f} Hz  |  GPS {data.gps_rate_hz:.1f} Hz  "
        f"|  {int(round(sats)) if math.isfinite(sats) else '--'} sats  PDOP {_format(pdop, 2)}",
        (14, bottom_y + 104),
        0.42,
        WHITE,
        1,
    )
    _put_text(image, can_text, (video_width - 177, bottom_y + 104), 0.42, can_color, 1)
    _put_text(
        image,
        f"Correction laterale: (mesure - ({data.lateral_intercept:+.3f})) / ({data.lateral_slope:+.3f})  "
        f"| corr={data.lateral_correlation:+.3f}",
        (14, bottom_y + 134),
        0.38,
        MUTED,
        1,
    )
    _put_text(
        image,
        f"Echelles: lacet {data.yaw_slope:.3f} (corr {data.yaw_correlation:.3f})  "
        f"GPS {data.gps_speed_slope:.3f} (corr {data.gps_speed_correlation:.3f})",
        (14, bottom_y + 160),
        0.38,
        MUTED,
        1,
    )
    _put_text(
        image,
        "Analyse hors ligne en lecture seule - aucune commande vehicule",
        (14, height - 16),
        0.34,
        AMBER,
        1,
    )

    specs = graph_specs(data)
    graph_height = height // len(specs)
    start_s = max(0.0, elapsed_s - window_s)
    graph_end_s = max(0.001, elapsed_s)
    for index, (title, unit, lines, y_limit) in enumerate(specs):
        draw_graph(
            image,
            (video_width, index * graph_height, graph_width, graph_height),
            title,
            unit,
            lines,
            start_s,
            graph_end_s,
            y_limit,
        )
    return image


def selected_frame_indices(frame_times_s: np.ndarray, fps: float, maximum_s: float | None) -> list[int]:
    end = float(frame_times_s[-1])
    if maximum_s is not None:
        end = min(end, maximum_s)
    targets = np.arange(0.0, end + 0.5 / fps, 1 / fps)
    indices = np.searchsorted(frame_times_s, targets, side="left")
    indices = np.clip(indices, 0, len(frame_times_s) - 1)
    # Timestamp jitter can map adjacent target times to the same camera frame.
    return [int(value) for value in indices]


def render_video(
    data: SessionData,
    output_path: Path,
    fps: float,
    output_size: tuple[int, int],
    window_s: float,
    maximum_s: float | None,
) -> dict[str, Any]:
    video_path = data.session_dir / "road.mp4"
    capture = cv.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir {video_path}")
    source_frames = int(capture.get(cv.CAP_PROP_FRAME_COUNT))
    indices = selected_frame_indices(data.frame_times_s[:source_frames], fps, maximum_s)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = output_size
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{fps:g}",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert encoder.stdin is not None
    current_source_index = -1
    road_frame: np.ndarray | None = None
    progress_step = max(1, len(indices) // 20)
    try:
        for output_index, source_index in enumerate(indices):
            while current_source_index < source_index:
                if not capture.grab():
                    raise RuntimeError(f"Lecture interrompue à l'image {current_source_index + 1}")
                current_source_index += 1
            ok, road_frame = capture.retrieve()
            if not ok or road_frame is None:
                raise RuntimeError(f"Décodage interrompu à l'image {source_index}")
            elapsed_s = float(data.frame_times_s[source_index])
            dashboard = draw_dashboard(road_frame, data, elapsed_s, output_size, window_s)
            encoder.stdin.write(dashboard.tobytes())
            if output_index % progress_step == 0 or output_index + 1 == len(indices):
                percent = round(100 * (output_index + 1) / len(indices))
                print(f"[{data.label}] rendu {percent}% ({elapsed_s:.1f}s)", flush=True)
    except (BrokenPipeError, KeyboardInterrupt):
        encoder.kill()
        raise
    finally:
        capture.release()
        try:
            encoder.stdin.close()
        except BrokenPipeError:
            pass
    return_code = encoder.wait()
    if return_code:
        raise RuntimeError(f"ffmpeg a échoué avec le code {return_code}")
    return {
        "path": str(output_path.resolve()),
        "frames": len(indices),
        "fps": fps,
        "duration_s": len(indices) / fps,
        "width": width,
        "height": height,
    }


def draw_summary_column(
    image: np.ndarray,
    data: SessionData,
    rect: tuple[int, int, int, int],
) -> None:
    x, y, width, height = rect
    _put_text(image, data.label, (x + 8, y + 25), 0.68, WHITE, 1)
    duration = float(data.frame_times_s[-1])
    can_duration = float(data.trace_times_s[np.flatnonzero(data.can_fresh)[-1]]) if np.any(data.can_fresh) else 0
    _put_text(
        image,
        f"{duration / 60:.1f} min | {data.gps_distance_km:.2f} km | CAN frais {can_duration:.1f}s",
        (x + 8, y + 50),
        0.42,
        MUTED,
        1,
    )
    specs = graph_specs(data)
    top = y + 64
    graph_height = (height - 64) // len(specs)
    for index, (title, unit, lines, y_limit) in enumerate(specs):
        draw_graph(
            image,
            (x, top + index * graph_height, width, graph_height - 7),
            title,
            unit,
            lines,
            0.0,
            max(0.001, duration),
            y_limit,
            show_legend=True,
        )


def render_summary(datasets: Sequence[SessionData], output_path: Path) -> None:
    width, height = 1920, 1080
    image = np.full((height, width, 3), BG, dtype=np.uint8)
    _put_text(image, "ANALYSE MATEK F722-SE + GPS 880", (34, 48), 1.0, WHITE, 2)
    total_distance = sum(data.gps_distance_km for data in datasets)
    total_duration = sum(float(data.frame_times_s[-1]) for data in datasets)
    _put_text(
        image,
        f"{len(datasets)} trajets | {total_duration / 60:.1f} min | {total_distance:.2f} km | lecture seule",
        (36, 78),
        0.55,
        CYAN,
        1,
    )
    margin = 28
    gap = 18
    column_width = (width - 2 * margin - gap) // max(1, len(datasets))
    for index, data in enumerate(datasets):
        draw_summary_column(
            image,
            data,
            (margin + index * (column_width + gap), 98, column_width, height - 126),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv.imwrite(str(output_path), image):
        raise RuntimeError(f"Impossible d'écrire {output_path}")


def session_report(data: SessionData) -> dict[str, Any]:
    fresh_indices = np.flatnonzero(data.can_fresh)
    return {
        "session_id": data.session_id,
        "label": data.label,
        "duration_s": round(float(data.frame_times_s[-1]), 3),
        "gps_distance_km": round(data.gps_distance_km, 6),
        "imu": {"samples": data.imu_samples, "rate_hz": round(data.imu_rate_hz, 6)},
        "gps": {
            "samples": data.gps_samples,
            "rate_hz": round(data.gps_rate_hz, 6),
            "fix_fraction": round(data.gps_fix_fraction, 6),
        },
        "fresh_can_duration_s": round(
            float(data.trace_times_s[fresh_indices[-1]]) if fresh_indices.size else 0.0, 6
        ),
        "lateral_acceleration_fit": {
            "sensor_equals_slope_times_can_plus_intercept": True,
            "method": "dynamic_turn_scale_and_all_moving_median_offset",
            "slope": round(data.lateral_slope, 6),
            "intercept_ms2": round(data.lateral_intercept, 6),
            "correlation": round(data.lateral_correlation, 6),
        },
        "yaw_rate_fit": {
            "slope": round(data.yaw_slope, 6),
            "intercept_deg_s": round(data.yaw_intercept, 6),
            "correlation": round(data.yaw_correlation, 6),
        },
        "gps_speed_fit": {
            "slope": round(data.gps_speed_slope, 6),
            "intercept_ms": round(data.gps_speed_intercept, 6),
            "correlation": round(data.gps_speed_correlation, 6),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère des vidéos GoPro + graphes Matek synchronisés, hors ligne."
    )
    parser.add_argument("sessions", nargs="+", type=Path, help="Dossiers live-*")
    parser.add_argument("--trace", type=Path, required=True, help="trace.csv du simulateur")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--window-s", type=float, default=20.0)
    parser.add_argument("--max-duration-s", type=float)
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fps <= 0 or args.width < 640 or args.height < 360 or args.window_s <= 0:
        raise ValueError("Paramètres vidéo invalides")
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = [
        load_session(session, args.trace.resolve(), f"TRAJET {index}")
        for index, session in enumerate(args.sessions, 1)
    ]

    summary_path = output_dir / "matek-analysis-summary.png"
    render_summary(datasets, summary_path)
    print(f"[résumé] {summary_path}", flush=True)

    videos: list[dict[str, Any]] = []
    if not args.summary_only:
        for data in datasets:
            videos.append(
                render_video(
                    data,
                    output_dir / f"{data.session_id}-matek-analysis.mp4",
                    args.fps,
                    (args.width, args.height),
                    args.window_s,
                    args.max_duration_s,
                )
            )

    report = {
        "schema_version": 1,
        "mode": "offline_readonly",
        "trace": str(args.trace.resolve()),
        "sessions": [session_report(data) for data in datasets],
        "artifacts": {
            "summary_png": str(summary_path),
            "videos": videos,
        },
        "interpretation": (
            "Les facteurs Matek/CAN qualifient les axes, biais et échelles des capteurs. "
            "Ils ne constituent pas un gain de commande EPS."
        ),
        "attitude_warning": (
            "L'attitude INAV suppose une dynamique de drone et confond une partie des "
            "accélérations du véhicule avec de l'inclinaison; elle ne mesure pas directement "
            "le roulis et le tangage réels de la caisse."
        ),
    }
    report_path = output_dir / "analysis.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[rapport] {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        raise SystemExit(130)
