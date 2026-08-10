from __future__ import annotations

from collections import deque
import json
import socket
import time

from app.models import CanFrame
from app.safety import TxSafetyProfile, authorize_transport_can_frame
from app.transports.base import Transport, validate_gateway_tx_policy


class Esp32WifiTransport(Transport):
    """JSON Lines gateway transported over a private ESP32 TCP access point."""

    def __init__(
        self,
        host: str,
        port: int,
        tx_enabled: bool = False,
        handshake_timeout: float = 3.0,
        reconnect_interval: float = 0.5,
        safety_profile: TxSafetyProfile = "diagnostic_read_only",
        require_diagnostic_can: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.tx_enabled = tx_enabled
        self.handshake_timeout = handshake_timeout
        self.reconnect_interval = reconnect_interval
        self.safety_profile = safety_profile
        self.require_diagnostic_can = require_diagnostic_can
        self.socket: socket.socket | None = None
        self.hello: dict | None = None
        self.last_stats: dict | None = None
        self.sequence_gap_count = 0
        self._last_sequence: int | None = None
        self._buffer = bytearray()
        self._pending_frames: deque[CanFrame] = deque()
        self._next_reconnect_at = 0.0
        self._closing = False

    @property
    def name(self) -> str:
        return f"esp32_wifi:{self.host}:{self.port}"

    def open(self) -> None:
        self._closing = False
        self._connect(self.handshake_timeout)
        self._write_command({"type": "get_status"})

    def close(self) -> None:
        self._closing = True
        self._disconnect("transport_close")
        self.hello = None
        self._buffer.clear()
        self._pending_frames.clear()

    def receive(self, timeout: float = 0.1) -> CanFrame | None:
        if self._pending_frames:
            return self._pending_frames.popleft()

        deadline = time.monotonic() + max(timeout, 0.0)
        while time.monotonic() < deadline:
            if self.socket is None:
                if self._closing or time.monotonic() < self._next_reconnect_at:
                    return None
                remaining = max(0.01, deadline - time.monotonic())
                try:
                    self._connect(min(self.handshake_timeout, remaining))
                    self.debug("gateway_reconnected", transport=self.name)
                except (ConnectionError, OSError, TimeoutError) as exc:
                    self._next_reconnect_at = time.monotonic() + self.reconnect_interval
                    self.debug("gateway_reconnect_failed", transport=self.name, error=str(exc))
                    return None

            try:
                message = self._read_json(max(0.001, deadline - time.monotonic()))
            except (ConnectionError, OSError) as exc:
                self._disconnect("gateway_disconnected", error=str(exc))
                continue
            if message is None:
                continue
            if message.get("type") == "can_rx":
                try:
                    return self._decode_frame(message)
                except (KeyError, TypeError, ValueError) as exc:
                    self.debug("gateway_decode_error", error=str(exc), message=message)
                    continue
            self._handle_non_frame_message(message)
        return None

    def send(self, frame: CanFrame) -> None:
        if not self.tx_enabled:
            raise PermissionError("Émission ESP32 Wi-Fi désactivée par CAN_TX_ENABLED.")
        if (
            frame.bus == "live"
            and (not self.hello or self.hello.get("live_obd_read_only") is not True)
        ):
            raise PermissionError(
                "Le firmware ESP32 Wi-Fi n'annonce pas l'allowlist OBD lecture seule sur 6/14."
            )
        decision = authorize_transport_can_frame(
            self.safety_profile,
            frame.arbitration_id,
            frame.extended,
            frame.data,
            frame.bus,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        payload = {
            "type": "can_tx",
            "id": frame.arbitration_id,
            "ext": frame.extended,
            "data": frame.data.hex().upper(),
        }
        if frame.bus != "default":
            payload["bus"] = frame.bus
        self._write_command(payload)

    def _connect(self, timeout: float) -> None:
        if timeout <= 0:
            raise TimeoutError("Délai de connexion Wi-Fi ESP32 expiré.")
        self._disconnect("gateway_connect_reset")
        deadline = time.monotonic() + timeout
        try:
            candidate = socket.create_connection(
                (self.host, self.port),
                timeout=min(timeout, 2.0),
            )
            candidate.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.socket = candidate
            self._buffer.clear()
            self.hello = None

            while time.monotonic() < deadline:
                message = self._read_json(max(0.01, deadline - time.monotonic()))
                if message is None:
                    continue
                if message.get("type") == "hello":
                    self.hello = message
                    break
                self._handle_non_frame_message(message)
        except Exception:
            self._disconnect("gateway_connect_failed")
            raise

        if self.hello is None:
            self._disconnect("gateway_handshake_timeout")
            raise TimeoutError(
                f"Aucun hello reçu de l’ESP32 Wi-Fi en {timeout:.1f} s."
            )
        self._validate_hello(self.hello)
        self._next_reconnect_at = 0.0
        self.debug("transport_open", transport=self.name, hello=self.hello)

    def _validate_hello(self, hello: dict) -> None:
        protocol = int(hello.get("protocol", 0))
        if protocol < 3:
            self._disconnect("gateway_protocol_rejected")
            raise RuntimeError(f"Protocole passerelle trop ancien : {protocol}.")
        if hello.get("can_ready") is False:
            self._disconnect("gateway_can_not_ready")
            raise RuntimeError("Le contrôleur CAN de la passerelle n’est pas initialisé.")
        try:
            validate_gateway_tx_policy(
                hello,
                tx_enabled=self.tx_enabled,
                safety_profile=self.safety_profile,
                require_diagnostic_can=self.require_diagnostic_can,
            )
        except RuntimeError:
            self._disconnect("gateway_tx_policy_rejected")
            raise

    def _read_json(self, timeout: float) -> dict | None:
        if self.socket is None:
            raise ConnectionError("Transport Wi-Fi fermé.")
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buffer[:newline]).rstrip(b"\r")
                del self._buffer[: newline + 1]
                if not raw:
                    continue
                try:
                    message = (
                        self._parse_frame_line(raw)
                        if raw.startswith(b"F,")
                        else json.loads(raw)
                    )
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    self.debug(
                        "gateway_invalid_line",
                        error=str(exc),
                        raw_hex=raw[:256].hex().upper(),
                    )
                    continue
                if not isinstance(message, dict):
                    self.debug("gateway_invalid_message", message=message)
                    continue
                message = self._expand_compact_message(message)
                self.debug("gateway_message", message=message)
                return message

            self.socket.settimeout(min(max(timeout, 0.001), 0.25))
            try:
                chunk = self.socket.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("Connexion TCP fermée par l’ESP32.")
            self._buffer.extend(chunk)
            if len(self._buffer) > 8192:
                self._buffer.clear()
                self.debug("gateway_receive_overflow")

    @staticmethod
    def _parse_frame_line(line: bytes) -> dict:
        parts = line.decode("ascii").strip().split(",", 5)
        if len(parts) != 6 or parts[0] != "F":
            raise ValueError("Trame compacte Wi-Fi invalide.")
        flags = int(parts[4], 16)
        return {
            "type": "can_rx",
            "ts_us": int(parts[1], 16),
            "seq": int(parts[2], 16),
            "id": int(parts[3], 16),
            "ext": bool(flags & 0x01),
            "rtr": bool(flags & 0x02),
            "dlc": (flags & 0x3C) >> 2,
            "bus": "diagnostic" if flags & 0x40 else "live",
            "data": parts[5],
        }

    @staticmethod
    def _expand_compact_message(message: dict) -> dict:
        if message.get("t") != "r":
            return message
        data_hex = message.get("d", "")
        inferred_dlc = len(data_hex) // 2 if isinstance(data_hex, str) else 0
        return {
            "type": "can_rx",
            "ts_us": message.get("u"),
            "seq": message.get("s"),
            "id": message.get("i"),
            "ext": bool(message.get("e", False)),
            "dlc": message.get("l", inferred_dlc),
            "rtr": bool(message.get("r", False)),
            "data": data_hex,
            "bus": message.get("b", "live"),
        }

    def _decode_frame(self, message: dict) -> CanFrame:
        data_hex = message.get("data", "")
        if not isinstance(data_hex, str) or len(data_hex) > 16 or len(data_hex) % 2:
            raise ValueError("Champ data CAN invalide.")
        data = bytes.fromhex(data_hex)
        dlc = int(message.get("dlc", len(data)))
        if not bool(message.get("rtr", False)) and dlc != len(data):
            raise ValueError(f"DLC {dlc} incohérent avec {len(data)} octets.")
        arbitration_id = int(message["id"])
        extended = bool(message.get("ext", False))
        if arbitration_id < 0 or arbitration_id > (0x1FFFFFFF if extended else 0x7FF):
            raise ValueError("Identifiant CAN hors plage.")
        self._track_sequence(message)
        announced_dual = bool(self.hello and self.hello.get("dual_can") is True)
        bus = str(message.get("bus", "live")) if announced_dual else "default"
        if bus not in {"default", "live", "diagnostic"}:
            raise ValueError("Canal CAN annoncé par la passerelle invalide.")
        return CanFrame(
            timestamp_us=int(message.get("ts_us", time.time_ns() // 1000)),
            arbitration_id=arbitration_id,
            extended=extended,
            data=data,
            direction="rx",
            bus=bus,
        )

    def _track_sequence(self, message: dict) -> None:
        if "seq" not in message:
            return
        sequence = int(message["seq"])
        if sequence < 0 or sequence > 0xFFFFFFFF:
            raise ValueError("Numéro de séquence hors plage.")
        if self._last_sequence is not None:
            expected = (self._last_sequence + 1) & 0xFFFFFFFF
            if sequence != expected:
                if sequence > expected:
                    missing = sequence - expected
                    self.sequence_gap_count += missing
                    self.debug(
                        "gateway_sequence_gap",
                        expected=expected,
                        received=sequence,
                        missing=missing,
                        missing_total=self.sequence_gap_count,
                    )
                else:
                    self.debug(
                        "gateway_sequence_reset",
                        previous=self._last_sequence,
                        received=sequence,
                    )
        self._last_sequence = sequence

    def _handle_non_frame_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "hello":
            self.hello = message
        elif message_type == "stats":
            self.last_stats = message
            self.debug("gateway_stats", stats=message)
        elif message_type in {"error", "fatal"}:
            self.debug("gateway_reported_error", message=message)

    def _write_command(self, payload: dict) -> None:
        if self.socket is None:
            raise RuntimeError("Transport Wi-Fi fermé.")
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        try:
            self.socket.sendall(encoded)
        except OSError as exc:
            self._disconnect("gateway_write_failed", error=str(exc))
            raise ConnectionError("Échec d’écriture vers l’ESP32 Wi-Fi.") from exc
        self.debug("gateway_command", command=payload, bytes_written=len(encoded))

    def _disconnect(self, event: str, **details) -> None:
        current = self.socket
        self.socket = None
        if current is not None:
            try:
                current.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            current.close()
            self.debug(event, transport=self.name, last_stats=self.last_stats, **details)
