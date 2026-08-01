from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import threading
import time
import uuid
from typing import TextIO

from app.config import settings
from app.learn.models import CaptureGpsPosition, CaptureStatus
from app.transports.factory import build_transport


class PassiveCaptureManager:
    _FLUSH_INTERVAL_SECONDS = 0.25
    _FLUSH_EVENT_COUNT = 256
    _RECORDED_TRANSPORT_EVENTS = {
        "gateway_sequence_gap",
        "gateway_sequence_reset",
        "gateway_disconnected",
        "gateway_reconnected",
        "gateway_reconnect_failed",
        "gateway_receive_overflow",
        "gateway_reported_error",
        "gateway_stats",
        "transport_close",
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._active = False
        self._session_id: str | None = None
        self._path: Path | None = None
        self._source = ""
        self._frame_count = 0
        self._live_frame_count = 0
        self._diagnostic_frame_count = 0
        self._marker_count = 0
        self._gps_point_count = 0
        self._gps_last_accuracy_m: float | None = None
        self._name = ""
        self._started_at_us: int | None = None
        self._strict_passive: bool | None = None
        self._dual_can = False
        self._live_can_ready: bool | None = None
        self._diagnostic_can_ready: bool | None = None
        self._last_error: str | None = None
        self._write_lock = threading.Lock()
        self._write_handle: TextIO | None = None
        self._unflushed_events = 0
        self._last_flush_monotonic = 0.0
        self._latest_frames_lock = threading.Lock()
        self._latest_frames: dict[tuple[int, bool], dict] = {}

    def start(self, name: str = "Nouvelle découverte", note: str | None = None) -> CaptureStatus:
        with self._lock:
            if self._active:
                return self.status()

            self._close_writer()
            settings.session_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._session_id = f"learn-{stamp}-{uuid.uuid4().hex[:8]}"
            self._path = settings.session_dir / f"{self._session_id}.jsonl"
            self._frame_count = 0
            self._live_frame_count = 0
            self._diagnostic_frame_count = 0
            self._marker_count = 0
            self._gps_point_count = 0
            self._gps_last_accuracy_m = None
            self._name = name
            self._started_at_us = time.time_ns() // 1000
            self._strict_passive = None
            self._dual_can = False
            self._live_can_ready = None
            self._diagnostic_can_ready = None
            self._last_error = None
            with self._latest_frames_lock:
                self._latest_frames = {}
            self._stop.clear()
            self._active = True
            self._source = settings.transport
            self._open_writer()

            self._write({
                "type": "meta",
                "timestamp_us": time.time_ns() // 1000,
                "session_id": self._session_id,
                "source": self._source,
                "readonly": True,
                "name": name,
                "note": note,
            })

            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> CaptureStatus:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, settings.esp32_handshake_timeout + 1.0))
        with self._lock:
            self._active = False
            self._write({
                "type": "meta",
                "timestamp_us": time.time_ns() // 1000,
                "event": "capture_stopped",
                "frame_count": self._frame_count,
                "live_frame_count": self._live_frame_count,
                "diagnostic_frame_count": self._diagnostic_frame_count,
                "gps_point_count": self._gps_point_count,
            })
            self._close_writer()
            return self.status()

    def marker(self, name: str, note: str | None = None) -> CaptureStatus:
        with self._lock:
            if not self._active:
                raise RuntimeError("Aucune capture active.")
            self._write({
                "type": "marker",
                "timestamp_us": time.time_ns() // 1000,
                "name": name,
                "note": note,
            })
            self._marker_count += 1
            return self.status()

    def gps_position(self, position: CaptureGpsPosition) -> CaptureStatus:
        """Append one browser/device GPS fix to the active CAN session."""
        with self._lock:
            if not self._active:
                raise RuntimeError("Aucune capture active.")
            if position.session_id != self._session_id:
                raise RuntimeError("La position GPS appartient à une autre session.")

            received_at_us = time.time_ns() // 1000
            source_timestamp_us = position.source_timestamp_us
            # A browser timestamp is normally Unix time. Fall back to server receipt
            # when a device clock is clearly unrelated, so CAN/GPS ordering stays sane.
            timestamp_us = (
                source_timestamp_us
                if source_timestamp_us is not None
                and abs(source_timestamp_us - received_at_us) <= 300_000_000
                else received_at_us
            )
            self._write({
                "type": "gps_position",
                "timestamp_us": timestamp_us,
                "source_timestamp_us": source_timestamp_us,
                "received_at_us": received_at_us,
                "source": "browser_geolocation",
                "latitude": position.latitude,
                "longitude": position.longitude,
                "accuracy_m": position.accuracy_m,
                "altitude_m": position.altitude_m,
                "altitude_accuracy_m": position.altitude_accuracy_m,
                "heading_deg": position.heading_deg,
                "speed_m_s": position.speed_m_s,
            })
            self._gps_point_count += 1
            self._gps_last_accuracy_m = position.accuracy_m
            return self.status()

    def status(self) -> CaptureStatus:
        return CaptureStatus(
            session_id=self._session_id or "",
            active=self._active,
            source=self._source,
            frame_count=self._frame_count,
            live_frame_count=self._live_frame_count,
            diagnostic_frame_count=self._diagnostic_frame_count,
            marker_count=self._marker_count,
            gps_point_count=self._gps_point_count,
            gps_last_accuracy_m=self._gps_last_accuracy_m,
            path=str(self._path or ""),
            name=self._name,
            started_at_us=self._started_at_us,
            strict_passive=self._strict_passive,
            dual_can=self._dual_can,
            live_can_ready=self._live_can_ready,
            diagnostic_can_ready=self._diagnostic_can_ready,
            error=self._last_error,
        )

    def latest_frames(self) -> list[dict]:
        """Return one immutable snapshot containing the newest frame per CAN ID."""
        with self._latest_frames_lock:
            return [dict(frame) for frame in self._latest_frames.values()]

    def reset_latest_frames(self) -> None:
        """Start a fresh passive inventory without interrupting the recording."""
        with self._latest_frames_lock:
            self._latest_frames = {}

    def _capture_loop(self) -> None:
        transport = build_transport(
            debug_sink=self._transport_debug,
            receive_buses=("default", "live", "diagnostic"),
            require_diagnostic_can=False,
        )
        try:
            transport.open()
            hello = getattr(transport, "hello", None)
            if isinstance(hello, dict):
                self._dual_can = bool(hello.get("dual_can", False))
                self._live_can_ready = bool(hello.get("live_can_ready", hello.get("can_ready", False)))
                self._diagnostic_can_ready = bool(
                    hello.get("diagnostic_can_ready", hello.get("can_ready", False))
                )
                self._strict_passive = bool(
                    hello.get("readonly", False)
                    or (self._dual_can and hello.get("live_listen_only") is True)
                )
            else:
                self._strict_passive = not settings.can_tx_enabled
            self._write({
                "type": "meta",
                "timestamp_us": time.time_ns() // 1000,
                "event": "capture_transport_ready",
                "strict_passive": self._strict_passive,
                "dual_can": self._dual_can,
                "live_can_ready": self._live_can_ready,
                "diagnostic_can_ready": self._diagnostic_can_ready,
            })
            while not self._stop.is_set():
                frame = transport.receive(timeout=0.1)
                if frame is None:
                    continue
                self._write({
                    "type": "can_frame",
                    "timestamp_us": time.time_ns() // 1000,
                    "source_timestamp_us": frame.timestamp_us,
                    "arbitration_id": frame.arbitration_id,
                    "extended": frame.extended,
                    "data_hex": frame.data.hex().upper(),
                    "direction": frame.direction,
                    "bus": frame.bus,
                })
                if frame.bus in {"default", "live"}:
                    with self._latest_frames_lock:
                        self._latest_frames[(frame.arbitration_id, frame.extended)] = {
                            "timestamp_us": time.time_ns() // 1000,
                            "arbitration_id": frame.arbitration_id,
                            "extended": frame.extended,
                            "data": bytes(frame.data),
                            "raw_hex": frame.data.hex().upper(),
                            "bus": frame.bus,
                        }
                self._frame_count += 1
                if frame.bus == "diagnostic":
                    self._diagnostic_frame_count += 1
                else:
                    self._live_frame_count += 1
        except Exception as exc:
            self._last_error = str(exc)
            self._write({
                "type": "meta",
                "timestamp_us": time.time_ns() // 1000,
                "event": "capture_error",
                "error": str(exc),
            })
        finally:
            transport.close()
            self._active = False

    def _transport_debug(self, event: dict) -> None:
        if event.get("type") not in self._RECORDED_TRANSPORT_EVENTS:
            return
        self._write({
            "type": "transport_event",
            "timestamp_us": time.time_ns() // 1000,
            **event,
        })

    def _write(self, event: dict) -> None:
        if not self._path:
            return
        with self._write_lock:
            if self._write_handle is None or self._write_handle.closed:
                self._write_handle = self._path.open(
                    "a",
                    encoding="utf-8",
                    buffering=64 * 1024,
                )
                self._last_flush_monotonic = time.monotonic()
                self._unflushed_events = 0
            self._write_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._unflushed_events += 1
            now = time.monotonic()
            if (
                self._unflushed_events >= self._FLUSH_EVENT_COUNT
                or now - self._last_flush_monotonic >= self._FLUSH_INTERVAL_SECONDS
            ):
                self._write_handle.flush()
                self._unflushed_events = 0
                self._last_flush_monotonic = now

    def _open_writer(self) -> None:
        if not self._path:
            return
        with self._write_lock:
            self._write_handle = self._path.open(
                "a",
                encoding="utf-8",
                buffering=64 * 1024,
            )
            self._unflushed_events = 0
            self._last_flush_monotonic = time.monotonic()

    def _close_writer(self) -> None:
        with self._write_lock:
            if self._write_handle is None:
                return
            try:
                self._write_handle.flush()
                os.fsync(self._write_handle.fileno())
            finally:
                self._write_handle.close()
                self._write_handle = None
                self._unflushed_events = 0


capture_manager = PassiveCaptureManager()
