from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

from app.config import settings
from app.models import EcuScanResult, ScanReport


def _active_session(ecu: EcuScanResult) -> int | None:
    if ecu.active_session is not None:
        return ecu.active_session
    for item in ecu.identification:
        if item.did == 0xF186 and isinstance(item.value, int):
            return item.value
    return None


def _dtc_fingerprint(ecu: EcuScanResult) -> str:
    records = sorted(f"{item.raw_hex}:{item.status_hex}" for item in ecu.dtcs)
    return sha256("\n".join(records).encode("ascii")).hexdigest()


def scan_signature(report: ScanReport) -> dict:
    detected = [ecu for ecu in report.ecus if ecu.detected]
    return {
        "vehicle_profile": report.vehicle_profile,
        "detected_count": len(detected),
        "detected_ecus": {
            ecu.key: {
                "request_id": ecu.request_id,
                "response_id": ecu.response_id,
                "probe_method": ecu.probe_method,
                "probe_response_hex": ecu.probe_response_hex,
                "active_session": _active_session(ecu),
                "dtc_count": len(ecu.dtcs),
                "dtc_fingerprint_sha256": _dtc_fingerprint(ecu),
            }
            for ecu in detected
        },
        "dtc_summary": report.dtc_summary.model_dump(),
    }


def _baseline_path(profile: str) -> Path:
    return settings.database_dir / "psa" / "baselines" / f"{profile}.json"


def compare_with_baseline(report: ScanReport) -> dict:
    path = _baseline_path(report.vehicle_profile)
    if not path.exists():
        raise FileNotFoundError(f"Référence de régression absente pour {report.vehicle_profile}.")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    actual = scan_signature(report)
    differences: list[dict] = []

    expected_ecus = baseline.get("detected_ecus", {})
    actual_ecus = actual["detected_ecus"]
    for key in sorted(set(expected_ecus) | set(actual_ecus)):
        if key not in actual_ecus:
            differences.append({"scope": "connectivity", "ecu": key, "field": "detected", "expected": True, "actual": False})
            continue
        if key not in expected_ecus:
            differences.append({"scope": "connectivity", "ecu": key, "field": "detected", "expected": False, "actual": True})
            continue
        for field in ("request_id", "response_id", "probe_method", "probe_response_hex", "active_session"):
            if expected_ecus[key].get(field) != actual_ecus[key].get(field):
                differences.append({
                    "scope": "connectivity",
                    "ecu": key,
                    "field": field,
                    "expected": expected_ecus[key].get(field),
                    "actual": actual_ecus[key].get(field),
                })
        for field in ("dtc_count", "dtc_fingerprint_sha256"):
            if expected_ecus[key].get(field) != actual_ecus[key].get(field):
                differences.append({
                    "scope": "dtc",
                    "ecu": key,
                    "field": field,
                    "expected": expected_ecus[key].get(field),
                    "actual": actual_ecus[key].get(field),
                })

    connectivity_differences = [item for item in differences if item["scope"] == "connectivity"]
    dtc_differences = [item for item in differences if item["scope"] == "dtc"]
    return {
        "baseline": baseline.get("name", path.stem),
        "baseline_file": str(path.resolve()),
        "scan_id": report.scan_id,
        "connectivity_match": not connectivity_differences,
        "dtc_match": not dtc_differences,
        "match": not differences,
        "differences": differences,
        "signature": actual,
    }
