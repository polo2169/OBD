#!/usr/bin/env python3
"""Import previously recorded identity/scan events into the per-VIN history."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.diagnostic.dtc_status import apply_dtc_classification, summarize_dtcs
from app.diagnostic.history import finalize_scan, find_report, list_reports, save_identity
from app.models import ScanReport, VehicleIdentityResult


def events(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(event, dict):
                yield event


def imported_scan_sessions(vin: str) -> set[str]:
    sessions: set[str] = set()
    for summary in list_reports(vin=vin):
        found = find_report(summary["scan_id"])
        if found and found[0].debug.session_id:
            sessions.add(found[0].debug.session_id)
    return sessions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vin", required=True)
    parser.add_argument("traces", nargs="+", type=Path)
    args = parser.parse_args()
    records: list[tuple[str, Path, dict]] = []
    for path in args.traces:
        if not path.exists():
            raise FileNotFoundError(path)
        for event in events(path):
            if event.get("type") in {"vehicle_identity_result", "scan_report"}:
                records.append((str(event.get("recorded_at") or ""), path, event))
    records.sort(key=lambda item: item[0])

    known_sessions = imported_scan_sessions(args.vin)
    # Register vehicle identities first so even older scans are filed under the
    # correct manufacturer directory instead of a temporary "inconnu" bucket.
    for _, path, event in records:
        if event["type"] != "vehicle_identity_result":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        identity = VehicleIdentityResult.model_validate(payload)
        if identity.vin == args.vin:
            save_identity(identity)
            print(f"identité importée : {identity.vin} depuis {path.name}")

    for recorded_at, path, event in records:
        if event["type"] != "scan_report":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        session_id = str(event.get("session_id") or path.stem)
        if session_id in known_sessions:
            print(f"scan déjà importé : {session_id}")
            continue
        report = ScanReport.model_validate(payload)
        ecus = []
        for ecu in report.ecus:
            classified = [apply_dtc_classification(dtc) for dtc in ecu.dtcs]
            ecus.append(ecu.model_copy(update={"dtcs": classified}))
        report = report.model_copy(update={
            "ecus": ecus,
            "dtc_summary": summarize_dtcs(ecus),
            "debug": report.debug.model_copy(update={
                "session_id": session_id,
                "trace_file": str(path.resolve()),
            }),
        })
        saved = finalize_scan(report, args.vin, recorded_at=recorded_at)
        known_sessions.add(session_id)
        print(f"scan importé : {saved.scan_id} depuis {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
