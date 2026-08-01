from collections import deque
import json
import time
import serial

from app.models import CanFrame
from app.safety import TxSafetyProfile, authorize_transport_can_frame
from app.transports.base import Transport


class Esp32SerialTransport(Transport):
    def __init__(
        self,
        port: str,
        baud: int,
        tx_enabled: bool = False,
        handshake_timeout: float = 3.0,
        safety_profile: TxSafetyProfile = "diagnostic_read_only",
        require_diagnostic_can: bool = True,
    ) -> None:
        self.port = port
        self.baud = baud
        self.tx_enabled = tx_enabled
        self.handshake_timeout = handshake_timeout
        self.safety_profile = safety_profile
        self.require_diagnostic_can = require_diagnostic_can
        self.serial: serial.Serial | None = None
        self.hello: dict | None = None
        self.last_stats: dict | None = None
        self.sequence_gap_count = 0
        self._last_sequence: int | None = None
        self._pending_frames: deque[CanFrame] = deque()

    @property
    def name(self) -> str:
        return f"esp32:{self.port}"

    def open(self) -> None:
        self.sequence_gap_count = 0
        self._last_sequence = None
        self.serial = serial.Serial(self.port, self.baud, timeout=0.1)
        self.debug("transport_open", transport=self.name, baud=self.baud)
        deadline = time.monotonic() + self.handshake_timeout
        next_status_request = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_status_request:
                self._write_command({"type": "get_status"})
                next_status_request = now + 0.5
            message = self._read_json(max(0.01, deadline - time.monotonic()))
            if message is None:
                continue
            if message.get("type") == "hello":
                self.hello = message
                self._stabilize_uart_dual_hello(deadline)
                break
            self._handle_non_frame_message(message)

        if self.hello is None:
            self.close()
            raise TimeoutError(
                f"Aucun hello reçu de la passerelle ESP32 en {self.handshake_timeout:.1f} s."
            )
        protocol = int(self.hello.get("protocol", 0))
        if protocol < 2:
            self.close()
            raise RuntimeError(f"Protocole passerelle trop ancien : {protocol}.")
        if self.hello.get("can_ready") is False:
            self.close()
            raise RuntimeError("Le contrôleur CAN de la passerelle n'est pas initialisé.")
        if self.tx_enabled and bool(self.hello.get("readonly", True)):
            self.close()
            raise RuntimeError(
                "CAN_TX_ENABLED=true mais le firmware ESP32 est compilé en écoute seule. "
                "Flashez esp32-tja1050-serial-diagnostic pour un scan UDS en lecture."
            )
        if self.tx_enabled:
            if (
                self.require_diagnostic_can
                and self.hello.get("dual_can") is True
                and self.hello.get("diagnostic_can_ready") is not True
            ):
                self.close()
                raise RuntimeError(
                    "Le bus CAN diagnostic 3/8 n'est pas initialisé sur le MCP2515."
                )
            psa_lab = self.hello.get("psa_lab") is True
            if self.safety_profile == "psa_lab" and not psa_lab:
                self.close()
                raise RuntimeError(
                    "Le firmware ESP32 n'annonce pas la capacité PSA lab. "
                    "Flashez le profil esp32-tja1050-serial-psa-lab."
                )
            if (
                self.safety_profile == "diagnostic_read_only"
                and self.hello.get("diagnostic_read_only") is not True
                and not psa_lab
            ):
                self.close()
                raise RuntimeError(
                    "Le firmware ESP32 n'annonce pas le verrou diagnostic lecture seule "
                    "ni le profil PSA lab compatible. "
                    "Le profil actif générique est refusé."
                )
        self.debug("gateway_ready", hello=self.hello)
        self._write_command({"type": "get_status"})

    def _stabilize_uart_dual_hello(self, handshake_deadline: float) -> None:
        """Let the UART satellite finish its post-reset hello exchange.

        The main ESP32 can announce the cached satellite state just before a
        fresh satellite hello arrives. Sending UDS immediately in that narrow
        window makes the main gateway reject an otherwise safe request.
        """
        if not self.hello or self.hello.get("driver") != "twai+uart-twai":
            return
        stabilization_deadline = min(handshake_deadline, time.monotonic() + 0.75)
        while time.monotonic() < stabilization_deadline:
            message = self._read_json(max(0.01, stabilization_deadline - time.monotonic()))
            if message is None:
                continue
            if message.get("type") == "hello":
                self.hello = message
                continue
            self._handle_non_frame_message(message)

    def close(self) -> None:
        if self.serial:
            self.debug("transport_close", transport=self.name, last_stats=self.last_stats)
            self.serial.close()
            self.serial = None
        self.hello = None
        self._pending_frames.clear()

    def receive(self, timeout: float = 0.1) -> CanFrame | None:
        if not self.serial:
            raise RuntimeError("Transport fermé.")
        if self._pending_frames:
            return self._pending_frames.popleft()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self._read_json(max(0.001, deadline - time.monotonic()))
            if message is None:
                continue
            if message.get("type") == "can_rx":
                try:
                    return self._decode_frame(message)
                except (KeyError, TypeError, ValueError) as exc:
                    self.debug(
                        "gateway_decode_error",
                        error=str(exc),
                        message=message,
                    )
                    continue
            self._handle_non_frame_message(message)
        return None

    def send(self, frame: CanFrame) -> None:
        if not self.tx_enabled:
            raise PermissionError("Émission ESP32 désactivée par CAN_TX_ENABLED.")
        if not self.serial:
            raise RuntimeError("Transport fermé.")
        decision = authorize_transport_can_frame(
            self.safety_profile,
            frame.arbitration_id,
            frame.extended,
            frame.data,
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

    def _read_json(self, timeout: float) -> dict | None:
        if not self.serial:
            raise RuntimeError("Transport fermé.")
        # Keep the CP2102 port configuration fixed after opening it. On macOS,
        # changing this property can discard the USB driver's pending packet.
        # The surrounding receive loop still enforces its own monotonic deadline.
        line = self.serial.readline()
        if not line:
            return None
        try:
            message = (
                self._parse_frame_line(line)
                if line.startswith(b"F,")
                else json.loads(line)
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.debug(
                "gateway_invalid_line",
                error=str(exc),
                raw_hex=line[:256].hex().upper(),
            )
            return None
        if not isinstance(message, dict):
            self.debug("gateway_invalid_message", message=message)
            return None
        message = self._expand_compact_message(message)
        self.debug("gateway_message", message=message)
        return message

    @staticmethod
    def _parse_frame_line(line: bytes) -> dict:
        parts = line.decode("ascii").strip().split(",", 5)
        if len(parts) != 6 or parts[0] != "F":
            raise ValueError("Trame compacte série invalide.")
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
        announced_role = str(self.hello.get("bus_role", "")) if self.hello else ""
        if announced_dual:
            bus = str(message.get("bus", "live"))
        elif announced_role in {"live", "diagnostic"}:
            bus = announced_role
        else:
            # Backward compatibility for firmware protocol <= 6, which had no
            # standalone bus-role announcement.
            bus = "default"
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
        if not self.serial:
            raise RuntimeError("Transport fermé.")
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        written = self.serial.write(encoded)
        self.debug(
            "gateway_command",
            command=payload,
            bytes_written=written,
        )
