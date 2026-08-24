import json

import pytest

from app.transports import serial_gateway
from app.transports.serial_gateway import Esp32SerialTransport


class FakeSerial:
    def __init__(self, message: dict | str | list[dict | str]) -> None:
        self.timeout = 0.1
        self.closed = False
        self.written: list[bytes] = []
        messages = message if isinstance(message, list) else [message]
        self._lines = [
            ((item if isinstance(item, str) else json.dumps(item)) + "\n").encode()
            for item in messages
        ]

    def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def write(self, payload: bytes) -> int:
        self.written.append(payload)
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


def test_gateway_requires_firmware_diagnostic_lock_when_tx_is_enabled(monkeypatch):
    device = FakeSerial({
        "type": "hello",
        "protocol": 4,
        "readonly": False,
        "can_ready": True,
        "diagnostic_read_only": False,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)

    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    with pytest.raises(RuntimeError, match="verrou diagnostic lecture seule"):
        transport.open()

    assert device.closed


def test_gateway_allows_live_obd_when_diagnostic_satellite_is_absent(monkeypatch):
    from app.models import CanFrame

    device = FakeSerial({
        "type": "hello",
        "protocol": 7,
        "readonly": False,
        "can_ready": True,
        "dual_can": True,
        "live_can_ready": True,
        "live_obd_read_only": True,
        "diagnostic_can_ready": False,
        "diagnostic_read_only": False,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport(
        "/dev/fake",
        921600,
        tx_enabled=True,
        require_diagnostic_can=False,
    )

    transport.open()
    transport.send(CanFrame(
        timestamp_us=1,
        arbitration_id=0x7E0,
        data=bytes.fromhex("0201000000000000"),
        bus="live",
    ))

    assert device.written[-1].endswith(b'"bus":"live"}\n')


def test_gateway_configures_profile_live_bitrate_during_handshake(monkeypatch):
    device = FakeSerial([
        {
            "type": "hello",
            "protocol": 8,
            "readonly": False,
            "can_ready": True,
            "dual_can": True,
            "live_can_ready": True,
            "live_obd_read_only": True,
            "diagnostic_can_ready": True,
            "diagnostic_read_only": True,
            "live_bitrate": 500_000,
        },
        {"type": "ack", "command": "set_bitrate", "bus": "live", "bitrate": 250_000},
        {
            "type": "hello",
            "protocol": 8,
            "readonly": False,
            "can_ready": True,
            "dual_can": True,
            "live_can_ready": True,
            "live_obd_read_only": True,
            "diagnostic_can_ready": True,
            "diagnostic_read_only": True,
            "live_bitrate": 250_000,
        },
    ])
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport(
        "/dev/fake",
        921600,
        tx_enabled=True,
        require_diagnostic_can=False,
        target_live_bitrate=250_000,
    )

    transport.open()

    assert transport.hello and transport.hello["live_bitrate"] == 250_000
    assert b'{"type":"set_bitrate","bus":"live","bitrate":250000}\n' in device.written


def test_gateway_explains_when_old_firmware_cannot_select_250k(monkeypatch):
    device = FakeSerial({
        "type": "hello",
        "protocol": 7,
        "readonly": False,
        "can_ready": True,
        "dual_can": True,
        "live_can_ready": True,
        "live_obd_read_only": True,
        "diagnostic_can_ready": True,
        "diagnostic_read_only": True,
        "live_bitrate": 500_000,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport(
        "/dev/fake",
        921600,
        tx_enabled=True,
        require_diagnostic_can=False,
        target_live_bitrate=250_000,
    )

    with pytest.raises(RuntimeError, match="protocole 8"):
        transport.open()

    assert device.closed


def test_gateway_accepts_locked_firmware_and_blocks_raw_write(monkeypatch):
    from app.models import CanFrame

    device = FakeSerial({
        "type": "hello",
        "protocol": 4,
        "readonly": False,
        "can_ready": True,
        "diagnostic_read_only": True,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    transport.open()

    transport.send(CanFrame(
        timestamp_us=1,
        arbitration_id=0x74A,
        data=bytes.fromhex("0322F19000000000"),
    ))
    with pytest.raises(PermissionError, match="bloqué|non autorisé|verrouillé"):
        transport.send(CanFrame(
            timestamp_us=2,
            arbitration_id=0x74A,
            data=bytes.fromhex("042E123400000000"),
        ))

    assert device.written[-1] == b'{"type":"can_tx","id":1866,"ext":false,"data":"0322F19000000000"}\n'


def test_gateway_psa_lab_requires_capability_and_keeps_exact_allowlist(monkeypatch):
    from app.models import CanFrame

    device = FakeSerial({
        "type": "hello",
        "protocol": 6,
        "readonly": False,
        "can_ready": True,
        "diagnostic_read_only": False,
        "psa_lab": True,
        "tx_policy": "psa_lab_named_actions",
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport(
        "/dev/fake",
        921600,
        tx_enabled=True,
        safety_profile="psa_lab",
    )
    transport.open()

    transport.send(CanFrame(
        timestamp_us=1,
        arbitration_id=0x764,
        data=bytes.fromhex("052FD60003000000"),
    ))
    with pytest.raises(PermissionError, match="allowlist"):
        transport.send(CanFrame(
            timestamp_us=2,
            arbitration_id=0x764,
            data=bytes.fromhex("042F123403000000"),
        ))

    assert device.written[-1] == b'{"type":"can_tx","id":1892,"ext":false,"data":"052FD60003000000"}\n'


def test_gateway_records_stats_and_detects_sequence_gaps(monkeypatch):
    device = FakeSerial([
        {
            "type": "hello",
            "protocol": 4,
            "readonly": False,
            "can_ready": True,
            "diagnostic_read_only": True,
        },
        "F,64,A,208,8,1234",
        {"type": "stats", "rx": 12, "dropped": 0, "bus_off": 0},
        "F,C8,C,1A8,4,56",
    ])
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    events: list[dict] = []
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    transport.set_debug_sink(events.append)

    transport.open()
    first = transport.receive(0.1)
    second = transport.receive(0.1)

    assert first and first.arbitration_id == 0x208
    assert second and second.data == bytes.fromhex("56")
    assert transport.sequence_gap_count == 1
    assert transport.last_stats == {"type": "stats", "rx": 12, "dropped": 0, "bus_off": 0}
    assert any(event["type"] == "gateway_sequence_gap" for event in events)
    assert any(event["type"] == "gateway_stats" for event in events)
    assert device.written[0] == b'{"type":"get_status"}\n'


def test_uart_dual_gateway_tracks_main_and_satellite_sequences_per_bus():
    transport = Esp32SerialTransport("/dev/fake", 921600)
    transport.hello = {
        "protocol": 7,
        "driver": "twai+uart-twai",
        "dual_can": True,
        "sequence_scope": "bus",
    }

    for message in (
        {"seq": 1525, "bus": "live"},
        {"seq": 27, "bus": "diagnostic"},
        {"seq": 1526, "bus": "live"},
        {"seq": 28, "bus": "diagnostic"},
    ):
        transport._track_sequence(message)

    assert transport.sequence_gap_count == 0


def test_gateway_sends_live_mute_only_when_firmware_supports_it(monkeypatch):
    device = FakeSerial({
        "type": "hello",
        "protocol": 7,
        "readonly": False,
        "can_ready": True,
        "dual_can": True,
        "live_can_ready": True,
        "diagnostic_can_ready": True,
        "diagnostic_read_only": True,
        "live_mute_supported": True,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    transport.open()

    transport.set_live_mute(True)
    transport.set_live_mute(False)

    assert device.written[-2:] == [
        b'{"type":"live_mute","enabled":true}\n',
        b'{"type":"live_mute","enabled":false}\n',
    ]


def test_dual_gateway_decodes_buses_and_routes_diagnostic_tx(monkeypatch):
    from app.models import CanFrame

    device = FakeSerial([
        {
            "type": "hello",
            "protocol": 7,
            "readonly": False,
            "can_ready": True,
            "dual_can": True,
            "live_can_ready": True,
            "diagnostic_can_ready": True,
            "diagnostic_read_only": True,
        },
        "F,64,A,208,8,1234",
        "F,65,B,652,48,5678",
    ])
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    transport.open()

    live = transport.receive(0.1)
    diagnostic = transport.receive(0.1)
    assert live and live.bus == "live" and live.arbitration_id == 0x208
    assert diagnostic and diagnostic.bus == "diagnostic" and diagnostic.arbitration_id == 0x652

    transport.send(CanFrame(
        timestamp_us=1,
        arbitration_id=0x752,
        data=bytes.fromhex("0322F19000000000"),
        bus="diagnostic",
    ))
    assert device.written[-1] == (
        b'{"type":"can_tx","id":1874,"ext":false,'
        b'"data":"0322F19000000000","bus":"diagnostic"}\n'
    )


def test_dual_gateway_routes_only_allowlisted_obd_reads_to_live_bus(monkeypatch):
    from app.models import CanFrame

    device = FakeSerial({
        "type": "hello",
        "protocol": 7,
        "readonly": False,
        "can_ready": True,
        "dual_can": True,
        "live_can_ready": True,
        "diagnostic_can_ready": True,
        "diagnostic_read_only": True,
        "live_obd_read_only": True,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    transport.open()

    transport.send(CanFrame(
        timestamp_us=1,
        arbitration_id=0x7E0,
        data=bytes.fromhex("02010C0000000000"),
        bus="live",
    ))
    with pytest.raises(PermissionError, match="verrouillé|autorisé"):
        transport.send(CanFrame(
            timestamp_us=2,
            arbitration_id=0x752,
            data=bytes.fromhex("0322F19000000000"),
            bus="live",
        ))

    assert device.written[-1] == (
        b'{"type":"can_tx","id":2016,"ext":false,'
        b'"data":"02010C0000000000","bus":"live"}\n'
    )


def test_dual_gateway_refuses_live_tx_without_firmware_capability(monkeypatch):
    from app.models import CanFrame

    device = FakeSerial({
        "type": "hello",
        "protocol": 7,
        "readonly": False,
        "can_ready": True,
        "dual_can": True,
        "live_can_ready": True,
        "diagnostic_can_ready": True,
        "diagnostic_read_only": True,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    transport.open()

    with pytest.raises(PermissionError, match="nouveau profil double-CAN"):
        transport.send(CanFrame(
            timestamp_us=1,
            arbitration_id=0x7E0,
            data=bytes.fromhex("02010C0000000000"),
            bus="live",
        ))


def test_dual_gateway_rejects_missing_diagnostic_controller(monkeypatch):
    device = FakeSerial({
        "type": "hello",
        "protocol": 7,
        "readonly": False,
        "can_ready": True,
        "dual_can": True,
        "live_can_ready": True,
        "diagnostic_can_ready": False,
        "diagnostic_read_only": True,
    })
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)

    with pytest.raises(RuntimeError, match="diagnostic 3/8"):
        transport.open()


def test_standalone_uart_satellite_announces_diagnostic_bus(monkeypatch):
    device = FakeSerial([
        {
            "type": "hello",
            "protocol": 6,
            "readonly": False,
            "can_ready": True,
            "diagnostic_read_only": True,
            "bus_role": "diagnostic",
        },
        "F,64,A,652,8,1234",
    ])
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport("/dev/fake", 921600, tx_enabled=True)
    transport.open()

    frame = transport.receive(0.1)

    assert frame and frame.bus == "diagnostic"
    assert frame.arbitration_id == 0x652


def test_uart_dual_gateway_waits_for_stable_satellite_hello(monkeypatch):
    device = FakeSerial([
        {
            "type": "hello",
            "protocol": 7,
            "driver": "twai+uart-twai",
            "readonly": False,
            "can_ready": True,
            "dual_can": True,
            "diagnostic_read_only": True,
            "diagnostic_can_ready": True,
            "satellite_connected": True,
        },
        {
            "type": "hello",
            "protocol": 7,
            "driver": "twai+uart-twai",
            "readonly": False,
            "can_ready": True,
            "dual_can": True,
            "diagnostic_read_only": False,
            "diagnostic_can_ready": False,
            "satellite_connected": False,
        },
        {
            "type": "hello",
            "protocol": 7,
            "driver": "twai+uart-twai",
            "readonly": False,
            "can_ready": True,
            "dual_can": True,
            "diagnostic_read_only": True,
            "diagnostic_can_ready": True,
            "satellite_connected": True,
        },
    ])
    monkeypatch.setattr(serial_gateway.serial, "Serial", lambda *_args, **_kwargs: device)
    transport = Esp32SerialTransport(
        "/dev/fake",
        921600,
        tx_enabled=True,
        handshake_timeout=0.05,
    )

    transport.open()

    assert transport.hello and transport.hello["satellite_connected"] is True
    assert transport.hello["diagnostic_can_ready"] is True
