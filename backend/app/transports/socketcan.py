import time
import can

from app.models import CanFrame
from app.safety import TxSafetyProfile, authorize_transport_can_frame
from app.transports.base import Transport


class SocketCanTransport(Transport):
    def __init__(
        self,
        channel: str,
        interface: str = "socketcan",
        tx_enabled: bool = False,
        safety_profile: TxSafetyProfile = "diagnostic_read_only",
    ) -> None:
        self.channel = channel
        self.interface = interface
        self.tx_enabled = tx_enabled
        self.safety_profile = safety_profile
        self.bus: can.BusABC | None = None

    @property
    def name(self) -> str:
        return f"{self.interface}:{self.channel}"

    def open(self) -> None:
        self.bus = can.Bus(interface=self.interface, channel=self.channel)

    def close(self) -> None:
        if self.bus:
            self.bus.shutdown()
            self.bus = None

    def receive(self, timeout: float = 0.1) -> CanFrame | None:
        if not self.bus:
            raise RuntimeError("Transport fermé.")
        msg = self.bus.recv(timeout)
        if msg is None:
            return None
        return CanFrame(
            timestamp_us=int((msg.timestamp or time.time()) * 1_000_000),
            arbitration_id=msg.arbitration_id,
            extended=msg.is_extended_id,
            data=bytes(msg.data),
            direction="rx",
        )

    def send(self, frame: CanFrame) -> None:
        if not self.tx_enabled:
            raise PermissionError("Émission SocketCAN désactivée par CAN_TX_ENABLED.")
        if not self.bus:
            raise RuntimeError("Transport fermé.")
        decision = authorize_transport_can_frame(
            self.safety_profile,
            frame.arbitration_id,
            frame.extended,
            frame.data,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        self.bus.send(can.Message(
            arbitration_id=frame.arbitration_id,
            is_extended_id=frame.extended,
            data=frame.data,
        ))
