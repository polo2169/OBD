import json

import pytest

from app.transports import serial_gateway
from app.transports.serial_gateway import Esp32SerialTransport


class FakeSerial:
    def __init__(self, message: dict) -> None:
        self.timeout = 0.1
        self.closed = False
        self._lines = [(json.dumps(message) + "\n").encode()]

    def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def write(self, payload: bytes) -> int:
        return len(payload)

    def close(self) -> None:
        self.closed = True


def test_gateway_rejects_uninitialized_can_controller(monkeypatch):
    device = FakeSerial(
        {
            "type": "hello",
            "protocol": 3,
            "device": "opendiag-esp32",
            "readonly": True,
            "can_ready": False,
        }
    )
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)

    transport = Esp32SerialTransport("/dev/fake", 921600)
    with pytest.raises(RuntimeError, match="contrôleur CAN.*pas initialisé"):
        transport.open()

    assert device.closed
    assert transport.serial is None
