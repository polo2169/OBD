import json

from app.config import settings
from app.learn.analyzer import analyze_behavior, list_sessions
from app.learn.isotp import parse_isotp_frame, uds_service
from app.learn.models import CorrelationOptions
from app.learn.opendbc import get_opendbc_decoder
from app.safety import authorize_uds


def test_single_frame_parse():
    parsed = parse_isotp_frame(bytes.fromhex("0322F19000000000"))
    assert parsed is not None
    assert parsed.complete
    assert parsed.payload == bytes.fromhex("22F190")
    assert uds_service(parsed.payload) == 0x22


def test_sensitive_service_stays_blocked():
    assert not authorize_uds(bytes.fromhex("2701"), True).allowed


def test_opendbc_psa_catalog_is_loaded_and_decodes_engine_speed():
    decoder = get_opendbc_decoder()
    source = decoder.source_info()
    assert source.loaded
    assert source.database == "psa_aee2010_r3"
    assert source.message_count == 107
    assert source.signal_count == 430

    message, values, error = decoder.decode_frame(
        0x208,
        False,
        bytes.fromhex("1F40000000000000"),
    )
    assert error is None
    assert message is not None
    assert message.name == "Dyn_CMM"
    assert values is not None
    assert values["P000_Com_nEng"]["value"] == 1000.0
    assert values["P000_Com_nEng"]["unit"] == "1/min"


def test_post_processing_finds_repeated_bit_correlation(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260731T120000Z-test"
    events = [
        {
            "type": "meta",
            "timestamp_us": 1_000_000,
            "session_id": session_id,
            "name": "Essai frein",
            "source": "fixture",
        }
    ]

    def frame(timestamp_us: int, arbitration_id: int, first_byte: int) -> dict:
        return {
            "type": "can_frame",
            "timestamp_us": timestamp_us,
            "arbitration_id": arbitration_id,
            "extended": False,
            "data_hex": bytes([first_byte, 0, 0, 0, 0, 0, 0, 0]).hex().upper(),
            "direction": "rx",
        }

    for marker_time in (2_000_000, 6_000_000):
        for offset in (-900_000, -650_000, -400_000, -150_000):
            events.append(frame(marker_time + offset, 0x123, 0x00))
            events.append(frame(marker_time + offset, 0x456, 0x55))
        events.append({
            "type": "marker",
            "timestamp_us": marker_time,
            "name": "frein_appuye",
            "note": "Pédale maintenue",
        })
        for offset in (150_000, 400_000, 650_000, 900_000):
            events.append(frame(marker_time + offset, 0x123, 0x04))
            events.append(frame(marker_time + offset, 0x456, 0x55))

    path = tmp_path / f"{session_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(event) for event in sorted(events, key=lambda e: e["timestamp_us"])) + "\n",
        encoding="utf-8",
    )

    report = analyze_behavior(
        session_id,
        CorrelationOptions(before_ms=1000, after_ms=1000, min_samples=3),
    )
    assert report.total_frames == 32
    assert report.unique_ids == 2
    assert report.correlations[0].marker == "frein_appuye"
    assert report.correlations[0].occurrences == 2

    bit_candidates = [
        candidate
        for candidate in report.correlations[0].candidates
        if candidate.kind == "bit"
    ]
    assert any(
        candidate.arbitration_id == 0x123
        and candidate.byte_index == 0
        and candidate.bit_index == 2
        and candidate.confidence == "forte"
        for candidate in bit_candidates
    )
    assert not any(candidate.arbitration_id == 0x456 for candidate in bit_candidates)

    sessions = list_sessions()
    assert sessions[0].name == "Essai frein"
    assert sessions[0].frame_count == 32
    assert sessions[0].marker_count == 2


def test_post_processing_enriches_candidates_with_opendbc(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260731T140000Z-opendbc"
    events = [{
        "type": "meta",
        "timestamp_us": 1_000_000,
        "session_id": session_id,
        "name": "Essai accélérateur",
        "source": "fixture",
    }]

    def frame(timestamp_us: int, data_hex: str) -> dict:
        return {
            "type": "can_frame",
            "timestamp_us": timestamp_us,
            "arbitration_id": 0x208,
            "extended": False,
            "data_hex": data_hex,
            "direction": "rx",
        }

    for marker_time in (2_000_000, 6_000_000):
        for offset in (-900_000, -650_000, -400_000, -150_000):
            events.append(frame(marker_time + offset, "1F40000000000000"))
        events.append({
            "type": "marker",
            "timestamp_us": marker_time,
            "name": "accelerateur_appuye",
        })
        for offset in (150_000, 400_000, 650_000, 900_000):
            events.append(frame(marker_time + offset, "1F40002800000000"))

    (tmp_path / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in sorted(events, key=lambda e: e["timestamp_us"])) + "\n",
        encoding="utf-8",
    )

    report = analyze_behavior(
        session_id,
        CorrelationOptions(before_ms=1000, after_ms=1000, min_samples=3),
    )
    assert report.opendbc is not None
    assert report.opendbc.loaded
    assert report.opendbc.observed_messages == ["Dyn_CMM"]
    assert report.inventory[0].opendbc_message == "Dyn_CMM"
    assert "P002_Com_rAPP" in report.inventory[0].opendbc_signals
    assert any(
        candidate.kind == "dbc_signal"
        and candidate.source == "opendbc"
        and candidate.dbc_message == "Dyn_CMM"
        and candidate.dbc_signal == "P002_Com_rAPP"
        for candidate in report.correlations[0].candidates
    )
