from __future__ import annotations

import time
import sys
from collections.abc import Callable
from typing import Literal

import isotp
from udsoncan import Request, Response
from udsoncan.client import Client
from udsoncan.configs import default_client_config
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.exceptions import NegativeResponseException

from app.models import CanFrame
from app.safety import SafetyDecision, authorize_obd, authorize_uds
from app.transports.base import Transport


class UdsSession:
    """UDS session using the maintained can-isotp and udsoncan stacks."""

    def __init__(
        self,
        transport: Transport,
        request_id: int,
        response_id: int,
        *,
        timeout: float = 1.0,
        read_only: bool = True,
        maintenance: bool = False,
        safety_policy: Callable[[bytes], SafetyDecision] | None = None,
        tx_bus: Literal["default", "live", "diagnostic"] = "diagnostic",
        flow_control_id: int | None = None,
        flow_control_blocksize: int = 8,
    ) -> None:
        if (request_id > 0x7FF) != (response_id > 0x7FF):
            raise ValueError("Les identifiants ISO-TP doivent utiliser le même format CAN.")
        self.transport = transport
        self.request_id = request_id
        self.response_id = response_id
        self.timeout = timeout
        self.read_only = read_only
        self.maintenance = maintenance
        self.safety_policy = safety_policy
        self.tx_bus = tx_bus
        if flow_control_id is not None:
            if not 0 <= flow_control_id <= 0x1FFFFFFF:
                raise ValueError("L'identifiant de contrôle de flux ISO-TP est hors plage CAN.")
            if (flow_control_id > 0x7FF) != (response_id > 0x7FF):
                raise ValueError("Le contrôle de flux et la réponse doivent utiliser le même format CAN.")
        self.flow_control_id = flow_control_id
        if not 0 <= flow_control_blocksize <= 0xFF:
            raise ValueError("La taille de bloc du contrôle de flux ISO-TP est hors plage.")
        self.flow_control_blocksize = flow_control_blocksize
        self.errors: list[str] = []
        self._client: Client | None = None
        self._connection: PythonIsoTpConnection | None = None
        self._transaction = None

    def __enter__(self) -> UdsSession:
        transaction = self.transport.diagnostic_transaction()
        transaction.__enter__()
        self._transaction = transaction
        try:
            return self._open()
        except Exception:
            transaction.__exit__(*sys.exc_info())
            self._transaction = None
            raise

    def _open(self) -> UdsSession:
        mode = (
            isotp.AddressingMode.Normal_29bits
            if self.request_id > 0x7FF
            else isotp.AddressingMode.Normal_11bits
        )
        address = isotp.Address(
            mode,
            txid=self.request_id,
            rxid=self.response_id,
        )
        self.transport.debug(
            "isotp_session_open",
            request_id=self.request_id,
            response_id=self.response_id,
            timeout_s=self.timeout,
            read_only=self.read_only,
            maintenance=self.maintenance,
            tx_bus=self.tx_bus,
            flow_control_id=self.flow_control_id,
            flow_control_blocksize=self.flow_control_blocksize,
        )
        stack = isotp.TransportLayer(
            rxfn=self._receive_can,
            txfn=self._send_can,
            address=address,
            error_handler=self._handle_isotp_error,
            params={
                "blocking_send": True,
                "blocksize": self.flow_control_blocksize,
                "stmin": 0,
                "tx_padding": 0x00,
                "rx_flowcontrol_timeout": max(100, int(self.timeout * 1000)),
                "rx_consecutive_frame_timeout": max(100, int(self.timeout * 1000)),
            },
            read_timeout=min(0.05, self.timeout),
        )
        connection = PythonIsoTpConnection(
            stack,
            name=f"{self.request_id:X}->{self.response_id:X}",
        )
        config = dict(default_client_config)
        config.update({
            "request_timeout": self.timeout,
            "p2_timeout": self.timeout,
            "p2_star_timeout": max(5.0, self.timeout),
        })
        self._client = Client(connection, config=config)
        self._connection = connection
        self._client.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if self._client is not None:
                self._client.close()
                self._client = None
                self._connection = None
            self.transport.debug(
                "isotp_session_close",
                request_id=self.request_id,
                response_id=self.response_id,
                error_type=exc_type.__name__ if exc_type else None,
                error=str(exc_value) if exc_value else None,
                isotp_errors=list(self.errors),
                tx_bus=self.tx_bus,
            )
        finally:
            if self._transaction is not None:
                transaction = self._transaction
                self._transaction = None
                transaction.__exit__(exc_type, exc_value, traceback)

    def send_request(self, request: Request) -> Response:
        if self._client is None:
            raise RuntimeError("Session UDS fermée.")
        payload = request.get_payload()
        decision = (
            self.safety_policy(payload)
            if self.safety_policy is not None
            else authorize_uds(payload, self.read_only, maintenance=self.maintenance)
        )
        started = time.perf_counter()
        self.transport.debug(
            "uds_request",
            request_id=self.request_id,
            response_id=self.response_id,
            service=payload[0] if payload else None,
            payload_hex=payload.hex().upper(),
            safety_allowed=decision.allowed,
            safety_reason=decision.reason,
        )
        if not decision.allowed:
            self.transport.debug(
                "uds_blocked",
                request_id=self.request_id,
                response_id=self.response_id,
                payload_hex=payload.hex().upper(),
                reason=decision.reason,
            )
            raise PermissionError(decision.reason)
        try:
            response = self._client.send_request(request, timeout=self.timeout)
        except Exception as exc:
            response_payload = None
            nrc = None
            if isinstance(exc, NegativeResponseException):
                response_payload = exc.response.original_payload.hex().upper()
                nrc = exc.response.code
            self.transport.debug(
                "uds_error",
                request_id=self.request_id,
                response_id=self.response_id,
                payload_hex=payload.hex().upper(),
                error_type=type(exc).__name__,
                error=str(exc),
                response_hex=response_payload,
                nrc=nrc,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                isotp_errors=list(self.errors),
            )
            raise
        if response is None:
            raise TimeoutError("La requête UDS n'a retourné aucune réponse.")
        self.transport.debug(
            "uds_response",
            request_id=self.request_id,
            response_id=self.response_id,
            request_hex=payload.hex().upper(),
            response_hex=response.original_payload.hex().upper(),
            positive=response.positive,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return response

    def request(self, payload: bytes) -> bytes:
        response = self.send_request(Request.from_payload(payload))
        return response.original_payload

    def request_obd(self, payload: bytes) -> bytes:
        if self._connection is None:
            raise RuntimeError("Session ISO-TP fermée.")
        decision = authorize_obd(payload)
        started = time.perf_counter()
        self.transport.debug(
            "obd_request",
            request_id=self.request_id,
            response_id=self.response_id,
            mode=payload[0] if payload else None,
            pid=payload[1] if len(payload) > 1 else None,
            payload_hex=payload.hex().upper(),
            safety_allowed=decision.allowed,
            safety_reason=decision.reason,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        try:
            self._connection.send(payload, timeout=self.timeout)
            response = self._connection.wait_frame(timeout=self.timeout, exception=True)
        except Exception as exc:
            self.transport.debug(
                "obd_error",
                request_id=self.request_id,
                response_id=self.response_id,
                payload_hex=payload.hex().upper(),
                error_type=type(exc).__name__,
                error=str(exc),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise
        if response is None:
            raise TimeoutError("La requête OBD n'a retourné aucune réponse.")
        self.transport.debug(
            "obd_response",
            request_id=self.request_id,
            response_id=self.response_id,
            request_hex=payload.hex().upper(),
            response_hex=response.hex().upper(),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return response

    def _receive_can(self, timeout: float) -> isotp.CanMessage | None:
        deadline = time.monotonic() + timeout
        frame = None
        accepted_buses = (
            {"default", "diagnostic"}
            if self.tx_bus == "default"
            else {"default", self.tx_bus}
        )
        while time.monotonic() < deadline:
            frame = self.transport.receive(timeout=max(0.001, deadline - time.monotonic()))
            if frame is None:
                return None
            if frame.bus in accepted_buses:
                break
            self.transport.debug(
                "can_frame_ignored",
                reason=f"bus_{frame.bus}_during_{self.tx_bus}_request",
                **frame.as_json(),
            )
        if frame is None or frame.bus not in accepted_buses:
            return None
        self.transport.debug(
            "can_frame",
            expected=frame.arbitration_id == self.response_id,
            **frame.as_json(),
        )
        return isotp.CanMessage(
            arbitration_id=frame.arbitration_id,
            dlc=len(frame.data),
            data=frame.data,
            extended_id=frame.extended,
        )

    def _send_can(self, message: isotp.CanMessage) -> None:
        arbitration_id = message.arbitration_id
        data = bytes(message.data)
        if data and data[0] >> 4 == 0x3 and self.flow_control_id is not None:
            arbitration_id = self.flow_control_id
        frame = CanFrame(
            timestamp_us=time.time_ns() // 1000,
            arbitration_id=arbitration_id,
            extended=arbitration_id > 0x7FF,
            data=data,
            direction="tx",
            bus=self.tx_bus,
        )
        self.transport.debug("can_frame", expected=True, **frame.as_json())
        self.transport.send(frame)

    def _handle_isotp_error(self, error: Exception) -> None:
        message = str(error)
        self.errors.append(message)
        self.transport.debug(
            "isotp_error",
            request_id=self.request_id,
            response_id=self.response_id,
            error_type=type(error).__name__,
            error=message,
        )
