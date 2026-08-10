from collections import deque
import queue
import time

from app.models import CanFrame
from app.safety import TxSafetyProfile, authorize_obd, authorize_psa_lab_uds, authorize_uds
from app.transports.base import Transport


class VirtualVehicleTransport(Transport):
    """Small deterministic ECU simulator at the CAN frame boundary.

    ISO-TP itself is deliberately handled by ``can-isotp`` in the diagnostic core.
    This simulator only behaves like the remote ECU: it acknowledges segmented
    requests and segments responses that do not fit in one classic CAN frame.
    """

    _DEFAULT_TELECODING_VALUES: dict[tuple[int, int], bytes] = {
        (0x752, 0x2200): bytes.fromhex("00"),
        (0x764, 0x2100): bytes.fromhex("0000"),
        (0x764, 0x2101): bytes.fromhex("0000"),
        (0x6A8, 0x2101): bytes.fromhex("00EFFFFFFDFFFFFF7F00"),
        (0x6AD, 0x2101): bytes.fromhex("00FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"),
    }
    _telecoding_values: dict[tuple[int, int], bytes] = dict(_DEFAULT_TELECODING_VALUES)

    @classmethod
    def reset_simulation(cls) -> None:
        cls._telecoding_values = dict(cls._DEFAULT_TELECODING_VALUES)

    def __init__(
        self,
        read_only: bool = True,
        maintenance: bool = False,
        response_ids: dict[int, int] | None = None,
        flow_control_ids: dict[int, int] | None = None,
        safety_profile: TxSafetyProfile = "diagnostic_read_only",
    ) -> None:
        self.read_only = read_only
        self.maintenance = maintenance
        self.response_ids = response_ids or {}
        self.flow_control_ids = flow_control_ids or {}
        self.safety_profile = safety_profile
        self._queue: queue.Queue[CanFrame] = queue.Queue()
        self._open = False
        self._request_id: int | None = None
        self._request_size = 0
        self._request_payload = bytearray()
        self._request_sequence = 1
        self._response_request_id: int | None = None
        self._response_id: int | None = None
        self._response_frames: deque[bytes] = deque()

    @property
    def name(self) -> str:
        return "virtual"

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False
        self._reset_request()
        self._reset_response()

    def receive(self, timeout: float = 0.1) -> CanFrame | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, frame: CanFrame) -> None:
        if not self._open:
            raise RuntimeError("Transport fermé.")
        if not frame.data:
            raise ValueError("Trame CAN vide.")

        pci_type = frame.data[0] >> 4
        if pci_type == 0x0:
            self._receive_single_frame(frame)
        elif pci_type == 0x1:
            self._receive_first_frame(frame)
        elif pci_type == 0x2:
            self._receive_consecutive_frame(frame)
        elif pci_type == 0x3:
            self._receive_flow_control(frame)
        else:
            raise ValueError(f"Type ISO-TP non pris en charge : 0x{pci_type:X}.")

    def _receive_single_frame(self, frame: CanFrame) -> None:
        length = frame.data[0] & 0x0F
        if length == 0 or length > min(7, len(frame.data) - 1):
            raise ValueError("Longueur ISO-TP Single Frame invalide.")
        self._handle_request(frame.arbitration_id, frame.data[1:1 + length])

    def _receive_first_frame(self, frame: CanFrame) -> None:
        if len(frame.data) < 2:
            raise ValueError("ISO-TP First Frame tronquée.")
        self._request_size = ((frame.data[0] & 0x0F) << 8) | frame.data[1]
        self._request_payload = bytearray(frame.data[2:])
        self._request_sequence = 1
        self._request_id = frame.arbitration_id
        self._queue_frame(
            self._response_id_for(frame.arbitration_id),
            bytes.fromhex("3000000000000000"),
        )

    def _receive_consecutive_frame(self, frame: CanFrame) -> None:
        if self._request_id is None or frame.arbitration_id != self._request_id:
            raise ValueError("ISO-TP Consecutive Frame inattendue.")
        sequence = frame.data[0] & 0x0F
        if sequence != self._request_sequence:
            raise ValueError(
                f"Séquence ISO-TP invalide : {sequence}, attendu {self._request_sequence}."
            )
        self._request_sequence = (self._request_sequence + 1) & 0x0F
        self._request_payload.extend(frame.data[1:])
        if len(self._request_payload) >= self._request_size:
            request_id = self._request_id
            payload = bytes(self._request_payload[:self._request_size])
            self._reset_request()
            self._handle_request(request_id, payload)

    def _receive_flow_control(self, frame: CanFrame) -> None:
        flow_status = frame.data[0] & 0x0F
        if flow_status != 0:
            raise ValueError(f"Flow Status ISO-TP non pris en charge : {flow_status}.")
        expected_flow_control_ids = {
            self._response_request_id,
            self.flow_control_ids.get(self._response_request_id),
        }
        if self._response_id is None or frame.arbitration_id not in expected_flow_control_ids:
            return
        while self._response_frames:
            self._queue_frame(self._response_id, self._response_frames.popleft())
        self._reset_response()

    def _handle_request(self, request_id: int, uds: bytes) -> None:
        if uds[:1] in {b"\x01", b"\x03", b"\x07", b"\x09"}:
            decision = authorize_obd(uds)
        elif self.safety_profile == "psa_lab":
            decision = authorize_psa_lab_uds(request_id, uds)
        else:
            decision = authorize_uds(uds, self.read_only, maintenance=self.maintenance)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        self._queue_response(
            request_id,
            self._response_id_for(request_id),
            self._response(uds, request_id),
        )

    def _queue_response(self, request_id: int, response_id: int, payload: bytes) -> None:
        if len(payload) <= 7:
            self._reset_response()
            data = (bytes([len(payload)]) + payload).ljust(8, b"\x00")
            self._queue_frame(response_id, data)
            return
        if len(payload) > 0xFFF:
            raise ValueError("Réponse virtuelle trop longue pour ISO-TP classique.")

        first = bytes([
            0x10 | ((len(payload) >> 8) & 0x0F),
            len(payload) & 0xFF,
        ]) + payload[:6]
        self._reset_response()
        self._response_request_id = request_id
        self._response_id = response_id
        sequence = 1
        for offset in range(6, len(payload), 7):
            chunk = payload[offset:offset + 7]
            frame = (bytes([0x20 | sequence]) + chunk).ljust(8, b"\x00")
            self._response_frames.append(frame)
            sequence = (sequence + 1) & 0x0F
        self._queue_frame(response_id, first.ljust(8, b"\x00"))

    def _queue_frame(self, arbitration_id: int, data: bytes) -> None:
        self._queue.put(CanFrame(
            timestamp_us=time.time_ns() // 1000,
            arbitration_id=arbitration_id,
            extended=arbitration_id > 0x7FF,
            data=data,
            direction="rx",
        ))

    def _reset_request(self) -> None:
        self._request_id = None
        self._request_size = 0
        self._request_payload.clear()
        self._request_sequence = 1

    def _reset_response(self) -> None:
        self._response_request_id = None
        self._response_id = None
        self._response_frames.clear()

    def _response_id_for(self, request_id: int) -> int:
        return self.response_ids.get(request_id, request_id + 8)

    def _response(self, uds: bytes, request_id: int) -> bytes:
        obd_values = {
            bytes.fromhex("0902"): b"\x49\x02\x01ZFA31200001234567",
            bytes.fromhex("0904"): b"\x49\x04\x01SIM-CAL-2026",
            bytes.fromhex("0906"): bytes.fromhex("49060112345678"),
            bytes.fromhex("090A"): b"\x49\x0A\x01SIM ENGINE ECU",
            bytes.fromhex("0100"): bytes.fromhex("41001FFF8003"),
            bytes.fromhex("0120"): bytes.fromhex("4120201A0001"),
            bytes.fromhex("0140"): bytes.fromhex("414054000094"),
            bytes.fromhex("0104"): bytes.fromhex("410459"),
            bytes.fromhex("0105"): bytes.fromhex("410580"),
            bytes.fromhex("0106"): bytes.fromhex("410680"),
            bytes.fromhex("0107"): bytes.fromhex("41077D"),
            bytes.fromhex("0108"): bytes.fromhex("410880"),
            bytes.fromhex("0109"): bytes.fromhex("410980"),
            bytes.fromhex("010A"): bytes.fromhex("410A23"),
            bytes.fromhex("010B"): bytes.fromhex("410B64"),
            bytes.fromhex("010C"): bytes.fromhex("410C0C30"),
            bytes.fromhex("010D"): bytes.fromhex("410D00"),
            bytes.fromhex("010E"): bytes.fromhex("410E80"),
            bytes.fromhex("010F"): bytes.fromhex("410F50"),
            bytes.fromhex("0110"): bytes.fromhex("411004D2"),
            bytes.fromhex("0111"): bytes.fromhex("411120"),
            bytes.fromhex("011F"): bytes.fromhex("411F000A"),
            bytes.fromhex("0123"): bytes.fromhex("41230FA0"),
            bytes.fromhex("012C"): bytes.fromhex("412C66"),
            bytes.fromhex("012D"): bytes.fromhex("412D7A"),
            bytes.fromhex("012F"): bytes.fromhex("412F80"),
            bytes.fromhex("0142"): bytes.fromhex("4142315C"),
            bytes.fromhex("0144"): bytes.fromhex("41448000"),
            bytes.fromhex("0146"): bytes.fromhex("414650"),
            bytes.fromhex("0159"): bytes.fromhex("41590FA0"),
            bytes.fromhex("015C"): bytes.fromhex("415C80"),
            bytes.fromhex("015E"): bytes.fromhex("415E0032"),
        }
        if uds in obd_values:
            return obd_values[uds]
        if uds[:1] == b"\x22" and len(uds) >= 3:
            did = int.from_bytes(uds[1:3], "big")
            telecoding_value = self._telecoding_values.get((request_id, did))
            if telecoding_value is not None:
                return b"\x62" + uds[1:3] + telecoding_value
            values = {
                0xF180: b"SIM-BOOT-1.0",
                0xF181: b"SIM-APP-3.2.1",
                0xF186: b"\x01",
                0xF187: b"PSA-9678521080",
                0xF189: b"SW-2026.07",
                0xF18C: f"SIM-{request_id:03X}-0001".encode(),
                0xF190: b"VF3LJHNYWJS123456",
            }
            if did in values:
                return b"\x62" + uds[1:3] + values[did]
            return b"\x7F\x22\x31"
        if uds[:2] == b"\x19\x02":
            # Un défaut représentatif par famille permet de tester tout le
            # pipeline sans prétendre simuler une voiture réelle.
            virtual_dtcs = {
                0x6AD: bytes.fromhex("4031002F"),  # C0031 ABS
                0x752: bytes.fromhex("90030008"),  # B1003 BSI
                0x74A: bytes.fromhex("92380008"),  # B1238 CVM
            }
            return b"\x59\x02\xFF" + virtual_dtcs.get(request_id, b"")
        if uds[:1] == b"\x14":
            return b"\x54"
        if uds[:1] == b"\x10":
            return b"\x50" + uds[1:2] + b"\x00\x32\x01\xF4"
        if uds[:1] == b"\x3E":
            return b"\x7E\x00"
        if uds == b"\x27\x03":
            return bytes.fromhex("670312345678")
        if uds[:2] == b"\x27\x04" and len(uds) == 6:
            return b"\x67\x04"
        if uds[:1] == b"\x2E" and len(uds) >= 4:
            did = int.from_bytes(uds[1:3], "big")
            self._telecoding_values[(request_id, did)] = bytes(uds[3:])
            return b"\x6E" + uds[1:3]
        if uds in {
            bytes.fromhex("2FD6000300"),
            bytes.fromhex("2FD60000"),
            bytes.fromhex("2FD66003"),
            bytes.fromhex("2FD66000"),
            bytes.fromhex("2FD6700330"),
            bytes.fromhex("2FD6700340"),
            bytes.fromhex("2FD6700350"),
        }:
            return b"\x6F" + uds[1:]
        return b"\x7F" + uds[:1] + b"\x11"
