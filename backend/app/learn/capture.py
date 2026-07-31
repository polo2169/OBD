from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import threading
import time
import uuid

from app.config import settings
from app.learn.models import CaptureStatus
from app.transports.factory import build_transport


class PassiveCaptureManager:
    _RECORDED_TRANSPORT_EVENTS = {
        "gateway_sequence_gap",
        "gateway_sequence_reset",
        "gateway_disconnected",
        "gateway_reconnected",
        "gateway_reconnect_failed",
        "gateway_receive_overflow",
        "gateway_reported_error",
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
        self._marker_count = 0
        self._name = ""
        self._started_at_us: int | None = None
        self._strict_passive: bool | None = None
        self._last_error: str | None = None

    def start(self, name: str = "Nouvelle découverte", note: str | None = None) -> CaptureStatus:
        with self._lock:
            if self._active:
                return self.status()

            settings.session_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._session_id = f"learn-{stamp}-{uuid.uuid4().hex[:8]}"
            self._path = settings.session_dir / f"{self._session_id}.jsonl"
            self._frame_count = 0
            self._marker_count = 0
            self._name = name
            self._started_at_us = time.time_ns() // 1000
            self._strict_passive = None
            self._last_error = None
            self._stop.clear()
            self._active = True
            self._source = settings.transport

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
            self._thread.join(timeout=2)
        with self._lock:
            self._active = False
            self._write({
                "type": "meta",
                "timestamp_us": time.time_ns() // 1000,
                "event": "capture_stopped",
            })
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

    def status(self) -> CaptureStatus:
        return CaptureStatus(
            session_id=self._session_id or "",
            active=self._active,
            source=self._source,
            frame_count=self._frame_count,
            marker_count=self._marker_count,
            path=str(self._path or ""),
            name=self._name,
            started_at_us=self._started_at_us,
            strict_passive=self._strict_passive,
            error=self._last_error,
        )

    def _capture_loop(self) -> None:
        transport = build_transport(debug_sink=self._transport_debug)
        try:
            transport.open()
            hello = getattr(transport, "hello", None)
            if isinstance(hello, dict):
                self._strict_passive = bool(hello.get("readonly", False))
            else:
                self._strict_passive = not settings.can_tx_enabled
            self._write({
                "type": "meta",
                "timestamp_us": time.time_ns() // 1000,
                "event": "capture_transport_ready",
                "strict_passive": self._strict_passive,
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
                })
                self._frame_count += 1
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
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


capture_manager = PassiveCaptureManager()
