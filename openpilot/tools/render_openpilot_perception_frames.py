#!/usr/bin/env python3
"""Render openpilot lane/path/lead predictions and emit raw BGR frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterator

import cv2 as cv
import numpy as np

try:
    from tools.run_openpilot_perception import (
        CameraPreprocessor,
        current_lead,
        lead_speed_estimate,
        openpilot_lead_distance,
    )
except ModuleNotFoundError:  # Direct execution from openpilot/tools.
    from run_openpilot_perception import (
        CameraPreprocessor,
        current_lead,
        lead_speed_estimate,
        openpilot_lead_distance,
    )


GREEN = (80, 230, 110)
WHITE = (245, 245, 245)
RED = (60, 70, 255)
AMBER = (40, 190, 255)
CYAN = (255, 220, 80)


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def project(points: np.ndarray, transform: np.ndarray, width: int, height: int) -> np.ndarray:
    if points.size == 0:
        return np.empty((0, 2), dtype=np.float32)
    projected = (transform @ points.T).T
    valid = projected[:, 2] > 0.05
    result = np.full((len(points), 2), np.nan, dtype=np.float32)
    result[valid] = projected[valid, :2] / projected[valid, 2:3]
    in_view = (
        valid
        & (result[:, 0] > -500)
        & (result[:, 0] < width + 500)
        & (result[:, 1] > -500)
        & (result[:, 1] < height + 500)
    )
    return result[in_view]


def line_polygon(
    points: np.ndarray,
    half_width: float,
    z_offset: float,
    transform: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    points = points[(points[:, 0] >= 1.0) & (points[:, 0] <= 100.0)]
    if len(points) < 2:
        return np.empty((0, 2), dtype=np.int32)
    left = points.copy()
    right = points.copy()
    left[:, 1] -= half_width
    right[:, 1] += half_width
    left[:, 2] += z_offset
    right[:, 2] += z_offset
    left_2d = project(left, transform, width, height)
    right_2d = project(right, transform, width, height)
    count = min(len(left_2d), len(right_2d))
    if count < 2:
        return np.empty((0, 2), dtype=np.int32)
    return np.vstack((left_2d[:count], right_2d[:count][::-1])).round().astype(np.int32)


def alpha_polygon(frame: np.ndarray, polygon: np.ndarray, color: tuple[int, int, int], alpha: float) -> None:
    if len(polygon) < 3:
        return
    height, width = frame.shape[:2]
    x0 = max(0, int(np.min(polygon[:, 0])))
    y0 = max(0, int(np.min(polygon[:, 1])))
    x1 = min(width, int(np.max(polygon[:, 0])) + 1)
    y1 = min(height, int(np.max(polygon[:, 1])) + 1)
    if x0 >= x1 or y0 >= y1:
        return
    # Blending a polygon used to copy the complete 1928x1208 image.  A live
    # frame can contain path + four lanes + two road edges, so limiting work
    # to the clipped bounding box materially lowers display latency.
    roi = frame[y0:y1, x0:x1]
    overlay = roi.copy()
    local_polygon = polygon - np.array([x0, y0], dtype=np.int32)
    cv.fillPoly(overlay, [local_polygon], color, cv.LINE_AA)
    cv.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0, roi)


def alpha_rectangle(
    frame: np.ndarray,
    top_left: tuple[int, int],
    bottom_right: tuple[int, int],
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    height, width = frame.shape[:2]
    x0, y0 = max(0, top_left[0]), max(0, top_left[1])
    x1, y1 = min(width, bottom_right[0]), min(height, bottom_right[1])
    if x0 >= x1 or y0 >= y1:
        return
    roi = frame[y0:y1, x0:x1]
    overlay = np.full_like(roi, color)
    cv.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0, roi)


def draw_label(
    frame: np.ndarray,
    value: str,
    origin: tuple[int, int],
    color: tuple[int, int, int] = WHITE,
    scale: float = 0.7,
) -> None:
    cv.putText(frame, value, origin, cv.FONT_HERSHEY_DUPLEX, scale, (0, 0, 0), 5, cv.LINE_AA)
    cv.putText(frame, value, origin, cv.FONT_HERSHEY_DUPLEX, scale, color, 2, cv.LINE_AA)


def draw_prediction(
    frame: np.ndarray,
    record: dict[str, Any],
    model_intrinsics: np.ndarray,
    view_frame_from_device_frame: np.ndarray,
    rot_from_euler: Any,
    lane_min_prob: float,
    lead_min_prob: float,
    title: str = "openpilot driving_supercombo | analyse hors ligne",
) -> None:
    height, width = frame.shape[:2]
    calibration = record["calibration"]
    rpy = np.asarray(calibration["rpy_rad"], dtype=np.float32)
    device_from_calib = rot_from_euler(rpy)
    transform = model_intrinsics @ view_frame_from_device_frame @ device_from_calib
    camera_height = float(calibration.get("camera_height_m") or 1.22)

    path = np.asarray(record["path"], dtype=np.float32)
    path_polygon = line_polygon(path, 0.9, camera_height, transform, width, height)
    alpha_polygon(frame, path_polygon, GREEN, 0.34)

    for lane in record["lane_lines"]:
        probability = float(lane["prob"])
        if probability < lane_min_prob:
            continue
        points = np.asarray(lane["points"], dtype=np.float32)
        polygon = line_polygon(points, 0.03, 0.0, transform, width, height)
        alpha_polygon(frame, polygon, WHITE, min(0.75, 0.18 + probability * 0.62))

    for edge in record["road_edges"]:
        confidence = float(edge["confidence"])
        if confidence < 0.15:
            continue
        points = np.asarray(edge["points"], dtype=np.float32)
        polygon = line_polygon(points, 0.035, 0.0, transform, width, height)
        alpha_polygon(frame, polygon, RED, min(0.65, confidence * 0.5))

    lead = current_lead(record["leads"])
    lead_probability = float(lead["prob"])
    if lead_probability >= lead_min_prob:
        # Keep compatibility with recordings made before distance_openpilot_m
        # was persisted.  This is the same 1.52 m correction used by radard.py.
        distance = float(
            lead.get("distance_openpilot_m", openpilot_lead_distance(lead["x"][0]))
        )
        lateral = float(lead["y"][0])
        path_z = float(np.interp(distance, path[:, 0], path[:, 2])) if len(path) else 0.0
        point = project(
            np.array([[distance, lateral, path_z + camera_height]], dtype=np.float32),
            transform,
            width,
            height,
        )
        if len(point):
            x, y = point[0].round().astype(int)
            size = int(np.clip(500 / max(distance, 3.0), 22, 70))
            diamond = np.array(
                [[x, y - size], [x + size, y], [x, y + size], [x - size, y]],
                dtype=np.int32,
            )
            alpha_polygon(frame, diamond, AMBER, 0.72)
            draw_label(
                frame,
                f"VEHICULE POSSIBLE {lead_probability:.0%}  {distance:.1f} m",
                (max(15, x - 210), max(35, y - size - 12)),
                AMBER,
                0.62,
            )
            pose = record.get("pose") or []
            model_speed_ms = pose[0] if pose else record.get("speed_ms")
            motion = lead_speed_estimate(
                lead,
                record.get("speed_ms", model_speed_ms),
                model_speed_ms,
            )
            if motion is not None:
                lead_speed_ms, relative_speed_ms = motion
                draw_label(
                    frame,
                    f"VITESSE ~{max(0.0, lead_speed_ms) * 3.6:.0f} km/h   "
                    f"dV {relative_speed_ms * 3.6:+.0f} km/h",
                    (max(15, x - 210), max(59, y - size + 14)),
                    AMBER,
                    0.56,
                )

    lane_probs = [float(lane["prob"]) for lane in record["lane_lines"]]
    alpha_rectangle(frame, (20, 18), (720, 112), (12, 18, 22), 0.72)
    draw_label(frame, title, (38, 52), CYAN, 0.72)
    draw_label(
        frame,
        "Lignes " + " / ".join(f"{prob:.0%}" for prob in lane_probs)
        + f"   Lead {lead_probability:.0%}",
        (38, 88),
        WHITE,
        0.62,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openpilot-root", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--perception", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--start-frame", type=int, required=True)
    parser.add_argument("--frame-count", type=int, required=True)
    parser.add_argument("--lane-min-prob", type=float, default=0.20)
    parser.add_argument("--lead-min-prob", type=float, default=0.50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(args.openpilot_root.resolve()))
    from openpilot.common.transformations.camera import view_frame_from_device_frame
    from openpilot.common.transformations.orientation import rot_from_euler

    preprocessor = CameraPreprocessor(args.calibration)
    capture = cv.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir {args.video}")
    capture.set(cv.CAP_PROP_POS_FRAMES, args.start_frame)

    records = iter_records(args.perception)
    next_record = next(records, None)
    current_record: dict[str, Any] | None = None
    output = sys.stdout.buffer
    next_progress = 10
    for offset in range(args.frame_count):
        frame_index = args.start_frame + offset
        ok, stored = capture.read()
        if not ok or stored is None:
            raise RuntimeError(f"Vidéo interrompue à l'image {frame_index}")
        while next_record is not None and int(next_record["frame_index"]) <= frame_index:
            current_record = next_record
            next_record = next(records, None)
        frame = preprocessor.prepare(stored)
        if current_record is not None:
            draw_prediction(
                frame,
                current_record,
                preprocessor.model_intrinsics,
                view_frame_from_device_frame,
                rot_from_euler,
                args.lane_min_prob,
                args.lead_min_prob,
            )
        try:
            output.write(frame.tobytes())
        except BrokenPipeError:
            return 1
        percent = (offset + 1) / args.frame_count * 100
        if percent >= next_progress:
            print(f"[dessin] {percent:.0f} %", file=sys.stderr, flush=True)
            next_progress += 10
    capture.release()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"Erreur rendu: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
