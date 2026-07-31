import json
import socket

import pytest

from app.transports import wifi_gateway
from app.transports.wifi_gateway import Esp32WifiTransport


class FakeSocket:
    def __init__(self, messages: list[dict | str]) -> None:
        self._chunks = [
            "".join(
                (message if isinstance(message, str) else json.dumps(message)) + "\n"
                for message in messages
            ).encode()
        ]
        self.closed = False
        self.sent: list[bytes] = []
        self.timeout = 0.1

    def setsockopt(self, *_args) -> None:
        pass

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def recv(self, _size: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        raise socket.timeout

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def shutdown(self, _how: int) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def hello(**overrides) -> dict:
    message = {
        "type": "hello",
        "protocol": 3,
        "device": "opendiag-esp32",
        "readonly": True,
        "can_ready": True,
        "wifi_ready": True,
    }
    message.update(overrides)
    return message


def test_wifi_gateway_receives_frames_and_detects_sequence_gaps(monkeypatch):
    device = FakeSocket([
        hello(),
        "F,64,A,208,8,1234",
        "F,C8,C,1A8,4,56",
    ])
    monkeypatch.setattr(wifi_gateway.socket, "create_connection", lambda *_args, **_kwargs: device)
    events: list[dict] = []
    transport = Esp32WifiTransport("192.168.4.1", 35000)
    transport.set_debug_sink(events.append)

    transport.open()
    first = transport.receive(0.1)
    second = transport.receive(0.1)

    assert first and first.arbitration_id == 0x208
    assert second and second.data == bytes.fromhex("56")
    assert transport.sequence_gap_count == 1
    assert any(event["type"] == "gateway_sequence_gap" for event in events)
    assert device.sent == [b'{"type":"get_status"}\n']


def test_wifi_gateway_rejects_uninitialized_can(monkeypatch):
    device = FakeSocket([hello(can_ready=False)])
    monkeypatch.setattr(wifi_gateway.socket, "create_connection", lambda *_args, **_kwargs: device)
    transport = Esp32WifiTransport("192.168.4.1", 35000)

    with pytest.raises(RuntimeError, match="contrôleur CAN.*pas initialisé"):
        transport.open()

    assert device.closed
    assert transport.socket is None


def test_wifi_gateway_blocks_transmit_by_default():
    transport = Esp32WifiTransport("192.168.4.1", 35000)
    with pytest.raises(PermissionError, match="désactivée"):
        from app.models import CanFrame

        transport.send(CanFrame(timestamp_us=1, arbitration_id=1, data=b""))
