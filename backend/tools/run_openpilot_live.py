#!/usr/bin/env python3
"""Live, read-only openpilot perception with Peugeot 308 T9 CAN telemetry.

The foreground process must run in openpilot's Python environment (OpenCV,
tinygrad and the compiled driving model).  CAN decoding is deliberately kept in
a child process using the backend environment (cantools and pyserial).  The
child only calls ``Serial.read*``: this tool contains no serial write and never
publishes ``sendcan``.

The camera and model exchange a single latest-frame slot.  A slow model can
therefore increase latency by at most one inference; frames are dropped instead
of being queued behind the vehicle.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import numpy as np

try:
    import cv2 as cv
except ModuleNotFoundError:
    cv = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENPILOT_ROOT = REPO_ROOT.parent / "openpilot"
DEFAULT_DBC = REPO_ROOT / "database/psa/dbc/peugeot_308_t9_2018.dbc"
DEFAULT_BACKEND_PYTHON = REPO_ROOT / "backend/.venv/bin/python"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/openpilot_live"
LANE_CHANGE_SPEED_MIN_KPH = 20.0 * 1.609344
DRIVER_TORQUE_INTENT_RAW = 5.0
DESIRE_NONE = 0
DESIRE_LANE_CHANGE_LEFT = 3
DESIRE_LANE_CHANGE_RIGHT = 4
SERIAL_READ_CHUNK_BYTES = 4096
SERIAL_MAX_LINE_BYTES = 16384
LIVE_CAN_MAX_AGE_S = 0.5
LIVE_CAN_MAX_TRANSPORT_LAG_S = 0.25


@dataclass(frozen=True)
class CompactCanFrame:
    timestamp_us: int
    sequence: int
    address: int
    data: bytes
    flags: int

    @property
    def bus(self) -> str:
        return "diagnostic" if self.flags & 0x40 else "live"


@dataclass(frozen=True)
class CapturedFrame:
    index: int
    monotonic_s: float
    wall_timestamp_us: int
    stored: np.ndarray
    processed: np.ndarray


@dataclass(frozen=True)
class LivePrediction:
    sequence: int
    source_frame_index: int
    record: dict[str, Any]
    execution_ms: float
    end_to_end_ms: float
    rate_hz: float


def parse_compact_can_line(line: str) -> CompactCanFrame | None:
    """Parse the ESP32 gateway's passive ``F,...`` wire format."""
    if not line.startswith("F,"):
        return None
    parts = line.split(",")
    if len(parts) < 6:
        return None
    try:
        timestamp_us = int(parts[1], 16)
        sequence = int(parts[2], 16)
        address = int(parts[3], 16)
        flags = int(parts[4], 16)
        data = bytes.fromhex(parts[5].strip())
    except ValueError:
        return None
    extended = bool(flags & 0x01)
    remote = bool(flags & 0x02)
    dlc = (flags & 0x3C) >> 2
    if (
        timestamp_us < 0
        or timestamp_us > 0xFFFFFFFF
        or sequence < 0
        or sequence > 0xFFFFFFFF
        or address < 0
        or address > (0x1FFFFFFF if extended else 0x7FF)
        or dlc > 8
        or len(data) > 8
        or (not remote and len(data) != dlc)
    ):
        return None
    return CompactCanFrame(timestamp_us, sequence, address, data, flags)


class SerialLineBuffer:
    """Split arbitrary serial chunks without losing fragmented lines."""

    def __init__(self, max_line_bytes: int = SERIAL_MAX_LINE_BYTES) -> None:
        if max_line_bytes <= 0:
            raise ValueError("max_line_bytes doit etre positif")
        self.max_line_bytes = max_line_bytes
        self._pending = bytearray()
        self.discarded_lines = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        self._pending.extend(chunk)
        parts = self._pending.split(b"\n")
        self._pending = bytearray(parts.pop())
        complete: list[bytes] = []
        for part in parts:
            line = part[:-1] if part.endswith(b"\r") else part
            if len(line) > self.max_line_bytes:
                self.discarded_lines += 1
            else:
                complete.append(line)
        if len(self._pending) > self.max_line_bytes:
            # No delimiter was received: drop the corrupt fragment so a serial
            # glitch cannot grow memory indefinitely.
            self._pending.clear()
            self.discarded_lines += 1
        return complete


def can_status_is_fresh(status: dict[str, Any]) -> bool:
    age = status.get("age_s")
    lag = status.get("transport_lag_s")
    return (
        isinstance(age, (int, float))
        and math.isfinite(float(age))
        and float(age) < LIVE_CAN_MAX_AGE_S
        and isinstance(lag, (int, float))
        and math.isfinite(float(lag))
        and float(lag) < LIVE_CAN_MAX_TRANSPORT_LAG_S
    )


def can_status_label(status: dict[str, Any]) -> str:
    if status.get("type") == "disabled":
        return "OFF"
    age = status.get("age_s")
    lag = status.get("transport_lag_s")
    if not isinstance(age, (int, float)):
        return "ATTENTE"
    if float(age) >= LIVE_CAN_MAX_AGE_S:
        return "PERDU"
    if isinstance(lag, (int, float)) and float(lag) >= LIVE_CAN_MAX_TRANSPORT_LAG_S:
        return f"RETARD {float(lag):.1f}s"
    dropped = status.get("gateway_dropped")
    if isinstance(dropped, (int, float)) and int(dropped) > 0:
        return f"OK pertes={int(dropped)}"
    return "OK"


def transmission_text(state: dict[str, Any]) -> str:
    if state.get("reverse"):
        return "R"
    current = state.get("current_gear")
    target = state.get("target_gear")
    if isinstance(current, (int, float)) and 1 <= int(current) <= 6:
        return f"D{int(current)}"
    if (
        isinstance(target, (int, float))
        and 1 <= int(target) <= 6
        and float(state.get("speed_kph") or 0.0) > 0.5
    ):
        return f"cible {int(target)}"
    return "N" if current == 0 else "--"


def turn_signal_sides(value: Any) -> tuple[bool, bool]:
    """Return (left, right) from validated PSA 0x452 encoding."""
    try:
        status = int(value)
    except (TypeError, ValueError):
        return False, False
    return status in {2, 3}, status in {1, 3}


def turn_signal_text(value: Any) -> str:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return "--"
    return {0: "OFF", 1: "DROITE", 2: "GAUCHE", 3: "WARNING"}.get(status, "--")


class PassiveLaneChangeDesire:
    """Read-only approximation of openpilot's DesireHelper for visualization.

    There is no blind-spot sensor on this car, so no blind-spot input is
    invented.  The helper requires a single blinker, the official 20 mph speed
    threshold and validated driver-torque intent.  Once active it keeps the
    desire high until the blinker is released; ModelState itself converts that
    rising edge to the single pulse expected by driving_supercombo.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.phase = "off"
        self.direction: str | None = None
        self.prev_one_blinker = False

    def _reset(self) -> None:
        self.phase = "off"
        self.direction = None

    def update(self, state: dict[str, Any]) -> int:
        left, right = turn_signal_sides(state.get("turn_signal"))
        one_blinker = left != right
        direction = "left" if left else "right" if right else None
        speed = state.get("speed_kph")
        torque = state.get("driver_torque_raw")
        speed_ok = isinstance(speed, (int, float)) and float(speed) >= LANE_CHANGE_SPEED_MIN_KPH

        if not self.enabled or not one_blinker or not speed_ok:
            self._reset()
        elif self.phase == "off" and not self.prev_one_blinker:
            self.phase = "waiting_torque"
            self.direction = direction
        elif self.phase == "waiting_torque":
            self.direction = direction
            torque_ok = isinstance(torque, (int, float)) and (
                (direction == "left" and float(torque) > DRIVER_TORQUE_INTENT_RAW)
                or (direction == "right" and float(torque) < -DRIVER_TORQUE_INTENT_RAW)
            )
            if torque_ok:
                self.phase = "active"
        elif self.phase == "active" and direction != self.direction:
            self.phase = "waiting_torque"
            self.direction = direction

        self.prev_one_blinker = one_blinker
        if self.phase != "active":
            return DESIRE_NONE
        return DESIRE_LANE_CHANGE_LEFT if self.direction == "left" else DESIRE_LANE_CHANGE_RIGHT

    def snapshot(self, desire: int) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "phase": self.phase,
            "direction": self.direction,
            "desire_index": desire,
            "speed_threshold_kph": round(LANE_CHANGE_SPEED_MIN_KPH, 3),
            "torque_threshold_raw": DRIVER_TORQUE_INTENT_RAW,
            "blindspot_available": False,
            "vehicle_control": False,
        }


def autodetect_serial_port(serial_list_ports: Any) -> str:
    candidates = [port.device for port in serial_list_ports.comports()]
    preferred = [
        path
        for path in candidates
        if any(tag in path.lower() for tag in ("usbserial", "usbmodem", "slab", "wchusbserial"))
    ]
    pool = preferred or candidates
    if not pool:
        raise RuntimeError("Aucun port série ESP32 détecté")
    if len(pool) != 1:
        raise RuntimeError("Plusieurs ports série détectés; préciser --port: " + ", ".join(pool))
    return pool[0]


def executable_path(path: Path) -> Path:
    """Return an absolute executable path without dereferencing venv symlinks.

    Python virtual environments commonly expose ``bin/python`` as a symlink to
    the base interpreter.  ``Path.resolve()`` follows it and silently drops the
    virtual environment, so imports installed only in that venv (cantools here)
    are no longer available in the child process.
    """
    return path if path.is_absolute() else Path.cwd() / path


def measured_frame_rate(frame_count: int, first_timestamp_us: int, last_timestamp_us: int) -> float:
    if frame_count < 2 or last_timestamp_us <= first_timestamp_us:
        raise ValueError("Chronologie vidéo insuffisante pour mesurer la cadence")
    return (frame_count - 1) / ((last_timestamp_us - first_timestamp_us) / 1_000_000.0)


def retime_video_in_place(
    path: Path,
    frame_count: int,
    first_timestamp_us: int | None,
    last_timestamp_us: int | None,
    nominal_fps: float,
) -> dict[str, Any] | None:
    """Scale MP4 timestamps without re-encoding, preserving every frame."""
    if (
        not path.is_file()
        or frame_count < 2
        or first_timestamp_us is None
        or last_timestamp_us is None
    ):
        return None
    actual_fps = measured_frame_rate(frame_count, first_timestamp_us, last_timestamp_us)
    scale = nominal_fps / actual_fps
    if abs(scale - 1.0) < 0.005:
        return {"measured_fps": actual_fps, "timestamp_scale": 1.0, "retimed": False}
    temporary = path.with_name(f".{path.stem}.retimed{path.suffix}")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-itsscale",
        f"{scale:.12f}",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    try:
        subprocess.run(command, check=True)
        temporary.replace(path)
    except (FileNotFoundError, subprocess.CalledProcessError):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Impossible de remettre {path.name} à l'heure réelle")
    return {
        "measured_fps": round(actual_fps, 6),
        "timestamp_scale": round(scale, 9),
        "retimed": True,
    }


def emit_worker(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def parse_can_worker_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker CAN passif interne")
    parser.add_argument("--can-worker", action="store_true", required=True)
    parser.add_argument("--port")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--dbc", type=Path, required=True)
    parser.add_argument("--snapshot-hz", type=float, default=20.0)
    parser.add_argument("--raw-output", type=Path)
    return parser.parse_args()


def can_worker_main() -> int:
    """Read and decode CAN. There is intentionally no serial write here."""
    args = parse_can_worker_args()
    import cantools
    import serial
    import serial.tools.list_ports

    from render_camera_can_replay import CanFrame, DecodeCounters, decode_can_frame

    if args.snapshot_hz <= 0:
        raise ValueError("--snapshot-hz doit être positif")
    database = cantools.database.load_file(args.dbc)
    messages = {message.frame_id: message for message in database.messages}
    port = args.port or autodetect_serial_port(serial.tools.list_ports)
    raw_stream = None
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_stream = args.raw_output.open("wb", buffering=1024 * 1024)

    running = True

    def stop_worker(_signum: int, _frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    state: dict[str, Any] = {}
    counters = DecodeCounters()
    snapshot_period = 1.0 / args.snapshot_hz
    last_snapshot = time.monotonic()
    rate_started = last_snapshot
    rate_frames = 0
    reported_rate = 0.0
    raw_last_flush = last_snapshot
    sync_anchor_emitted = False
    last_can_monotonic: float | None = None
    last_transport_lag_s: float | None = None
    max_transport_lag_s = 0.0
    last_sequences: dict[str, int] = {}
    sequence_gap_count = 0
    sequence_reset_count = 0
    malformed_frame_lines = 0
    gateway_stats: dict[str, Any] = {}
    emit_worker({"type": "starting", "port": port, "baud": args.baud, "readonly": True})

    try:
        while running:
            try:
                with serial.Serial(port=port, baudrate=args.baud, timeout=0.05) as serial_port:
                    print(f"[CAN] lecture seule ouverte sur {port}", file=sys.stderr, flush=True)
                    emit_worker({"type": "ready", "port": port, "baud": args.baud, "readonly": True})
                    line_buffer = SerialLineBuffer()
                    pending_decode: dict[int, CanFrame] = {}
                    lag_anchor_timestamp_us: int | None = None
                    lag_anchor_wall_epoch: float | None = None
                    while running:
                        waiting = int(getattr(serial_port, "in_waiting", 0) or 0)
                        raw = serial_port.read(
                            max(1, min(max(waiting, 1), SERIAL_READ_CHUNK_BYTES))
                        )
                        now = time.monotonic()
                        complete_lines = line_buffer.feed(raw)
                        if raw_stream is not None and complete_lines:
                            raw_stream.write(b"\n".join(complete_lines) + b"\n")
                        for raw_line in complete_lines:
                            if not raw_line:
                                continue
                            counters.raw_lines += 1
                            line = raw_line.decode("ascii", errors="ignore").strip()
                            compact = parse_compact_can_line(line)
                            if compact is not None:
                                counters.can_frames += 1
                                rate_frames += 1
                                wall_epoch = time.time()
                                last_can_monotonic = now
                                if not sync_anchor_emitted:
                                    sync_anchor_emitted = True
                                    emit_worker({
                                        "type": "anchor",
                                        "can_first_frame_ts_us": compact.timestamp_us,
                                        "can_first_frame_wall_epoch": wall_epoch,
                                    })

                                previous = last_sequences.get(compact.bus)
                                if previous is not None:
                                    expected = (previous + 1) & 0xFFFFFFFF
                                    if compact.sequence != expected:
                                        if compact.sequence > expected:
                                            sequence_gap_count += compact.sequence - expected
                                        elif not (previous > 0xFFFFFF00 and compact.sequence < 0x100):
                                            sequence_reset_count += 1
                                last_sequences[compact.bus] = compact.sequence

                                if lag_anchor_timestamp_us is None or lag_anchor_wall_epoch is None:
                                    lag_anchor_timestamp_us = compact.timestamp_us
                                    lag_anchor_wall_epoch = wall_epoch
                                source_elapsed_s = (
                                    (compact.timestamp_us - lag_anchor_timestamp_us) & 0xFFFFFFFF
                                ) / 1_000_000.0
                                candidate_lag_s = wall_epoch - lag_anchor_wall_epoch - source_elapsed_s
                                if candidate_lag_s < -1.0:
                                    # The ESP32 restarted: establish a new local lag baseline.
                                    lag_anchor_timestamp_us = compact.timestamp_us
                                    lag_anchor_wall_epoch = wall_epoch
                                    candidate_lag_s = 0.0
                                last_transport_lag_s = max(0.0, candidate_lag_s)
                                max_transport_lag_s = max(
                                    max_transport_lag_s, last_transport_lag_s
                                )

                                # Raw traffic is always preserved. Decoding only the newest
                                # live frame per identifier at the 20 Hz snapshot cadence
                                # avoids starving the serial reader at ~1,570 frames/s.
                                if compact.bus == "live":
                                    pending_decode[compact.address] = CanFrame(
                                        timestamp_us=compact.timestamp_us,
                                        wall_timestamp_us=round(wall_epoch * 1_000_000),
                                        address=compact.address,
                                        data=compact.data,
                                    )
                            elif line.startswith("F,"):
                                malformed_frame_lines += 1
                            elif line.startswith("{"):
                                try:
                                    control = json.loads(line)
                                except json.JSONDecodeError:
                                    control = None
                                if isinstance(control, dict) and control.get("type") == "stats":
                                    gateway_stats = control
                        if raw_stream is not None and now - raw_last_flush >= 1.0:
                            raw_stream.flush()
                            raw_last_flush = now
                        if now - last_snapshot >= snapshot_period:
                            for frame in pending_decode.values():
                                decode_can_frame(frame, messages, state, counters)
                            pending_decode.clear()
                            elapsed = max(now - rate_started, 1e-6)
                            if elapsed >= 1.0:
                                reported_rate = rate_frames / elapsed
                                rate_started = now
                                rate_frames = 0
                            elif reported_rate == 0.0:
                                reported_rate = rate_frames / elapsed
                            can_age_s = (
                                None
                                if last_can_monotonic is None
                                else max(0.0, now - last_can_monotonic)
                            )
                            emit_worker({
                                "type": "state",
                                "state": state,
                                "frames_total": counters.can_frames,
                                "decoded_total": counters.decoded_frames,
                                "decode_errors": counters.decode_errors,
                                "frames_per_second": round(reported_rate, 1),
                                "can_age_s": can_age_s,
                                "transport_lag_s": last_transport_lag_s,
                                "max_transport_lag_s": round(max_transport_lag_s, 6),
                                "serial_backlog_bytes": int(
                                    getattr(serial_port, "in_waiting", 0) or 0
                                ),
                                "sequence_gaps": sequence_gap_count,
                                "sequence_resets": sequence_reset_count,
                                "malformed_frame_lines": malformed_frame_lines,
                                "discarded_serial_lines": line_buffer.discarded_lines,
                                "gateway_dropped": gateway_stats.get("dropped"),
                                "interboard_overflow": gateway_stats.get("interboard_overflow"),
                            })
                            last_snapshot = now
            except serial.SerialException as exc:
                if not running:
                    break
                emit_worker({"type": "disconnected", "error": str(exc)})
                time.sleep(1.0)
    finally:
        if raw_stream is not None:
            raw_stream.close()
    return 0


class LiveCanClient:
    def __init__(
        self,
        backend_python: Path,
        port: str | None,
        baud: int,
        dbc: Path,
        raw_output: Path | None,
    ) -> None:
        command = [
            str(backend_python),
            str(Path(__file__).resolve()),
            "--can-worker",
            "--baud",
            str(baud),
            "--dbc",
            str(dbc),
        ]
        if port:
            command.extend(("--port", port))
        if raw_output:
            command.extend(("--raw-output", str(raw_output)))
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self._status: dict[str, Any] = {"type": "starting", "frames_total": 0}
        self._anchor: dict[str, Any] | None = None
        self._received_monotonic = 0.0
        self._thread = threading.Thread(target=self._read_loop, name="can-state", daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._lock:
                message_type = payload.get("type")
                if message_type == "state":
                    self._state = dict(payload.get("state") or {})
                    self._received_monotonic = time.monotonic()
                elif message_type == "anchor":
                    self._anchor = dict(payload)
                elif message_type == "ready":
                    print(f"[CAN] prêt: {payload.get('port')}", file=sys.stderr, flush=True)
                elif message_type == "disconnected":
                    print(f"[CAN] déconnecté: {payload.get('error')}", file=sys.stderr, flush=True)
                self._status.update(payload)
        with self._lock:
            self._status["type"] = "stopped"
            self._status["returncode"] = self.process.poll()

    def snapshot(self) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._lock:
            status = dict(self._status)
            worker_age_s = (
                None
                if self._received_monotonic == 0.0
                else max(0.0, time.monotonic() - self._received_monotonic)
            )
            status["worker_age_s"] = worker_age_s
            source_age_s = status.get("can_age_s")
            status["age_s"] = (
                float(source_age_s) + float(worker_age_s)
                if isinstance(source_age_s, (int, float))
                and isinstance(worker_age_s, (int, float))
                else None
            )
            return dict(self._state), status

    @property
    def anchor(self) -> dict[str, Any] | None:
        with self._lock:
            return None if self._anchor is None else dict(self._anchor)

    def check_started(self) -> None:
        code = self.process.poll()
        if code is not None:
            raise RuntimeError(f"Le lecteur CAN s'est arrêté au démarrage (code {code})")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1.0)
        self._thread.join(timeout=1.0)


class LatestCamera:
    def __init__(
        self,
        source: int | Path,
        width: int,
        height: int,
        fps: float,
        preprocessor: Any,
        rotate_live_camera: bool,
        video_start_frame: int = 0,
        frame_sink: Any = None,
        is_live_stream: bool = False,
    ) -> None:
        if cv is None:
            raise RuntimeError("OpenCV est requis")
        self.is_live_stream = is_live_stream
        self.is_video = isinstance(source, Path) and not self.is_live_stream
        if self.is_live_stream:
            backend = cv.CAP_FFMPEG
        else:
            backend = cv.CAP_ANY if self.is_video or platform.system() != "Darwin" else cv.CAP_AVFOUNDATION
        capture_source = str(source) if isinstance(source, Path) else source
        self.capture = cv.VideoCapture(capture_source, backend)
        if not self.capture.isOpened():
            raise RuntimeError(f"Impossible d'ouvrir la source caméra {source}")
        if self.is_live_stream:
            # Some backends ignore this property, but those that implement it
            # will discard decoder backlog instead of displaying stale frames.
            self.capture.set(cv.CAP_PROP_BUFFERSIZE, 1)
        if self.is_video and video_start_frame:
            self.capture.set(cv.CAP_PROP_POS_FRAMES, video_start_frame)
        self.start_index = video_start_frame if self.is_video else 0
        self.frame_sink = frame_sink
        if not self.is_video:
            self.capture.set(cv.CAP_PROP_FRAME_WIDTH, width)
            self.capture.set(cv.CAP_PROP_FRAME_HEIGHT, height)
            self.capture.set(cv.CAP_PROP_FPS, fps)
        self.source_fps = float(self.capture.get(cv.CAP_PROP_FPS) or fps)
        self.preprocessor = preprocessor
        self.rotate_live_camera = rotate_live_camera and not self.is_video
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._frame: CapturedFrame | None = None
        self._error: Exception | None = None
        self._ended = False
        self._published_times: deque[float] = deque(maxlen=60)
        self._raw_lock = threading.Lock()
        self._raw_frame: tuple[int, float, int, np.ndarray] | None = None
        self._reader_thread: threading.Thread | None = None
        if self.is_live_stream:
            self._reader_thread = threading.Thread(
                target=self._stream_reader_loop,
                name="road-stream-decoder",
                daemon=True,
            )
        self._thread = threading.Thread(target=self._capture_loop, name="road-camera", daemon=True)
        if self._reader_thread is not None:
            self._reader_thread.start()
        self._thread.start()

    def _stream_reader_loop(self) -> None:
        frame_index = self.start_index
        try:
            while not self._stop.is_set():
                ok, raw = self.capture.read()
                if not ok or raw is None:
                    if not self._stop.is_set():
                        raise RuntimeError("Le flux vidéo ne fournit plus d'image")
                    return
                captured_at = time.monotonic()
                wall_timestamp_us = round(time.time() * 1_000_000)
                with self._raw_lock:
                    # A single latest-frame slot is intentional.  Decoding
                    # keeps consuming the 30 Hz stream while preprocessing may
                    # run slower, so stale frames never accumulate upstream.
                    self._raw_frame = (frame_index, captured_at, wall_timestamp_us, raw)
                frame_index += 1
        except Exception as exc:
            with self._lock:
                self._error = exc

    def _stream_processing_loop(self) -> None:
        last_frame_index = -1
        while not self._stop.is_set():
            with self._raw_lock:
                raw_frame = self._raw_frame
            if raw_frame is None or raw_frame[0] == last_frame_index:
                self._stop.wait(0.001)
                continue
            frame_index, captured_at, wall_timestamp_us, raw = raw_frame
            last_frame_index = frame_index
            stored = cv.flip(raw, -1) if self.rotate_live_camera else raw
            processed = self.preprocessor.prepare(stored)
            frame = CapturedFrame(
                index=frame_index,
                monotonic_s=captured_at,
                wall_timestamp_us=wall_timestamp_us,
                stored=stored,
                processed=processed,
            )
            if self.frame_sink is not None:
                self.frame_sink(frame)
            with self._lock:
                self._frame = frame
                self._published_times.append(time.monotonic())

    def _capture_loop(self) -> None:
        if self.is_live_stream:
            try:
                self._stream_processing_loop()
            except Exception as exc:
                with self._lock:
                    self._error = exc
            return
        frame_index = self.start_index
        next_video_deadline = time.monotonic()
        try:
            while not self._stop.is_set():
                ok, raw = self.capture.read()
                if not ok or raw is None:
                    if self.is_video:
                        with self._lock:
                            self._ended = True
                        return
                    raise RuntimeError("La caméra ne fournit plus d'image")
                if self.is_video:
                    now = time.monotonic()
                    delay = next_video_deadline - now
                    if delay > 0 and self._stop.wait(delay):
                        return
                    next_video_deadline = max(next_video_deadline + 1.0 / self.source_fps, time.monotonic())
                stored = cv.flip(raw, -1) if self.rotate_live_camera else raw
                processed = self.preprocessor.prepare(stored)
                captured_at = time.monotonic()
                frame = CapturedFrame(
                    index=frame_index,
                    monotonic_s=captured_at,
                    wall_timestamp_us=round(time.time() * 1_000_000),
                    stored=stored,
                    processed=processed,
                )
                if self.frame_sink is not None:
                    self.frame_sink(frame)
                with self._lock:
                    self._frame = frame
                    self._published_times.append(captured_at)
                frame_index += 1
        except Exception as exc:  # surfaced in the UI thread
            with self._lock:
                self._error = exc

    def latest(self) -> CapturedFrame | None:
        with self._lock:
            return self._frame

    @property
    def rate_hz(self) -> float:
        with self._lock:
            if len(self._published_times) < 2:
                return 0.0
            return (len(self._published_times) - 1) / (
                self._published_times[-1] - self._published_times[0]
            )

    @property
    def ended(self) -> bool:
        with self._lock:
            return self._ended

    @property
    def error(self) -> Exception | None:
        with self._lock:
            return self._error

    def close(self) -> None:
        self._stop.set()
        if self._reader_thread is not None:
            # A live read returns at the next frame (~33 ms).  Let the decoder
            # observe the stop flag before releasing its VideoCapture; calling
            # release concurrently with FFmpeg's read can crash OpenCV.
            self._reader_thread.join(timeout=2.0)
        self.capture.release()
        self._thread.join(timeout=2.0)


class OnnxModelState:
    """Run the policy with ONNX Runtime while retaining openpilot's warp."""

    FRAME_SKIP = 4

    def __init__(self, native_model: Any, onnx_path: Path) -> None:
        try:
            import onnxruntime as ort
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "onnxruntime absent; installer avec: "
                "uv pip install --python ../openpilot/.venv/bin/python onnxruntime"
            ) from exc
        from tinygrad.tensor import Tensor
        from openpilot.selfdrive.modeld.get_model_metadata import make_metadata_dict

        if not onnx_path.is_file():
            raise FileNotFoundError(onnx_path)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(onnx_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.native = native_model
        self.Tensor = Tensor
        # The checked-in Darwin pickle may have been built from the optional
        # 1.6 GB big model.  Always take slices from the ONNX file actually
        # selected here; mixing the two layouts silently corrupts recurrent
        # state (small: 2576 outputs, big: 2580 outputs).
        metadata = make_metadata_dict(onnx_path)
        self.output_slices = metadata["output_slices"]
        self.parser = native_model.parser
        img_shape = tuple(int(value) for value in metadata["input_shapes"]["img"])
        if img_shape[0:2] != (1, 12):
            raise RuntimeError(f"Forme image openpilot inattendue: {img_shape}")
        self.image_shape = img_shape[2:]
        self._reset_history()

    def _reset_history(self) -> None:
        self.img_history = np.zeros((5, 6, *self.image_shape), dtype=np.uint8)
        self.big_img_history = np.zeros_like(self.img_history)
        self.feature_history = np.zeros((96, 512), dtype=np.float16)
        self.desire_history = np.zeros((100, 8), dtype=np.float16)
        self.prev_desire = np.zeros(8, dtype=np.float32)
        self.prev_feature = np.zeros(512, dtype=np.float16)

    @staticmethod
    def _shift(history: np.ndarray, value: np.ndarray) -> None:
        history[:-1] = history[1:]
        history[-1] = value

    def run(
        self,
        bufs: dict[str, Any],
        transforms: dict[str, np.ndarray],
        inputs: dict[str, np.ndarray],
    ) -> dict[str, np.ndarray]:
        full_frames: dict[str, Any] = {}
        for key, buf in bufs.items():
            array = np.frombuffer(buf.data, dtype=np.uint8)
            pointer = array.ctypes.data
            yuv_size = self.native.frame_buf_params[key][3]
            full_frames[key] = self.Tensor.from_blob(
                pointer,
                (yuv_size,),
                dtype="uint8",
                device=self.native.WARP_DEV,
            )

        self.native.npy["tfm"][:, :] = transforms["img"]
        self.native.npy["big_tfm"][:, :] = transforms["big_img"]
        warped = self.native.warp(
            **{key: self.native.input_queues[key] for key in ("tfm", "big_tfm")},
            frame=full_frames["img"],
            big_frame=full_frames["big_img"],
        ).numpy()
        if warped.shape != (2, 6, *self.image_shape):
            raise RuntimeError(f"Sortie warp openpilot inattendue: {warped.shape}")

        self._shift(self.img_history, warped[0])
        self._shift(self.big_img_history, warped[1])
        self._shift(self.feature_history, self.prev_feature)

        desire = np.asarray(inputs["desire_pulse"], dtype=np.float32)
        desire_pulse = np.where(desire - self.prev_desire > 0.99, desire, 0.0)
        self.prev_desire[:] = desire
        self._shift(self.desire_history, desire_pulse.astype(np.float16))

        feeds = {
            "img": self.img_history[::self.FRAME_SKIP].reshape(1, 12, *self.image_shape),
            "big_img": self.big_img_history[::self.FRAME_SKIP].reshape(1, 12, *self.image_shape),
            "features_buffer": self.feature_history[::self.FRAME_SKIP][None, ...],
            "desire_pulse": self.desire_history.reshape(25, self.FRAME_SKIP, 8).max(axis=1)[None, ...],
            "traffic_convention": np.asarray(inputs["traffic_convention"], dtype=np.float16).reshape(1, 2),
            "action_t": np.asarray(inputs["action_t"], dtype=np.float16).reshape(1, 2),
        }
        model_output = self.session.run(None, feeds)[0][0].astype(np.float32)
        if not np.all(np.isfinite(model_output)):
            raise RuntimeError("Le modèle ONNX a produit une sortie non finie")
        sliced = {
            key: model_output[np.newaxis, output_slice]
            for key, output_slice in self.output_slices.items()
        }
        self.prev_feature[:] = model_output[self.output_slices["hidden_state"]]
        return self.parser.parse_outputs(sliced)

    def warmup(self) -> None:
        from types import SimpleNamespace

        yuv_size = self.native.frame_buf_params["img"][3]
        dummy = SimpleNamespace(data=np.zeros(yuv_size, dtype=np.uint8))
        zeros = {
            "desire_pulse": np.zeros(8, dtype=np.float32),
            "traffic_convention": np.zeros(2, dtype=np.float32),
            "action_t": np.zeros(2, dtype=np.float32),
        }
        identity = np.eye(3, dtype=np.float32)
        self.run(
            {"img": dummy, "big_img": dummy},
            {"img": identity, "big_img": identity},
            zeros,
        )
        self._reset_history()


class LiveModel:
    def __init__(
        self,
        camera: LatestCamera,
        can_client: LiveCanClient | None,
        preprocessor: Any,
        model: Any,
        calibrator: Any,
        nv12: Any,
        get_warp_matrix: Any,
        model_constants: Any,
        camera_frame_type: Any,
        output_record: Any,
        model_hz: float,
        blinker_desire_enabled: bool,
    ) -> None:
        self.camera = camera
        self.can_client = can_client
        self.preprocessor = preprocessor
        self.model = model
        self.calibrator = calibrator
        self.nv12 = nv12
        self.get_warp_matrix = get_warp_matrix
        self.model_constants = model_constants
        self.camera_frame_type = camera_frame_type
        self.output_record = output_record
        self.period_s = 1.0 / model_hz
        self.desire_helper = PassiveLaneChangeDesire(blinker_desire_enabled)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._prediction: LivePrediction | None = None
        self._error: Exception | None = None
        self._sequence = 0
        self._run_times: deque[float] = deque(maxlen=30)
        self._thread = threading.Thread(target=self._run, name="openpilot-model", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        last_frame_index = -1
        last_run_started = 0.0
        first_timestamp_us: int | None = None
        traffic_convention = np.array([1.0, 0.0], dtype=np.float32)
        try:
            while not self._stop.is_set():
                frame = self.camera.latest()
                now = time.monotonic()
                if (
                    frame is None
                    or frame.index == last_frame_index
                    or now - last_run_started < self.period_s
                ):
                    self._stop.wait(0.002)
                    continue
                last_run_started = now
                last_frame_index = frame.index
                if first_timestamp_us is None:
                    first_timestamp_us = frame.wall_timestamp_us
                if self.can_client is not None:
                    state, can_status = self.can_client.snapshot()
                    if not can_status_is_fresh(can_status):
                        state = {}
                else:
                    state = {}
                speed_kph = state.get("speed_kph")
                speed_ms = (
                    max(0.0, float(speed_kph) / 3.6)
                    if isinstance(speed_kph, (int, float)) and math.isfinite(float(speed_kph))
                    else 0.0
                )
                self.calibrator.handle_v_ego(speed_ms)
                rpy = np.asarray(self.calibrator.get_smooth_rpy(), dtype=np.float32)
                transforms = {
                    "img": self.get_warp_matrix(rpy, self.preprocessor.model_intrinsics, False).astype(np.float32),
                    "big_img": self.get_warp_matrix(rpy, self.preprocessor.model_intrinsics, True).astype(np.float32),
                }
                desire = self.desire_helper.update(state)
                desire_vector = np.zeros(self.model_constants.DESIRE_LEN, dtype=np.float32)
                if 0 <= desire < len(desire_vector):
                    desire_vector[desire] = 1.0
                inputs = {
                    "desire_pulse": desire_vector,
                    "traffic_convention": traffic_convention,
                    "action_t": np.array([0.075, 0.575], dtype=np.float32),
                }
                buffer = self.nv12.update(frame.processed)
                inference_started = time.perf_counter()
                output = self.model.run({"img": buffer, "big_img": buffer}, transforms, inputs)
                execution_ms = (time.perf_counter() - inference_started) * 1000.0
                if output is None:
                    continue
                pose = output["pose"][0]
                if speed_kph is None:
                    speed_ms = max(0.0, float(pose[0]))
                    self.calibrator.handle_v_ego(speed_ms)
                self.calibrator.handle_cam_odom(
                    pose[:3].tolist(),
                    pose[3:].tolist(),
                    output["wide_from_device_euler"][0].tolist(),
                    output["pose_stds"][0, :3].tolist(),
                    output["road_transform"][0, :3].tolist(),
                    output["road_transform_stds"][0, :3].tolist(),
                )
                record = self.output_record(
                    self.camera_frame_type(frame.index, frame.wall_timestamp_us),
                    output,
                    execution_ms,
                    rpy,
                    self.calibrator,
                    speed_ms,
                    first_timestamp_us,
                    self.model_constants,
                )
                record["passive_lane_change"] = self.desire_helper.snapshot(desire)
                completed = time.monotonic()
                self._run_times.append(completed)
                rate_hz = 0.0
                if len(self._run_times) >= 2:
                    rate_hz = (len(self._run_times) - 1) / (self._run_times[-1] - self._run_times[0])
                prediction = LivePrediction(
                    sequence=self._sequence,
                    source_frame_index=frame.index,
                    record=record,
                    execution_ms=execution_ms,
                    end_to_end_ms=(completed - frame.monotonic_s) * 1000.0,
                    rate_hz=rate_hz,
                )
                self._sequence += 1
                with self._lock:
                    self._prediction = prediction
        except Exception as exc:  # surfaced in the UI thread
            with self._lock:
                self._error = exc

    def latest(self) -> LivePrediction | None:
        with self._lock:
            return self._prediction

    @property
    def error(self) -> Exception | None:
        with self._lock:
            return self._error

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)


class LiveRecorder:
    def __init__(self, root: Path, requested_fps: float, record_overlay: bool, meta: dict[str, Any]) -> None:
        if cv is None:
            raise RuntimeError("OpenCV est requis")
        self.session_id = datetime.now(UTC).strftime("live-%Y%m%dT%H%M%SZ")
        self.directory = root / self.session_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.requested_fps = requested_fps
        self.record_overlay = record_overlay
        self.meta = dict(meta)
        self.meta.update({"session_id": self.session_id, "started_at": datetime.now(UTC).isoformat()})
        self.raw_writer: Any = None
        self.overlay_writer: Any = None
        self.frames = (self.directory / "frames.jsonl").open("w", encoding="utf-8")
        self.overlay_frames = (self.directory / "overlay_frames.jsonl").open("w", encoding="utf-8")
        self.perception = (self.directory / "perception.jsonl").open("w", encoding="utf-8")
        self._lock = threading.Lock()
        self.frame_count = 0
        self.last_source_frame = -1
        self.first_source_timestamp_us: int | None = None
        self.last_source_timestamp_us: int | None = None
        self.overlay_frame_count = 0
        self.last_overlay_source_frame = -1
        self.first_overlay_timestamp_us: int | None = None
        self.last_overlay_timestamp_us: int | None = None
        self.last_prediction = -1
        (self.directory / "meta.json").write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @property
    def raw_can_path(self) -> Path:
        return self.directory / "can.jsonl"

    def record_source_frame(self, frame: CapturedFrame) -> None:
        """Called by the capture thread so UI/model load cannot drop recordings."""
        with self._lock:
            if frame.index == self.last_source_frame:
                return
            self.last_source_frame = frame.index
            if self.raw_writer is None:
                height, width = frame.stored.shape[:2]
                self.raw_writer = cv.VideoWriter(
                    str(self.directory / "road.mp4"),
                    cv.VideoWriter_fourcc(*"mp4v"),
                    self.requested_fps,
                    (width, height),
                )
                if not self.raw_writer.isOpened():
                    raise RuntimeError("Impossible d'ouvrir l'enregistrement road.mp4")
            self.raw_writer.write(frame.stored)
            if self.first_source_timestamp_us is None:
                self.first_source_timestamp_us = frame.wall_timestamp_us
            self.last_source_timestamp_us = frame.wall_timestamp_us
            self.frames.write(json.dumps({
                "frame_index": self.frame_count,
                "source_frame_index": frame.index,
                "timestamp_us": frame.wall_timestamp_us,
            }) + "\n")
            self.frame_count += 1

    def record_overlay_frame(self, frame: CapturedFrame, rendered: np.ndarray) -> None:
        if not self.record_overlay or frame.index == self.last_overlay_source_frame:
            return
        self.last_overlay_source_frame = frame.index
        if self.overlay_writer is None:
            rendered_height, rendered_width = rendered.shape[:2]
            self.overlay_writer = cv.VideoWriter(
                str(self.directory / "overlay.mp4"),
                cv.VideoWriter_fourcc(*"mp4v"),
                self.requested_fps,
                (rendered_width, rendered_height),
            )
            if not self.overlay_writer.isOpened():
                raise RuntimeError("Impossible d'ouvrir l'enregistrement overlay.mp4")
        self.overlay_writer.write(rendered)
        if self.first_overlay_timestamp_us is None:
            self.first_overlay_timestamp_us = frame.wall_timestamp_us
        self.last_overlay_timestamp_us = frame.wall_timestamp_us
        self.overlay_frames.write(json.dumps({
            "frame_index": self.overlay_frame_count,
            "source_frame_index": frame.index,
            "timestamp_us": frame.wall_timestamp_us,
        }) + "\n")
        self.overlay_frame_count += 1

    def record_prediction(self, prediction: LivePrediction | None) -> None:
        if prediction is None or prediction.sequence == self.last_prediction:
            return
        self.last_prediction = prediction.sequence
        payload = dict(prediction.record)
        payload["live_sequence"] = prediction.sequence
        payload["source_frame_index"] = prediction.source_frame_index
        payload["end_to_end_ms"] = round(prediction.end_to_end_ms, 3)
        payload["model_rate_hz"] = round(prediction.rate_hz, 3)
        self.perception.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def close(self, can_anchor: dict[str, Any] | None, summary: dict[str, Any]) -> None:
        if self.raw_writer is not None:
            self.raw_writer.release()
        if self.overlay_writer is not None:
            self.overlay_writer.release()
        self.frames.close()
        self.overlay_frames.close()
        self.perception.close()
        timing = {
            "road": retime_video_in_place(
                self.directory / "road.mp4",
                self.frame_count,
                self.first_source_timestamp_us,
                self.last_source_timestamp_us,
                self.requested_fps,
            ),
            "overlay": retime_video_in_place(
                self.directory / "overlay.mp4",
                self.overlay_frame_count,
                self.first_overlay_timestamp_us,
                self.last_overlay_timestamp_us,
                self.requested_fps,
            ),
        }
        self.meta["finished_at"] = datetime.now(UTC).isoformat()
        self.meta["frame_count"] = self.frame_count
        self.meta["overlay_frame_count"] = self.overlay_frame_count
        self.meta["sync_anchor"] = can_anchor
        self.meta["summary"] = summary
        self.meta["video_timing"] = timing
        (self.directory / "meta.json").write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def draw_text(
    frame: np.ndarray,
    text: str,
    origin: tuple[int, int],
    color: tuple[int, int, int] = (245, 245, 245),
    scale: float = 0.65,
) -> None:
    cv.putText(frame, text, origin, cv.FONT_HERSHEY_DUPLEX, scale, (0, 0, 0), 5, cv.LINE_AA)
    cv.putText(frame, text, origin, cv.FONT_HERSHEY_DUPLEX, scale, color, 2, cv.LINE_AA)


def draw_turn_signals(
    frame: np.ndarray,
    status: Any,
    clock_s: float,
    decision: dict[str, Any] | None = None,
) -> None:
    """Draw dashboard-like blinking arrows for 0x452 TurnSignalStatus."""
    _height, width = frame.shape[:2]
    left_commanded, right_commanded = turn_signal_sides(status)
    blink_on = int(clock_s * 2.0) % 2 == 0
    gap_left = min(720, width // 2)
    gap_right = max(gap_left + 170, width - 500)
    center = (gap_left + gap_right) // 2

    def arrow(center_x: int, points_left: bool, active: bool, commanded: bool) -> None:
        direction = -1 if points_left else 1
        points = np.asarray(
            [
                (center_x + direction * 45, 66),
                (center_x + direction * 10, 40),
                (center_x + direction * 10, 54),
                (center_x - direction * 38, 54),
                (center_x - direction * 38, 78),
                (center_x + direction * 10, 78),
                (center_x + direction * 10, 92),
            ],
            dtype=np.int32,
        )
        color = (40, 190, 255) if active else (70, 82, 88) if commanded else (45, 52, 56)
        cv.fillPoly(frame, [points], color, cv.LINE_AA)
        cv.polylines(frame, [points], True, (8, 12, 14), 2, cv.LINE_AA)

    arrow(center - 58, True, left_commanded and blink_on, left_commanded)
    arrow(center + 58, False, right_commanded and blink_on, right_commanded)
    if left_commanded or right_commanded:
        label = turn_signal_text(status)
        text_size = cv.getTextSize(label, cv.FONT_HERSHEY_DUPLEX, 0.50, 2)[0]
        draw_text(frame, label, (center - text_size[0] // 2, 116), (40, 190, 255), 0.50)
    if decision and decision.get("enabled"):
        phase = decision.get("phase")
        direction = decision.get("direction")
        if phase == "waiting_torque":
            label = "ATTENTE EFFORT"
            color = (245, 245, 245)
        elif phase == "active":
            label = "MODELE " + ("GAUCHE" if direction == "left" else "DROITE")
            color = (255, 220, 80)
        else:
            label = ""
            color = (245, 245, 245)
        if label:
            text_size = cv.getTextSize(label, cv.FONT_HERSHEY_DUPLEX, 0.43, 2)[0]
            draw_text(frame, label, (center - text_size[0] // 2, 140), color, 0.43)


def draw_live_hud(
    frame: np.ndarray,
    state: dict[str, Any],
    can_status: dict[str, Any],
    prediction: LivePrediction | None,
    camera_rate_hz: float,
) -> None:
    height, width = frame.shape[:2]
    speed = state.get("speed_kph")
    brake = state.get("brake_active")
    accelerator = state.get("accelerator_pct")
    steering = state.get("steering_angle_deg")
    cruise = state.get("cruise_setpoint_kph")
    can_ok = can_status_is_fresh(can_status)
    for x0, y0, x1, y1 in (
        (width - 500, 18, width - 20, 220),
        (20, height - 66, width - 20, height - 18),
    ):
        roi = frame[y0:y1, x0:x1]
        overlay = np.full_like(roi, (12, 18, 22))
        cv.addWeighted(overlay, 0.72, roi, 0.28, 0, roi)
    speed_text = "--" if speed is None else f"{float(speed):.1f}"
    draw_text(frame, f"{speed_text} km/h   EAT6 {transmission_text(state)}", (width - 475, 60), (100, 235, 145), 0.84)
    draw_text(
        frame,
        f"Frein {'ACTIF' if brake else 'relache' if brake is not None else '--'}   "
        f"Accel {'--' if accelerator is None else f'{float(accelerator):.1f}%'}",
        (width - 475, 102),
        (70, 90, 255) if brake else (245, 245, 245),
    )
    draw_text(
        frame,
        f"Volant {'--' if steering is None else f'{float(steering):.1f} deg'}   "
        f"RVV {'--' if cruise is None else f'{float(cruise):.0f} km/h'}",
        (width - 475, 143),
    )
    door_values = [
        state.get(name)
        for name in ("driver_door", "passenger_door", "rear_left_door", "rear_right_door")
    ]
    doors_known = any(value is not None for value in door_values)
    door_open = any(bool(value) for value in door_values if value is not None)
    belt = state.get("driver_seatbelt_state")
    parking = state.get("parking_brake")
    draw_text(
        frame,
        f"Portes {'OUVERTES' if door_open else 'fermees' if doors_known else '--'}   "
        f"Ceinture {'OK' if belt == 2 else '--'}   Parking {'SERRE' if parking else 'libre' if parking is not None else '--'}",
        (width - 475, 184),
        (70, 90, 255) if door_open else (245, 245, 245),
    )
    model_hz = prediction.rate_hz if prediction else 0.0
    latency = prediction.end_to_end_ms if prediction else 0.0
    can_rate = float(can_status.get("frames_per_second") or 0.0)
    status_color = (100, 235, 145) if can_ok else (40, 190, 255)
    can_label = can_status_label(can_status)
    draw_text(
        frame,
        f"CAM {camera_rate_hz:4.1f} Hz   MODEL {model_hz:4.1f} Hz / {latency:4.0f} ms   "
        f"CAN {can_rate:5.0f} tr/s {can_label}   "
        "LECTURE SEULE",
        (38, height - 34),
        status_color,
        0.62,
    )
    decision = prediction.record.get("passive_lane_change") if prediction else None
    draw_turn_signals(frame, state.get("turn_signal"), time.monotonic(), decision)


def list_cameras(maximum: int = 6) -> None:
    if cv is None:
        raise RuntimeError("OpenCV est requis")
    backend = cv.CAP_AVFOUNDATION if platform.system() == "Darwin" else cv.CAP_ANY
    for index in range(maximum):
        capture = cv.VideoCapture(index, backend)
        ok, frame = capture.read() if capture.isOpened() else (False, None)
        if ok and frame is not None:
            print(f"{index}: {frame.shape[1]}x{frame.shape[0]}")
        else:
            print(f"{index}: indisponible")
        capture.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openpilot-root", type=Path, default=DEFAULT_OPENPILOT_ROOT)
    parser.add_argument("--backend-python", type=Path, default=DEFAULT_BACKEND_PYTHON)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--dbc", type=Path, default=DEFAULT_DBC)
    parser.add_argument("--camera", type=int, default=0)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--video", type=Path, help="Source vidéo de test à la place de la caméra")
    source_group.add_argument(
        "--stream",
        type=Path,
        help="Flux vidéo live local (FIFO); aucune régulation de lecture ni file d'images",
    )
    parser.add_argument("--video-start-frame", type=int, default=0)
    parser.add_argument(
        "--rotate-180",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Retourne la caméra physique ou le flux live de 180 degrés "
            "(activé par défaut; sans effet avec --video)"
        ),
    )
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--model-hz", type=float, default=20.0)
    parser.add_argument(
        "--model-backend",
        choices=("onnx-cpu", "native"),
        default="onnx-cpu",
        help="Moteur d'inférence: ONNX Runtime CPU accéléré ou tinygrad natif",
    )
    parser.add_argument("--onnx-model", type=Path, help="driving_supercombo.onnx alternatif")
    parser.add_argument("--port", help="Port ESP32; auto-détecté si absent")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--no-can", action="store_true")
    parser.add_argument("--lane-min-prob", type=float, default=0.20)
    parser.add_argument("--lead-min-prob", type=float, default=0.50)
    parser.add_argument(
        "--blinker-desire",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Injecte passivement l'intention de changement de voie dans le modèle",
    )
    parser.add_argument("--display-scale", type=float, default=0.75)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--duration", type=float, help="Arrêt automatique après N secondes")
    parser.add_argument("--record", action="store_true", help="Enregistre route/CAN/perception")
    parser.add_argument("--record-overlay", action="store_true", help="Ajoute overlay.mp4 (implique --record)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--list-cameras", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if cv is None:
        raise RuntimeError("OpenCV absent: utiliser le Python de l'environnement openpilot")
    if args.list_cameras:
        list_cameras()
        return 0
    if args.fps <= 0 or args.model_hz <= 0 or args.display_scale <= 0:
        raise ValueError("Les cadences et l'échelle d'affichage doivent être positives")
    if args.video_start_frame < 0:
        raise ValueError("--video-start-frame doit être positif ou nul")

    openpilot_root = args.openpilot_root.resolve()
    calibration_path = (args.calibration or openpilot_root / "camera_intrinsics.json").resolve()
    for required in (openpilot_root, calibration_path):
        if not required.exists():
            raise FileNotFoundError(required)
    if not args.no_can:
        for required in (args.backend_python, args.dbc):
            if not required.is_file():
                raise FileNotFoundError(required)

    sys.path.insert(0, str(openpilot_root))
    os.environ.pop("DEBUG", None)
    from openpilot.common.transformations.camera import view_frame_from_device_frame
    from openpilot.common.transformations.model import get_warp_matrix
    from openpilot.common.transformations.orientation import rot_from_euler
    from openpilot.selfdrive.locationd.calibrationd import Calibrator
    from openpilot.selfdrive.modeld.constants import ModelConstants
    from openpilot.selfdrive.modeld.modeld import ModelState as NativeModelState
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    from render_openpilot_perception_frames import draw_prediction
    from run_openpilot_perception import CameraFrame, CameraPreprocessor, Nv12Buffer, output_record

    print("OPENPILOT LIVE — OBSERVATION PASSIVE", flush=True)
    print("Aucune émission série, aucune trame CAN TX, aucune commande véhicule.", flush=True)
    preprocessor = CameraPreprocessor(calibration_path)
    print(f"[model] chargement driving_supercombo ({args.model_backend})", flush=True)
    native_model = NativeModelState(preprocessor.model_width, preprocessor.model_height, False)
    if args.model_backend == "onnx-cpu":
        onnx_path = (
            args.onnx_model.resolve()
            if args.onnx_model is not None
            else openpilot_root / "openpilot/selfdrive/modeld/models/driving_supercombo.onnx"
        )
        model = OnnxModelState(native_model, onnx_path)
    else:
        model = native_model
    model.warmup()
    print("[model] prêt", flush=True)

    recorder: LiveRecorder | None = None
    if args.record or args.record_overlay:
        recorder = LiveRecorder(
            args.output_dir.resolve(),
            args.fps,
            args.record_overlay,
            {
                "readonly": True,
                "model": "openpilot driving_supercombo",
                "model_backend": args.model_backend,
                "camera": (
                    str(args.stream.resolve())
                    if args.stream is not None
                    else args.camera if args.video is None else str(args.video.resolve())
                ),
                "source_type": (
                    "stream"
                    if args.stream is not None
                    else "video" if args.video is not None else "camera"
                ),
                "rotate_180": args.rotate_180 if args.video is None else False,
                "requested_fps": args.fps,
                "calibration": str(calibration_path),
                "dbc": None if args.no_can else str(args.dbc.resolve()),
                "blinker_desire": args.blinker_desire,
            },
        )
        print(f"[record] {recorder.directory}", flush=True)

    can_client: LiveCanClient | None = None
    camera: LatestCamera | None = None
    live_model: LiveModel | None = None
    started = time.monotonic()
    displayed_source_frame = -1
    prediction_written = -1
    frames_displayed = 0
    last_console_status = 0.0
    last_rendered: np.ndarray | None = None
    try:
        if not args.no_can:
            can_client = LiveCanClient(
                executable_path(args.backend_python),
                args.port,
                args.baud,
                args.dbc.resolve(),
                recorder.raw_can_path if recorder else None,
            )
            time.sleep(0.35)
            can_client.check_started()
        source: int | Path = (
            args.stream.resolve()
            if args.stream is not None
            else args.video.resolve() if args.video is not None else args.camera
        )
        if args.video is None:
            print(
                "[cam] rotation 180° " + ("activée" if args.rotate_180 else "désactivée"),
                flush=True,
            )
        camera = LatestCamera(
            source,
            args.width,
            args.height,
            args.fps,
            preprocessor,
            rotate_live_camera=args.rotate_180,
            video_start_frame=args.video_start_frame,
            frame_sink=recorder.record_source_frame if recorder is not None else None,
            is_live_stream=args.stream is not None,
        )
        live_model = LiveModel(
            camera,
            can_client,
            preprocessor,
            model,
            Calibrator(param_put=False),
            Nv12Buffer(preprocessor.model_width, preprocessor.model_height, get_nv12_info),
            get_warp_matrix,
            ModelConstants,
            CameraFrame,
            output_record,
            args.model_hz,
            args.blinker_desire,
        )
        live_model.start()
        print("[live] q/Echap: quitter | s: capture d'écran", flush=True)

        while True:
            now = time.monotonic()
            if args.duration is not None and now - started >= args.duration:
                break
            if camera.error is not None:
                raise RuntimeError(f"Caméra: {camera.error}")
            if live_model.error is not None:
                raise RuntimeError(f"Modèle: {live_model.error}")
            frame = camera.latest()
            if frame is None or frame.index == displayed_source_frame:
                if camera.ended and frame is not None and now - frame.monotonic_s > 0.5:
                    break
                if not args.headless:
                    key = cv.waitKey(1) & 0xFF
                    if key in (27, ord("q")):
                        break
                else:
                    time.sleep(0.003)
                continue

            displayed_source_frame = frame.index
            prediction = live_model.latest()
            state, can_status = can_client.snapshot() if can_client else ({}, {"type": "disabled"})
            if can_client is not None and not can_status_is_fresh(can_status):
                state = {}
            if args.display_scale == 1.0:
                rendered = frame.processed.copy()
                render_intrinsics = preprocessor.model_intrinsics
            else:
                rendered = cv.resize(
                    frame.processed,
                    None,
                    fx=args.display_scale,
                    fy=args.display_scale,
                    interpolation=cv.INTER_AREA,
                )
                render_intrinsics = preprocessor.model_intrinsics.copy()
                render_intrinsics[:2] *= args.display_scale
            if prediction is not None:
                draw_prediction(
                    rendered,
                    prediction.record,
                    render_intrinsics,
                    view_frame_from_device_frame,
                    rot_from_euler,
                    args.lane_min_prob,
                    args.lead_min_prob,
                    "openpilot driving_supercombo | LIVE PASSIF",
                )
            draw_live_hud(rendered, state, can_status, prediction, camera.rate_hz)
            last_rendered = rendered
            frames_displayed += 1
            if recorder is not None:
                recorder.record_overlay_frame(frame, rendered)
                if prediction is not None and prediction.sequence != prediction_written:
                    recorder.record_prediction(prediction)
                    prediction_written = prediction.sequence

            if not args.headless:
                cv.imshow("OpenPilot Live — Peugeot 308 T9 — READ ONLY", rendered)
                key = cv.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                if key == ord("s"):
                    screenshot = args.output_dir / datetime.now(UTC).strftime("screenshot-%Y%m%dT%H%M%SZ.jpg")
                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                    cv.imwrite(str(screenshot), rendered)
                    print(f"[capture] {screenshot}", flush=True)

            if now - last_console_status >= 2.0:
                last_console_status = now
                rate = prediction.rate_hz if prediction else 0.0
                latency = prediction.end_to_end_ms if prediction else 0.0
                can_rate = float(can_status.get("frames_per_second") or 0.0)
                print(
                    f"[live] cam={camera.rate_hz:.1f}Hz model={rate:.1f}Hz "
                    f"latence={latency:.0f}ms CAN={can_rate:.0f}tr/s "
                    f"{can_status_label(can_status)}",
                    flush=True,
                )
    finally:
        if live_model is not None:
            live_model.close()
        if camera is not None:
            camera.close()
        final_can_status: dict[str, Any] | None = None
        if can_client is not None:
            _final_can_state, final_can_status = can_client.snapshot()
            can_client.close()
        if not args.headless:
            cv.destroyAllWindows()
        duration_s = max(time.monotonic() - started, 1e-6)
        prediction = live_model.latest() if live_model is not None else None
        summary = {
            "duration_s": round(duration_s, 3),
            "displayed_frames": frames_displayed,
            "display_rate_hz": round(frames_displayed / duration_s, 3),
            "model_rate_hz": round(prediction.rate_hz, 3) if prediction else 0.0,
            "last_model_latency_ms": round(prediction.end_to_end_ms, 3) if prediction else None,
        }
        if final_can_status is not None:
            summary["can"] = {
                key: final_can_status.get(key)
                for key in (
                    "frames_total",
                    "decoded_total",
                    "decode_errors",
                    "frames_per_second",
                    "age_s",
                    "transport_lag_s",
                    "max_transport_lag_s",
                    "serial_backlog_bytes",
                    "sequence_gaps",
                    "sequence_resets",
                    "malformed_frame_lines",
                    "discarded_serial_lines",
                    "gateway_dropped",
                    "interboard_overflow",
                )
            }
        if recorder is not None:
            recorder.close(can_client.anchor if can_client else None, summary)
            print(f"[record] terminé: {recorder.directory}", flush=True)
        if last_rendered is not None:
            print(
                f"[live] terminé: {frames_displayed} images affichées en {duration_s:.1f}s",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    try:
        if "--can-worker" in sys.argv:
            raise SystemExit(can_worker_main())
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
