from collections import deque
import json
import time
import serial

from app.models import CanFrame
from app.transports.base import Transport


class Esp32SerialTransport(Transport):
    def __init__(
        self,
        port: str,
        baud: int,
        tx_enabled: bool = False,
        handshake_timeout: float = 3.0,
    ) -> None:
        self.port = port
        self.baud = baud
        self.tx_enabled = tx_enabled
        self.handshake_timeout = handshake_timeout
        self.serial: serial.Serial | None = None
        self.hello: dict | None = None
        self.last_stats: dict | None = None
        self._pending_frames: deque[CanFrame] = deque()

    @property
    def name(self) -> str:
        return f"esp32:{self.port}"

    def open(self) -> None:
        self.serial = serial.Serial(self.port, self.baud, timeout=0.1)
        self.debug("transport_open", transport=self.name, baud=self.baud)
        deadline = time.monotonic() + self.handshake_timeout
        while time.monotonic() < deadline:
            message = self._read_json(max(0.01, deadline - time.monotonic()))
            if message is None:
                continue
            if message.get("type") == "hello":
                self.hello = message
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
                "Flashez esp32-s3-active pour un scan UDS en lecture."
            )
        self.debug("gateway_ready", hello=self.hello)
        self._write_command({"type": "get_status"})

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
        payload = {
            "type": "can_tx",
            "id": frame.arbitration_id,
            "ext": frame.extended,
            "data": frame.data.hex().upper(),
        }
        self._write_command(payload)

    def _read_json(self, timeout: float) -> dict | None:
        if not self.serial:
            raise RuntimeError("Transport fermé.")
        self.serial.timeout = min(max(timeout, 0.001), 0.25)
        line = self.serial.readline()
        if not line:
            return None
        try:
            message = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.debug(
                "gateway_invalid_line",
                error=str(exc),
                raw_hex=line[:256].hex().upper(),
            )
            return None
        if not isinstance(message, dict):
            self.debug("gateway_invalid_message", message=message)
            return None
        self.debug("gateway_message", message=message)
        return message

    def _decode_frame(self, message: dict) -> CanFrame:
        data_hex = message.get("data", "")
        if not isinstance(data_hex, str) or len(data_hex) > 16 or len(data_hex) % 2:
            raise ValueError("Champ data CAN invalide.")
        data = bytes.fromhex(data_hex)
        dlc = int(message.get("dlc", len(data)))
        if dlc != len(data):
            raise ValueError(f"DLC {dlc} incohérent avec {len(data)} octets.")
        arbitration_id = int(message["id"])
        extended = bool(message.get("ext", False))
        if arbitration_id < 0 or arbitration_id > (0x1FFFFFFF if extended else 0x7FF):
            raise ValueError("Identifiant CAN hors plage.")
        return CanFrame(
            timestamp_us=int(message.get("ts_us", time.time_ns() // 1000)),
            arbitration_id=arbitration_id,
            extended=extended,
            data=data,
            direction="rx",
        )

    def _handle_non_frame_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "stats":
            self.last_stats = message
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
