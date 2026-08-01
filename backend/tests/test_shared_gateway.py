import queue
import time

from app.models import CanFrame
from app.transports.base import Transport
from app.transports.shared_gateway import SharedGatewayHub


class FakePhysicalGateway(Transport):
    def __init__(self) -> None:
        self.hello = {
            "protocol": 7,
            "dual_can": True,
            "diagnostic_read_only": True,
            "live_can_ready": True,
            "diagnostic_can_ready": True,
        }
        self.last_stats = None
        self.safety_profile = "diagnostic_read_only"
        self.frames: queue.Queue[CanFrame] = queue.Queue()
        self.sent: list[CanFrame] = []
        self.opened = False

    @property
    def name(self) -> str:
        return "fake-dual-gateway"

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def receive(self, timeout: float = 0.1) -> CanFrame | None:
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, frame: CanFrame) -> None:
        self.sent.append(frame)


def test_shared_gateway_keeps_live_and_diagnostic_consumers_independent():
    physical = FakePhysicalGateway()
    hub = SharedGatewayHub(lambda: physical, physical.name)
    live_client = hub.client(("live",), "diagnostic_read_only", 16)
    diagnostic_client = hub.client(("diagnostic",), "diagnostic_read_only", 16)
    live_client.open()
    diagnostic_client.open()

    physical.frames.put(CanFrame(
        timestamp_us=1,
        arbitration_id=0x305,
        data=b"\x01",
        bus="live",
    ))
    physical.frames.put(CanFrame(
        timestamp_us=2,
        arbitration_id=0x652,
        data=b"\x02",
        bus="diagnostic",
    ))

    live = live_client.receive(0.5)
    diagnostic = diagnostic_client.receive(0.5)
    assert live and live.bus == "live" and live.arbitration_id == 0x305
    assert diagnostic and diagnostic.bus == "diagnostic" and diagnostic.arbitration_id == 0x652
    assert live_client.receive(0.01) is None
    assert diagnostic_client.receive(0.01) is None

    request = CanFrame(
        timestamp_us=time.time_ns() // 1000,
        arbitration_id=0x752,
        data=bytes.fromhex("0322F19000000000"),
        direction="tx",
        bus="diagnostic",
    )
    diagnostic_client.send(request)
    assert physical.sent == [request]

    diagnostic_client.close()
    assert physical.opened
    live_client.close()
    assert not physical.opened
