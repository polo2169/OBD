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
        "obd_request",
        "obd_response",
        "obd_error",
        "isotp_error",
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._obd_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._transport_ready = threading.Event()
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
        self._vin: str | None = None
        self._vehicle_profile: str | None = None
        self._vehicle_label: str | None = None
        self._mode: str | None = None
        self._started_at_us: int | None = None
        self._strict_passive: bool | None = None
        self._dual_can = False
        self._live_can_ready: bool | None = None
        self._diagnostic_can_ready: bool | None = None
        self._hybrid_obd_enabled = False
        self._hybrid_obd_ready = False
        self._obd_sample_count = 0
        self._obd_supported_pids: list[int] = []
        self._obd_error: str | None = None
        self._last_error: str | None = None
        self._write_lock = threading.Lock()
        self._write_handle: TextIO | None = None
        self._unflushed_events = 0
        self._last_flush_monotonic = 0.0
        self._latest_frames_lock = threading.Lock()
        self._latest_frames: dict[tuple[int, bool], dict] = {}
        self._latest_obd_lock = threading.Lock()
        self._latest_obd_values: dict[str, dict] = {}
        self._obd_diagnostic_ids: set[int] = set()

    def start(
        self,
        name: str = "Nouvelle découverte",
        note: str | None = None,
        vin: str | None = None,
        vehicle_profile: str | None = None,
        vehicle_label: str | None = None,
        enable_live_data_reads: bool = False,
    ) -> CaptureStatus:
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
            if vin is None:
                try:
                    from app.diagnostic.history import active_vehicle
                    selected = active_vehicle() or {}
                except Exception:
                    selected = {}
                selected_profile = selected.get("vehicle_profile")
                if vehicle_profile is None or vehicle_profile == selected_profile:
                    vin = selected.get("vin")
                    vehicle_profile = vehicle_profile or selected_profile
                    vehicle_label = vehicle_label or " ".join(filter(None, [selected.get("manufacturer"), selected.get("model")])) or None
            self._vin = vin
            self._vehicle_profile = vehicle_profile
            self._vehicle_label = vehicle_label
            self._mode = "live_data" if enable_live_data_reads else "learn_passive"
            self._started_at_us = time.time_ns() // 1000
            self._strict_passive = None
            self._dual_can = False
            self._live_can_ready = None
            self._diagnostic_can_ready = None
            # Learn captures remain strictly passive. Normalized OBD polling is
            # enabled only when the caller is the cross-cutting Live Data view.
            self._hybrid_obd_enabled = (
                enable_live_data_reads and self._live_obd_configured(vehicle_profile)
            )
            self._hybrid_obd_ready = False
            self._obd_sample_count = 0
            self._obd_supported_pids = []
            self._obd_error = None
            self._last_error = None
            with self._latest_frames_lock:
                self._latest_frames = {}
            with self._latest_obd_lock:
                self._latest_obd_values = {}
            self._obd_diagnostic_ids = self._profile_obd_ids(vehicle_profile)
            self._stop.clear()
            self._transport_ready.clear()
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
                "vin": self._vin,
                "vehicle_profile": self._vehicle_profile,
                "vehicle_label": self._vehicle_label,
                "mode": self._mode,
            })

            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            if self._hybrid_obd_enabled:
                self._obd_thread = threading.Thread(
                    target=self._obd_loop,
                    name="opendiag-live-obd",
                    daemon=True,
                )
                self._obd_thread.start()
            else:
                self._obd_thread = None
            return self.status()

    def stop(self) -> CaptureStatus:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, settings.esp32_handshake_timeout + 1.0))
        if self._obd_thread:
            self._obd_thread.join(timeout=max(3.0, settings.diagnostic_timeout + 2.0))
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
            hybrid_obd_enabled=self._hybrid_obd_enabled,
            hybrid_obd_ready=self._hybrid_obd_ready,
            obd_sample_count=self._obd_sample_count,
            obd_supported_pids=list(self._obd_supported_pids),
            obd_error=self._obd_error,
            error=self._last_error,
            vin=self._vin,
            vehicle_profile=self._vehicle_profile,
            vehicle_label=self._vehicle_label,
            mode=self._mode,
        )

    def latest_frames(self) -> list[dict]:
        """Return one immutable snapshot containing the newest frame per CAN ID."""
        with self._latest_frames_lock:
            return [dict(frame) for frame in self._latest_frames.values()]

    def latest_obd_values(self) -> list[dict]:
        """Return the newest standardized OBD values from the hybrid live loop."""
        with self._latest_obd_lock:
            return [dict(value) for value in self._latest_obd_values.values()]

    def reset_latest_frames(self) -> None:
        """Start a fresh passive inventory without interrupting the recording."""
        with self._latest_frames_lock:
            self._latest_frames = {}

    def _capture_loop(self) -> None:
        transport = build_transport(
            debug_sink=self._transport_debug,
            receive_buses=("default", "live", "diagnostic"),
            require_diagnostic_can=False,
            vehicle_profile=self._vehicle_profile,
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
            self._transport_ready.set()
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
                    if frame.arbitration_id not in self._obd_diagnostic_ids:
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
            self._transport_ready.set()
            transport.close()
            self._active = False

    def _obd_loop(self) -> None:
        """Poll a small profile allowlist of Mode 01 PIDs beside passive CAN."""
        from app.database import KnowledgeBase
        from app.diagnostic.isotp import UdsSession
        from app.diagnostic.obd import live_pid_definitions, read_pid, supported_pids

        if not self._transport_ready.wait(timeout=settings.esp32_handshake_timeout + 1.0):
            self._obd_error = "La passerelle CAN n'a pas confirmé son démarrage."
            return
        if self._stop.is_set() or not self._active:
            return
        if self._strict_passive:
            self._obd_error = "Firmware en écoute passive stricte : polling OBD désactivé."
            return

        profile_key = self._vehicle_profile or settings.vehicle_profile
        diagnostic = KnowledgeBase().vehicle(profile_key).get("diagnostic", {})
        live_config = diagnostic.get("live_obd", {})
        definitions = live_pid_definitions(profile_key)
        if not definitions:
            self._obd_error = "Aucun PID direct n'est configuré pour ce profil."
            return
        request_id = int(str(diagnostic.get("obd_request_id", 0x7E0)), 0)
        response_id = int(str(diagnostic.get("obd_response_id", 0x7E8)), 0)
        flow_control_id = (
            int(str(diagnostic["obd_flow_control_id"]), 0)
            if diagnostic.get("obd_flow_control_id") is not None
            else None
        )
        flow_control_blocksize = int(diagnostic.get("obd_flow_control_blocksize", 8))
        interval_seconds = max(0.25, min(10.0, float(live_config.get("interval_ms", 1000)) / 1000))
        supported: set[int] | None = None
        transport = build_transport(
            debug_sink=self._transport_debug,
            receive_buses=("default", "live"),
            require_diagnostic_can=False,
            vehicle_profile=profile_key,
        )
        try:
            transport.open()
            while not self._stop.is_set() and self._active:
                cycle_started = time.monotonic()
                values: dict[str, dict] = {}
                pid_errors: list[str] = []
                try:
                    with UdsSession(
                        transport,
                        request_id,
                        response_id,
                        timeout=settings.diagnostic_timeout,
                        read_only=True,
                        tx_bus="live",
                        flow_control_id=flow_control_id,
                        flow_control_blocksize=flow_control_blocksize,
                    ) as session:
                        if supported is None:
                            supported = set(supported_pids(session))
                            self._obd_supported_pids = sorted(supported)
                            self._write({
                                "type": "obd_supported_pids",
                                "timestamp_us": time.time_ns() // 1000,
                                "request_id": request_id,
                                "response_id": response_id,
                                "supported_pids": self._obd_supported_pids,
                            })
                        for definition in definitions:
                            if self._stop.is_set():
                                break
                            if definition.pid not in supported:
                                continue
                            try:
                                value = read_pid(session, definition)
                                timestamp_us = time.time_ns() // 1000
                                values[value.key] = {
                                    **value.model_dump(mode="json"),
                                    "updated_at_us": timestamp_us,
                                    "request_id": request_id,
                                    "response_id": response_id,
                                }
                            except Exception as exc:
                                pid_errors.append(f"PID 0x{definition.pid:02X}: {exc}")
                    if values:
                        with self._latest_obd_lock:
                            self._latest_obd_values = values
                        self._obd_sample_count += 1
                        self._hybrid_obd_ready = True
                        self._obd_error = "; ".join(pid_errors[:3]) or None
                        self._write({
                            "type": "obd_sensor_snapshot",
                            "timestamp_us": max(value["updated_at_us"] for value in values.values()),
                            "vehicle_profile": profile_key,
                            "values": list(values.values()),
                            "errors": pid_errors,
                        })
                    else:
                        self._hybrid_obd_ready = False
                        self._obd_error = "; ".join(pid_errors[:3]) or "Aucun PID OBD direct pris en charge."
                        with self._latest_obd_lock:
                            self._latest_obd_values = {}
                except Exception as exc:
                    self._hybrid_obd_ready = False
                    self._obd_error = str(exc)
                    with self._latest_obd_lock:
                        self._latest_obd_values = {}
                    self._write({
                        "type": "obd_live_error",
                        "timestamp_us": time.time_ns() // 1000,
                        "error": str(exc),
                    })
                elapsed = time.monotonic() - cycle_started
                self._stop.wait(max(0.05, interval_seconds - elapsed))
        except Exception as exc:
            self._hybrid_obd_ready = False
            self._obd_error = str(exc)
        finally:
            transport.close()

    @staticmethod
    def _live_obd_configured(vehicle_profile: str | None) -> bool:
        if not settings.live_obd_enabled or not settings.can_tx_enabled:
            return False
        try:
            from app.database import KnowledgeBase
            live = KnowledgeBase().vehicle(vehicle_profile).get("diagnostic", {}).get("live_obd", {})
            return isinstance(live, dict) and live.get("enabled") is True
        except Exception:
            return False

    @staticmethod
    def _profile_obd_ids(vehicle_profile: str | None) -> set[int]:
        try:
            from app.database import KnowledgeBase
            diagnostic = KnowledgeBase().vehicle(vehicle_profile).get("diagnostic", {})
            return {
                int(str(value), 0)
                for key in ("obd_request_id", "obd_response_id", "obd_flow_control_id")
                if (value := diagnostic.get(key)) is not None
            }
        except Exception:
            return set()

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
