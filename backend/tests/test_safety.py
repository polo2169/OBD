import pytest

from app.safety import (
    authorize_diagnostic_can_frame,
    authorize_live_obd_can_frame,
    authorize_obd,
    authorize_transport_can_frame,
    authorize_uds,
    authorize_psa_lab_uds,
)
from app.transports.base import validate_gateway_tx_policy


def test_gateway_policy_rejects_raw_active_firmware_even_when_backend_tx_is_disabled():
    with pytest.raises(RuntimeError, match="non filtrée"):
        validate_gateway_tx_policy(
            {
                "readonly": False,
                "diagnostic_read_only": False,
                "psa_lab": False,
                "tx_policy": "unrestricted",
            },
            tx_enabled=False,
            safety_profile="diagnostic_read_only",
            require_diagnostic_can=True,
        )


def test_gateway_policy_accepts_passive_and_allowlisted_firmware():
    validate_gateway_tx_policy(
        {"readonly": True, "tx_policy": "blocked"},
        tx_enabled=False,
        safety_profile="diagnostic_read_only",
        require_diagnostic_can=True,
    )
    validate_gateway_tx_policy(
        {
            "readonly": False,
            "diagnostic_read_only": True,
            "tx_policy": "diagnostic_read_only",
        },
        tx_enabled=True,
        safety_profile="diagnostic_read_only",
        require_diagnostic_can=True,
    )


def test_read_did_allowed():
    assert authorize_uds(b"\x22\xF1\x90", True).allowed


def test_security_access_blocked():
    result = authorize_uds(b"\x27\x01", True)
    assert not result.allowed


def test_write_did_blocked():
    result = authorize_uds(b"\x2E\xF1\x90", True)
    assert not result.allowed


def test_programming_session_blocked_in_read_only_mode():
    result = authorize_uds(b"\x10\x02", True)
    assert not result.allowed


def test_extended_diagnostic_session_allowed_in_read_only_mode():
    assert authorize_uds(b"\x10\x03", True).allowed


def test_read_memory_services_are_blocked_even_though_they_do_not_write():
    assert not authorize_uds(b"\x23\x00", True).allowed
    assert not authorize_uds(b"\x24\x00", True).allowed


def test_dtc_clear_requires_explicit_maintenance_mode():
    assert not authorize_uds(bytes.fromhex("14FFFFFF"), False).allowed
    assert authorize_uds(bytes.fromhex("14FFFFFF"), False, maintenance=True).allowed
    assert not authorize_uds(bytes.fromhex("14FFFF"), False, maintenance=True).allowed
    assert authorize_psa_lab_uds(0x764, bytes.fromhex("14FFFFFF")).allowed
    assert not authorize_psa_lab_uds(0x764, bytes.fromhex("14FFFF00")).allowed


def test_sensor_mode_only_allows_reading_obd_pids():
    assert authorize_obd(bytes.fromhex("010C")).allowed
    assert not authorize_obd(bytes.fromhex("0400")).allowed


def test_can_policy_allows_read_did_and_flow_control():
    assert authorize_diagnostic_can_frame(0x74A, False, bytes.fromhex("0322F19000000000")).allowed
    assert authorize_diagnostic_can_frame(0x7B0, False, bytes.fromhex("0322F19000000000")).allowed
    assert authorize_diagnostic_can_frame(0x74A, False, bytes.fromhex("3008000000000000")).allowed


def test_can_policy_blocks_write_clear_security_and_unknown_ids():
    for data in ("042E123400000000", "0414FFFFFF000000", "0227010000000000"):
        assert not authorize_diagnostic_can_frame(0x752, False, bytes.fromhex(data)).allowed
        assert not authorize_diagnostic_can_frame(0x7B0, False, bytes.fromhex(data)).allowed
    assert not authorize_diagnostic_can_frame(0x123, False, bytes.fromhex("0322F19000000000")).allowed


def test_can_policy_blocks_fragmented_requests_and_obd_clear():
    assert not authorize_diagnostic_can_frame(0x752, False, bytes.fromhex("10092E123456789A")).allowed
    assert not authorize_diagnostic_can_frame(0x7E0, False, bytes.fromhex("0104000000000000")).allowed


def test_live_6_14_policy_only_allows_obd_read_modes_and_flow_control():
    assert authorize_live_obd_can_frame(0x7DF, False, bytes.fromhex("0201000000000000")).allowed
    assert authorize_live_obd_can_frame(0x7E0, False, bytes.fromhex("02010C0000000000")).allowed
    assert authorize_live_obd_can_frame(0x18DB33F1, True, bytes.fromhex("0201000000000000")).allowed
    assert authorize_live_obd_can_frame(0x18DA10F1, True, bytes.fromhex("0209020000000000")).allowed
    assert authorize_live_obd_can_frame(0x7E0, False, bytes.fromhex("0209020000000000")).allowed
    assert authorize_live_obd_can_frame(0x7E0, False, bytes.fromhex("3008000000000000")).allowed
    assert authorize_live_obd_can_frame(0x18DA10F1, True, bytes.fromhex("3008000000000000")).allowed

    assert not authorize_live_obd_can_frame(0x7DF, False, bytes.fromhex("3008000000000000")).allowed
    assert not authorize_live_obd_can_frame(0x18DB33F1, True, bytes.fromhex("3008000000000000")).allowed
    assert not authorize_live_obd_can_frame(0x18DA11F1, True, bytes.fromhex("0201000000000000")).allowed
    assert not authorize_live_obd_can_frame(0x18DA10F1, True, bytes.fromhex("0204000000000000")).allowed
    assert not authorize_live_obd_can_frame(0x7E0, False, bytes.fromhex("0104000000000000")).allowed
    assert not authorize_live_obd_can_frame(0x7E0, False, bytes.fromhex("0222F10000000000")).allowed
    assert not authorize_live_obd_can_frame(0x752, False, bytes.fromhex("0322F19000000000")).allowed


def test_transport_policy_uses_bus_specific_allowlists():
    obd = bytes.fromhex("02010C0000000000")
    uds = bytes.fromhex("0322F19000000000")
    assert authorize_transport_can_frame("diagnostic_read_only", 0x7E0, False, obd, "live").allowed
    assert not authorize_transport_can_frame("diagnostic_read_only", 0x752, False, uds, "live").allowed
    assert authorize_transport_can_frame("diagnostic_read_only", 0x752, False, uds, "diagnostic").allowed
