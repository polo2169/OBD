import json
from pathlib import Path

from app.config import settings
from app.diagnostic.regression import compare_with_baseline
from app.diagnostic.trace_import import import_diagnostic_trace
from app.models import DiagnosticTraceImportRequest, ScanReport


def test_diagbox_trace_import_reassembles_did_and_quarantines_action(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_trace_import_dir", tmp_path)
    trace = """
TX 752#0322F19000000000
RX 652#101462F190564633
TX 752#3000000000000000
RX 652#214C50484E59574A
RX 652#2253313431393636
TX 764#052FD60003000000
RX 664#056FD60003000000
"""

    result = import_diagnostic_trace(DiagnosticTraceImportRequest(
        name="lecture plafonnier.log",
        content=trace,
    ))

    assert result["frame_count"] == 7
    assert result["exchange_count"] == 2
    assert result["observed_dids"] == [{
        "ecu_key": "bsi",
        "did": 0xF190,
        "value_hex": "5646334C50484E59574A53313431393636",
        "request_line": 2,
        "response_line": 3,
        "confidence": "observed_trace",
    }]
    assert result["observed_actions"][0]["ecu_key"] == "telematics"
    assert result["observed_actions"][0]["service"] == 0x2F
    assert result["observed_actions"][0]["executable"] is False
    saved = Path(result["saved_file"])
    assert saved.exists()
    assert json.loads(saved.read_text(encoding="utf-8"))["import_id"] == result["import_id"]


def test_real_peugeot_scan_still_matches_frozen_reference():
    scan = Path(__file__).resolve().parents[2] / (
        "data/diagnostics/peugeot/VF3LJHNYWJS123456/scans/"
        "scan-20260802T152802400960Z-da1fb35d.json"
    )
    if not scan.exists():
        return

    report = ScanReport.model_validate_json(scan.read_text(encoding="utf-8"))
    comparison = compare_with_baseline(report)

    assert comparison["connectivity_match"] is True
    assert comparison["dtc_match"] is True
    assert comparison["differences"] == []
