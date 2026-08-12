#!/usr/bin/env python3
"""Run the real openpilot driving model on an offline camera recording.

The tool loads openpilot's compiled ``driving_supercombo`` through its native
``ModelState`` implementation.  It does not start manager, camerad, controlsd or
any CAN process.  Results are tied to the original camera frame indices and can
optionally be rendered by ``render_openpilot_perception_frames.py``.

The model is not an object detector: its vehicle output represents the lead at
three probability horizons (0, 2 and 4 seconds), not three distinct cars or
bounding boxes for every visible vehicle.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterator

import numpy as np

try:
    import cv2 as cv
except ModuleNotFoundError:  # The backend venv can still inspect/test pure helpers.
    cv = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENPILOT_ROOT = REPO_ROOT.parent / "openpilot"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/openpilot_perception"
OPENPILOT_RADAR_TO_CAMERA_M = 1.52


@dataclass(frozen=True)
class CameraFrame:
    index: int
    timestamp_us: int


def openpilot_lead_distance(model_x_m: float) -> float:
    """Match radard's vision-only dRel origin at the front/radar position."""
    return max(0.0, float(model_x_m) - OPENPILOT_RADAR_TO_CAMERA_M)


def current_lead(leads: list[dict[str, Any]]) -> dict[str, Any]:
    if not leads:
        raise ValueError("Aucune prédiction de véhicule précédent")
    # leads[0] is probTime=0.  Entries 1/2 are the 2 s and 4 s probability
    # horizons; they are not alternative detected cars to rank by probability.
    return leads[0]


class FrameBuffer:
    def __init__(self, data: np.ndarray):
        self.data = data


class CameraPreprocessor:
    """Reproduce the calibrated webcam-to-openpilot model view."""

    def __init__(self, calibration_path: Path):
        if cv is None:
            raise RuntimeError(
                "OpenCV est requis; utiliser l'environnement .venv d'openpilot"
            )
        self.payload = json.loads(calibration_path.read_text(encoding="utf-8"))
        self.image_width = int(self.payload["image_width"])
        self.image_height = int(self.payload["image_height"])
        self.camera_matrix = np.asarray(self.payload["camera_matrix"], dtype=np.float64)
        self.distortion = np.asarray(self.payload["distortion_coefficients"], dtype=np.float64)
        self.optimal_matrix = np.asarray(self.payload["optimal_camera_matrix"], dtype=np.float64)
        self.valid_roi = tuple(int(value) for value in self.payload["valid_roi"])

        model = self.payload["model_input"]
        self.model_width = int(model["width"])
        self.model_height = int(model["height"])
        self.rotate_180 = bool(model.get("rotate_180"))
        crop = model["aspect_crop"]
        self.crop = (
            int(crop["x"]),
            int(crop["y"]),
            int(crop["width"]),
            int(crop["height"]),
        )
        self.model_intrinsics = np.asarray(model["camera_matrix"], dtype=np.float32)
        self._map_x, self._map_y = cv.initUndistortRectifyMap(
            self.camera_matrix,
            self.distortion,
            None,
            self.optimal_matrix,
            (self.image_width, self.image_height),
            cv.CV_32FC1,
        )

    def prepare(self, stored_frame: np.ndarray) -> np.ndarray:
        if stored_frame.shape[1] != self.image_width or stored_frame.shape[0] != self.image_height:
            stored_frame = cv.resize(stored_frame, (self.image_width, self.image_height), interpolation=cv.INTER_AREA)

        # record_dataset already applied the requested rotation. Undo it while
        # applying the raw optical calibration, then reproduce the calibrated
        # model-input stages stored in camera_intrinsics.json.
        raw = cv.flip(stored_frame, -1) if self.rotate_180 else stored_frame
        undistorted = cv.remap(raw, self._map_x, self._map_y, cv.INTER_LINEAR)
        roi_x, roi_y, roi_w, roi_h = self.valid_roi
        undistorted = undistorted[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
        undistorted = cv.resize(
            undistorted,
            (self.image_width, self.image_height),
            interpolation=cv.INTER_LINEAR,
        )
        upright = cv.flip(undistorted, -1) if self.rotate_180 else undistorted
        crop_x, crop_y, crop_w, crop_h = self.crop
        cropped = upright[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
        return cv.resize(
            cropped,
            (self.model_width, self.model_height),
            interpolation=cv.INTER_LINEAR,
        )


class Nv12Buffer:
    def __init__(self, width: int, height: int, get_nv12_info: Any):
        self.width = width
        self.height = height
        self.stride, self.y_height, self.uv_height, size = get_nv12_info(width, height)
        self.array = np.zeros(size, dtype=np.uint8)
        self.buffer = FrameBuffer(self.array)
        self.y_plane = self.array[:self.stride * self.y_height].reshape(self.y_height, self.stride)
        uv_offset = self.stride * self.y_height
        self.uv_plane = self.array[
            uv_offset:uv_offset + self.stride * self.uv_height
        ].reshape(self.uv_height, self.stride)

    def update(self, frame: np.ndarray) -> FrameBuffer:
        if cv is None:
            raise RuntimeError(
                "OpenCV est requis; utiliser l'environnement .venv d'openpilot"
            )
        i420 = cv.cvtColor(frame, cv.COLOR_BGR2YUV_I420).reshape(-1)
        y_size = self.width * self.height
        uv_size = y_size // 4
        y = i420[:y_size].reshape(self.height, self.width)
        u = i420[y_size:y_size + uv_size].reshape(self.height // 2, self.width // 2)
        v = i420[y_size + uv_size:y_size + 2 * uv_size].reshape(self.height // 2, self.width // 2)
        self.y_plane[:self.height, :self.width] = y
        self.uv_plane[:self.height // 2, :self.width:2] = u
        self.uv_plane[:self.height // 2, 1:self.width:2] = v
        return self.buffer


def load_camera_frames(path: Path) -> list[CameraFrame]:
    frames: list[CameraFrame] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            frame = CameraFrame(int(payload["frame_index"]), int(payload["timestamp_us"]))
            if frames and (
                frame.index != frames[-1].index + 1
                or frame.timestamp_us <= frames[-1].timestamp_us
            ):
                raise ValueError(f"{path}:{line_number}: chronologie caméra invalide")
            frames.append(frame)
    if not frames:
        raise ValueError(f"Aucune image dans {path}")
    if frames[0].index != 0:
        raise ValueError(f"{path}: la chronologie caméra doit commencer à l'image 0")
    return frames


def find_video(session_dir: Path) -> Path:
    preferred = session_dir / "road.mp4"
    if preferred.is_file():
        return preferred
    candidates = sorted(session_dir.glob("*.mp4"))
    if len(candidates) != 1:
        raise ValueError(f"Impossible de sélectionner une vidéo unique dans {session_dir}")
    return candidates[0]


def load_speed_by_frame(path: Path | None) -> dict[int, float]:
    if path is None or not path.is_file():
        return {}
    result: dict[int, float] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            payload = json.loads(line)
            speed = payload.get("speed_kph")
            if isinstance(speed, (int, float)) and math.isfinite(float(speed)):
                result[int(payload["frame_index"])] = max(0.0, float(speed) / 3.6)
    return result


def output_record(
    frame: CameraFrame,
    output: dict[str, np.ndarray],
    model_execution_ms: float,
    rpy: np.ndarray,
    calibrator: Any,
    speed_ms: float,
    first_timestamp_us: int,
    model_constants: Any,
) -> dict[str, Any]:
    lane_probs = output["lane_lines_prob"][0, 1::2]
    lane_lines = output["lane_lines"][0]
    road_edges = output["road_edges"][0]
    road_confidence = np.clip(1.0 - output["road_edges_stds"][0, :, 0, 0], 0.0, 1.0)
    plan = output["plan"][0, :, :3]

    lanes = []
    for index in range(4):
        lanes.append({
            "prob": round(float(lane_probs[index]), 6),
            "points": np.column_stack((model_constants.X_IDXS, lane_lines[index])).round(6).tolist(),
        })
    edges = []
    for index in range(2):
        edges.append({
            "confidence": round(float(road_confidence[index]), 6),
            "points": np.column_stack((model_constants.X_IDXS, road_edges[index])).round(6).tolist(),
        })
    leads = []
    for index in range(3):
        trajectory = output["lead"][0, index]
        model_distance = float(trajectory[0, 0])
        leads.append({
            "prob": round(float(output["lead_prob"][0, index]), 6),
            "time_offset_s": float(model_constants.LEAD_T_OFFSETS[index]),
            "distance_model_origin_m": round(model_distance, 6),
            "distance_openpilot_m": round(openpilot_lead_distance(model_distance), 6),
            "x": trajectory[:, 0].round(6).tolist(),
            "y": trajectory[:, 1].round(6).tolist(),
            "v": trajectory[:, 2].round(6).tolist(),
            "a": trajectory[:, 3].round(6).tolist(),
        })

    return {
        "frame_index": frame.index,
        "timestamp_us": frame.timestamp_us,
        "capture_elapsed_s": round((frame.timestamp_us - first_timestamp_us) / 1_000_000, 6),
        "model_execution_ms": round(model_execution_ms, 3),
        "speed_ms": round(speed_ms, 4),
        "calibration": {
            "status": str(calibrator.cal_status),
            "valid_blocks": int(calibrator.valid_blocks),
            "block_progress": int(calibrator.idx),
            "rpy_rad": np.asarray(rpy).round(8).tolist(),
            "rpy_deg": np.degrees(rpy).round(5).tolist(),
            "camera_height_m": round(float(calibrator.height[0]), 4),
        },
        "lane_lines": lanes,
        "road_edges": edges,
        "path": plan.round(6).tolist(),
        "leads": leads,
        "pose": output["pose"][0].round(6).tolist(),
    }


def run_renderer(
    python: Path,
    renderer: Path,
    openpilot_root: Path,
    video: Path,
    perception: Path,
    calibration: Path,
    output: Path,
    start_frame: int,
    frame_count: int,
    width: int,
    height: int,
    fps: float,
    lead_min_prob: float,
    lane_min_prob: float,
) -> None:
    renderer_process = subprocess.Popen(
        [
            str(python),
            str(renderer),
            "--openpilot-root",
            str(openpilot_root),
            "--video",
            str(video),
            "--perception",
            str(perception),
            "--calibration",
            str(calibration),
            "--start-frame",
            str(start_frame),
            "--frame-count",
            str(frame_count),
            "--lead-min-prob",
            str(lead_min_prob),
            "--lane-min-prob",
            str(lane_min_prob),
        ],
        stdout=subprocess.PIPE,
    )
    assert renderer_process.stdout is not None
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "bgr24",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        f"{fps:.9f}",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-frames:v",
        str(frame_count),
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]
    encoder = subprocess.Popen(
        command,
        stdin=renderer_process.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    renderer_process.stdout.close()
    assert encoder.stdout is not None
    next_progress = 10
    tail: list[str] = []
    for line in encoder.stdout:
        line = line.strip()
        tail = (tail + [line])[-40:]
        if line.startswith("frame="):
            try:
                percent = int(line.split("=", 1)[1]) / frame_count * 100
            except ValueError:
                continue
            if percent >= next_progress:
                print(f"[video] encodage {min(percent, 100):.0f} %", flush=True)
                next_progress += 10
    encoder_code = encoder.wait()
    renderer_code = renderer_process.wait()
    if encoder_code or renderer_code:
        raise RuntimeError(
            f"Rendu échoué (dessin={renderer_code}, ffmpeg={encoder_code})\n" + "\n".join(tail)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--openpilot-root", type=Path, default=DEFAULT_OPENPILOT_ROOT)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--can-telemetry", type=Path)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--warmup-seconds", type=float, default=5.0)
    parser.add_argument("--model-hz", type=float, default=20.0)
    parser.add_argument("--lane-min-prob", type=float, default=0.20)
    parser.add_argument("--lead-min-prob", type=float, default=0.50)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-render", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if cv is None:
        raise RuntimeError(
            "OpenCV est requis; exécuter cet outil avec le Python d'openpilot"
        )
    openpilot_root = args.openpilot_root.resolve()
    sys.path.insert(0, str(openpilot_root))
    # Codex sets DEBUG=release; tinygrad requires an integer DEBUG value.
    os.environ.pop("DEBUG", None)

    from openpilot.common.transformations.model import get_warp_matrix
    from openpilot.selfdrive.locationd.calibrationd import Calibrator
    from openpilot.selfdrive.modeld.constants import ModelConstants
    from openpilot.selfdrive.modeld.modeld import ModelState
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

    session_dir = args.session_dir.resolve()
    frames_path = session_dir / "frames.jsonl"
    video_path = (args.video or find_video(session_dir)).resolve()
    calibration_path = (args.calibration or openpilot_root / "camera_intrinsics.json").resolve()
    for required in (frames_path, video_path, calibration_path):
        if not required.is_file():
            raise FileNotFoundError(required)

    frames = load_camera_frames(frames_path)
    start_frame = max(0, args.start_frame)
    stop_frame = len(frames)
    if args.max_frames is not None:
        if args.max_frames <= 0:
            raise ValueError("--max-frames doit être positif")
        stop_frame = min(stop_frame, start_frame + args.max_frames)
    if start_frame >= stop_frame:
        raise ValueError("Plage d'images vide")

    warmup_timestamp = frames[start_frame].timestamp_us - round(max(0.0, args.warmup_seconds) * 1_000_000)
    warmup_start = bisect_left([frame.timestamp_us for frame in frames], warmup_timestamp)
    selected_count = stop_frame - start_frame
    suffix = "" if start_frame == 0 and stop_frame == len(frames) else f"-{start_frame}-{stop_frame}"
    output_dir = (args.output_dir or DEFAULT_OUTPUT_ROOT / session_dir.name).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    perception_path = output_dir / f"perception{suffix}.jsonl"
    report_path = output_dir / f"report{suffix}.json"
    video_output = output_dir / f"{session_dir.name}-openpilot-perception{suffix}.mp4"

    telemetry_path = args.can_telemetry
    if telemetry_path is None:
        candidate = REPO_ROOT / f"data/runtime/camera_can_replays/{session_dir.name}/telemetry.jsonl"
        telemetry_path = candidate if candidate.is_file() else None
    speed_by_frame = load_speed_by_frame(telemetry_path)

    preprocessor = CameraPreprocessor(calibration_path)
    capture = cv.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir {video_path}")
    media_fps = float(capture.get(cv.CAP_PROP_FPS) or 30.0)
    capture.set(cv.CAP_PROP_POS_FRAMES, warmup_start)

    print("[openpilot] chargement du vrai driving_supercombo", flush=True)
    model = ModelState(preprocessor.model_width, preprocessor.model_height, False)
    model.warmup()
    nv12 = Nv12Buffer(preprocessor.model_width, preprocessor.model_height, get_nv12_info)
    calibrator = Calibrator(param_put=False)
    traffic_convention = np.array([1.0, 0.0], dtype=np.float32)
    model_period_us = round(1_000_000 / args.model_hz)
    next_model_timestamp = frames[warmup_start].timestamp_us
    model_runs = 0
    recorded_runs = 0
    lane_detection_counts = np.zeros(4, dtype=np.int64)
    lead_detection_counts = np.zeros(3, dtype=np.int64)
    model_times: list[float] = []
    max_lead_prob = 0.0
    next_progress = 10

    with perception_path.open("w", encoding="utf-8") as perception:
        for frame_index in range(warmup_start, stop_frame):
            ok, stored = capture.read()
            if not ok or stored is None:
                raise RuntimeError(f"Vidéo interrompue à l'image {frame_index}")
            camera_frame = frames[frame_index]
            if camera_frame.timestamp_us < next_model_timestamp:
                continue
            while next_model_timestamp <= camera_frame.timestamp_us:
                next_model_timestamp += model_period_us

            processed = preprocessor.prepare(stored)
            buffer = nv12.update(processed)
            speed_ms = speed_by_frame.get(frame_index, 0.0)
            calibrator.handle_v_ego(speed_ms)
            rpy = np.asarray(calibrator.get_smooth_rpy(), dtype=np.float32)
            transforms = {
                "img": get_warp_matrix(rpy, preprocessor.model_intrinsics, False).astype(np.float32),
                "big_img": get_warp_matrix(rpy, preprocessor.model_intrinsics, True).astype(np.float32),
            }
            inputs = {
                "desire_pulse": np.zeros(ModelConstants.DESIRE_LEN, dtype=np.float32),
                "traffic_convention": traffic_convention,
                "action_t": np.array([0.075, 0.575], dtype=np.float32),
            }
            started = time.perf_counter()
            output = model.run({"img": buffer, "big_img": buffer}, transforms, inputs)
            execution_ms = (time.perf_counter() - started) * 1000
            model_runs += 1
            if output is None:
                continue

            pose = output["pose"][0]
            if frame_index not in speed_by_frame:
                speed_ms = max(0.0, float(pose[0]))
                calibrator.handle_v_ego(speed_ms)
            calibrator.handle_cam_odom(
                pose[:3].tolist(),
                pose[3:].tolist(),
                output["wide_from_device_euler"][0].tolist(),
                output["pose_stds"][0, :3].tolist(),
                output["road_transform"][0, :3].tolist(),
                output["road_transform_stds"][0, :3].tolist(),
            )

            if frame_index >= start_frame:
                record = output_record(
                    camera_frame,
                    output,
                    execution_ms,
                    rpy,
                    calibrator,
                    speed_ms,
                    frames[0].timestamp_us,
                    ModelConstants,
                )
                perception.write(json.dumps(record, ensure_ascii=False) + "\n")
                recorded_runs += 1
                model_times.append(execution_ms)
                lane_probs = output["lane_lines_prob"][0, 1::2]
                lead_probs = output["lead_prob"][0]
                lane_detection_counts += lane_probs >= args.lane_min_prob
                lead_detection_counts += lead_probs >= args.lead_min_prob
                max_lead_prob = max(max_lead_prob, float(np.max(lead_probs)))

            percent = (frame_index - start_frame + 1) / selected_count * 100
            if frame_index >= start_frame and percent >= next_progress:
                print(
                    f"[openpilot] inférence {min(percent, 100):.0f} % "
                    f"({execution_ms:.0f} ms)",
                    flush=True,
                )
                next_progress += 10
    capture.release()

    if recorded_runs == 0:
        raise RuntimeError("Le modèle n'a produit aucun résultat")

    report = {
        "session_id": session_dir.name,
        "offline_readonly": True,
        "model": "openpilot driving_supercombo (native tinygrad ModelState)",
        "source_video": str(video_path),
        "calibration": str(calibration_path),
        "can_telemetry": str(telemetry_path) if telemetry_path else None,
        "frame_range": {
            "start": start_frame,
            "stop_exclusive": stop_frame,
            "count": selected_count,
            "warmup_start": warmup_start,
        },
        "model_runs": recorded_runs,
        "model_hz": args.model_hz,
        "model_execution_ms": {
            "mean": round(sum(model_times) / len(model_times), 3),
            "minimum": round(min(model_times), 3),
            "maximum": round(max(model_times), 3),
        },
        "lane_min_prob": args.lane_min_prob,
        "lane_detection_counts": lane_detection_counts.tolist(),
        "lead_min_prob": args.lead_min_prob,
        "lead_detection_counts": lead_detection_counts.tolist(),
        "max_lead_probability": round(max_lead_prob, 6),
        "limitations": [
            "Les leads openpilot sont des horizons de probabilité 0/2/4 s et non trois voitures ou des boîtes d'objets.",
            "La distance affichée suit radard: x modèle moins RADAR_TO_CAMERA (1,52 m).",
            "La caméra USB n'a pas les mêmes caractéristiques qu'une caméra comma; la calibration locale est appliquée.",
            "Le résultat est une analyse hors ligne et n'autorise aucune commande véhicule.",
        ],
        "outputs": {
            "perception": str(perception_path),
            "video": None if args.no_render else str(video_output),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[openpilot] résultats: {perception_path}", flush=True)

    if not args.no_render:
        run_renderer(
            Path(sys.executable),
            Path(__file__).with_name("render_openpilot_perception_frames.py"),
            openpilot_root,
            video_path,
            perception_path,
            calibration_path,
            video_output,
            start_frame,
            selected_count,
            preprocessor.model_width,
            preprocessor.model_height,
            media_fps,
            args.lead_min_prob,
            args.lane_min_prob,
        )
        print(f"[video] terminé: {video_output}", flush=True)
    print(f"[rapport] {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
