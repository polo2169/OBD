from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
import json
import re
import threading
import uuid

from app.config import settings
from app.models import DtcChange, ScanComparison, ScanReport, VehicleIdentityResult


_LOCK = threading.RLock()
_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def _root() -> Path:
    path = settings.diagnostic_history_dir
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        path = (backend_root / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path() -> Path:
    return _root() / "registry.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _registry() -> dict:
    payload = _read_json(_registry_path(), {})
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("active_by_profile", {})
    payload.setdefault("active_vehicle_vin", None)
    payload.setdefault("vehicles", {})
    return payload


def _manufacturer_key(name: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (name or "inconnu").casefold()).strip("-")
    return normalized or "inconnu"


def _vehicle_dir(vin: str, manufacturer: str | None = None) -> Path:
    if not _VIN.fullmatch(vin):
        raise ValueError(f"VIN invalide pour l'historique : {vin}")
    if manufacturer:
        return _root() / _manufacturer_key(manufacturer) / vin
    registry = _registry()
    item = registry["vehicles"].get(vin, {})
    return _root() / _manufacturer_key(item.get("manufacturer")) / vin


def vehicle_storage_dir(vin: str) -> Path:
    """Return the canonical on-disk directory for a known Garage vehicle."""
    if not _VIN.fullmatch(vin):
        raise ValueError("VIN invalide.")
    with _LOCK:
        registry = _registry()
        item = registry["vehicles"].get(vin)
        if not isinstance(item, dict):
            raise KeyError("Véhicule inconnu : ajoute-le d’abord au Garage.")
        return _vehicle_dir(vin, item.get("manufacturer"))


def active_identity(vehicle_profile: str) -> dict | None:
    with _LOCK:
        registry = _registry()
        vin = registry["active_by_profile"].get(vehicle_profile)
        item = registry["vehicles"].get(vin) if vin else None
        return dict(item) if isinstance(item, dict) else None


def active_vehicle() -> dict | None:
    with _LOCK:
        registry = _registry()
        vin = registry.get("active_vehicle_vin")
        item = registry["vehicles"].get(vin) if vin else None
        if not isinstance(item, dict):
            vehicles = sorted(
                registry["vehicles"].values(),
                key=lambda candidate: candidate.get("last_seen") or "",
                reverse=True,
            )
            item = vehicles[0] if vehicles else None
        return dict(item) if isinstance(item, dict) else None


def select_vehicle(vin: str) -> dict:
    if not _VIN.fullmatch(vin):
        raise ValueError("VIN invalide.")
    with _LOCK:
        registry = _registry()
        item = registry["vehicles"].get(vin)
        if not isinstance(item, dict):
            raise KeyError("Véhicule inconnu : lis d’abord son identité.")
        registry["active_vehicle_vin"] = vin
        registry["active_by_profile"][item["vehicle_profile"]] = vin
        item["last_selected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        registry["vehicles"][vin] = item
        _atomic_json(_registry_path(), registry)
        return dict(item)


def save_identity(result: VehicleIdentityResult) -> None:
    if not result.found or not result.vin or not _VIN.fullmatch(result.vin):
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        registry = _registry()
        existing = registry["vehicles"].get(result.vin, {})
        record = {
            **existing,
            "vin": result.vin,
            "vehicle_profile": result.vehicle_profile,
            "manufacturer": result.detected_manufacturer or result.manufacturer,
            "model": result.model,
            "year": result.year,
            "wmi": result.wmi,
            "first_seen": existing.get("first_seen") or now,
            "last_seen": now,
            "latest_identity_session_id": result.debug.session_id,
            "scan_count": int(existing.get("scan_count") or 0),
        }
        registry["vehicles"][result.vin] = record
        registry["active_by_profile"][result.vehicle_profile] = result.vin
        registry["active_vehicle_vin"] = result.vin
        _atomic_json(_registry_path(), registry)

        vehicle_dir = _vehicle_dir(result.vin, record["manufacturer"])
        identity_payload = result.model_dump(mode="json")
        _atomic_json(vehicle_dir / "identity" / "latest.json", identity_payload)
        identity_id = result.debug.session_id or f"identity-{now.replace(':', '').replace('+00:00', 'Z')}"
        _atomic_json(vehicle_dir / "identity" / f"{identity_id}.json", identity_payload)


def _dtc_map(report: ScanReport, comparable: set[str]) -> dict[tuple[str, str], tuple]:
    result = {}
    for ecu in report.ecus:
        if ecu.key not in comparable:
            continue
        for dtc in ecu.dtcs:
            result[(ecu.key, dtc.raw_hex)] = (ecu, dtc)
    return result


def compare_reports(previous: ScanReport | None, current: ScanReport) -> ScanComparison | None:
    if previous is None:
        return None
    previous_valid = {
        ecu.key for ecu in previous.ecus
        if ecu.detected and ecu.dtc_error is None and ecu.dtc_status_availability_mask is not None
    }
    current_valid = {
        ecu.key for ecu in current.ecus
        if ecu.detected and ecu.dtc_error is None and ecu.dtc_status_availability_mask is not None
    }
    comparable = previous_valid & current_valid
    all_ecus = {ecu.key for ecu in previous.ecus} | {ecu.key for ecu in current.ecus}
    comparison = ScanComparison(
        previous_scan_id=previous.scan_id,
        previous_scanned_at=previous.scanned_at,
        comparable_ecus=sorted(comparable),
        excluded_ecus=sorted(all_ecus - comparable),
    )
    before = _dtc_map(previous, comparable)
    after = _dtc_map(current, comparable)

    for key in sorted(before.keys() | after.keys()):
        before_item = before.get(key)
        after_item = after.get(key)
        before_dtc = before_item[1] if before_item else None
        after_dtc = after_item[1] if after_item else None
        ecu = (after_item or before_item)[0]
        meaningful_before = before_dtc is not None and before_dtc.state in {"active", "historical"}
        meaningful_after = after_dtc is not None and after_dtc.state in {"active", "historical"}
        change = DtcChange(
            ecu_key=ecu.key,
            ecu_name=ecu.name,
            code=(after_dtc or before_dtc).code,
            raw_hex=(after_dtc or before_dtc).raw_hex,
            title=(after_dtc or before_dtc).title,
            before_state=before_dtc.state if before_dtc else None,
            after_state=after_dtc.state if after_dtc else None,
            before_status_hex=before_dtc.status_hex if before_dtc else None,
            after_status_hex=after_dtc.status_hex if after_dtc else None,
        )
        if not meaningful_before and meaningful_after:
            comparison.appeared.append(change)
        elif meaningful_before and not meaningful_after:
            comparison.resolved.append(change)
        elif meaningful_before and meaningful_after:
            if before_dtc.state != after_dtc.state or before_dtc.status != after_dtc.status:
                comparison.changed.append(change)
            else:
                comparison.unchanged += 1
    return comparison


def _report_paths(vin: str, manufacturer: str | None = None) -> list[Path]:
    paths = set(_root().glob(f"*/{vin}/scans/scan-*.json"))
    if manufacturer:
        directory = _vehicle_dir(vin, manufacturer) / "scans"
        if directory.exists():
            paths.update(directory.glob("scan-*.json"))
    return sorted(paths, key=lambda path: path.name, reverse=True)


def _load_report(path: Path) -> ScanReport | None:
    try:
        return ScanReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest_report(vehicle_profile: str | None = None, vin: str | None = None) -> ScanReport | None:
    with _LOCK:
        registry = _registry()
        selected_vin = vin
        if selected_vin is None and vehicle_profile:
            selected_vin = registry["active_by_profile"].get(vehicle_profile)
        if selected_vin is None:
            candidates = [
                item for item in registry["vehicles"].values()
                if not vehicle_profile or item.get("vehicle_profile") == vehicle_profile
            ]
            candidates.sort(key=lambda item: item.get("last_seen") or "", reverse=True)
            selected_vin = candidates[0].get("vin") if candidates else None
        if not selected_vin or not _VIN.fullmatch(selected_vin):
            return None
        item = registry["vehicles"].get(selected_vin, {})
        paths = _report_paths(selected_vin, item.get("manufacturer"))
        return _load_report(paths[0]) if paths else None


def finalize_scan(
    report: ScanReport,
    requested_vin: str | None = None,
    recorded_at: str | None = None,
) -> ScanReport:
    try:
        now = datetime.fromisoformat(recorded_at) if recorded_at else datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
    except ValueError:
        now = datetime.now(timezone.utc)
    report.scan_id = f"scan-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    report.scanned_at = now.isoformat(timespec="milliseconds")
    vehicle = active_identity(report.vehicle_profile)
    discovered_vin = next((ecu.vin for ecu in report.ecus if ecu.vin and _VIN.fullmatch(ecu.vin)), None)
    report.vin = requested_vin or discovered_vin or (vehicle or {}).get("vin")
    if vehicle:
        report.manufacturer = vehicle.get("manufacturer")
        report.model = vehicle.get("model")

    previous = latest_report(report.vehicle_profile, report.vin) if report.vin else None
    report.comparison = compare_reports(previous, report)
    if not report.vin:
        report.warnings.append(
            "Rapport non rattaché à un VIN : lire l'identité du véhicule avant le prochain scan."
        )
        return report

    with _LOCK:
        registry = _registry()
        item = registry["vehicles"].get(report.vin, {
            "vin": report.vin,
            "vehicle_profile": report.vehicle_profile,
            "manufacturer": report.manufacturer or "Inconnu",
            "model": report.model or "Inconnu",
            "first_seen": report.scanned_at,
        })
        item["last_seen"] = report.scanned_at
        item["latest_scan_id"] = report.scan_id
        item["scan_count"] = int(item.get("scan_count") or 0) + 1
        registry["vehicles"][report.vin] = item
        registry["active_by_profile"][report.vehicle_profile] = report.vin
        registry["active_vehicle_vin"] = report.vin
        _atomic_json(_registry_path(), registry)
        path = _vehicle_dir(report.vin, item.get("manufacturer")) / "scans" / f"{report.scan_id}.json"
        _atomic_json(path, report.model_dump(mode="json"))
    return report


def list_vehicles() -> list[dict]:
    with _LOCK:
        registry = _registry()
        active_vin = registry.get("active_vehicle_vin")
        vehicles = [{**dict(item), "is_active": item.get("vin") == active_vin} for item in registry["vehicles"].values()]
    vehicles.sort(key=lambda item: item.get("last_seen") or "", reverse=True)
    return vehicles


def list_reports(vehicle_profile: str | None = None, vin: str | None = None) -> list[dict]:
    registry = _registry()
    selected_vins = [vin] if vin else [
        item.get("vin") for item in registry["vehicles"].values()
        if not vehicle_profile or item.get("vehicle_profile") == vehicle_profile
    ]
    summaries: list[dict] = []
    for selected_vin in selected_vins:
        if not selected_vin or not _VIN.fullmatch(selected_vin):
            continue
        item = registry["vehicles"].get(selected_vin, {})
        for path in _report_paths(selected_vin, item.get("manufacturer")):
            report = _load_report(path)
            if report is None:
                continue
            summaries.append({
                "scan_id": report.scan_id,
                "scanned_at": report.scanned_at,
                "vin": report.vin,
                "vehicle_profile": report.vehicle_profile,
                "manufacturer": report.manufacturer,
                "model": report.model,
                "dtc_summary": report.dtc_summary.model_dump(),
                "detected_ecus": sum(1 for ecu in report.ecus if ecu.detected),
            })
    summaries.sort(key=lambda item: item.get("scanned_at") or "", reverse=True)
    return summaries


def find_report(scan_id: str) -> tuple[ScanReport, Path] | None:
    if not re.fullmatch(r"scan-[A-Za-z0-9TZ-]+", scan_id):
        return None
    for path in _root().glob(f"*/*/scans/{scan_id}.json"):
        report = _load_report(path)
        if report is not None:
            return report, path
    return None


def report_html(report: ScanReport) -> str:
    summary = report.dtc_summary
    rows = []
    order = {"active": 0, "historical": 1, "not_tested": 2, "inactive": 3}
    dtcs = sorted(
        ((ecu, dtc) for ecu in report.ecus for dtc in ecu.dtcs),
        key=lambda item: (order[item[1].state], item[0].name, item[1].code),
    )
    for ecu, dtc in dtcs:
        rows.append(
            "<tr>"
            f"<td><strong>{escape(dtc.code)}</strong><br><small>{escape(dtc.raw_hex)}</small></td>"
            f"<td>{escape(ecu.name)}</td>"
            f"<td><span class='state {escape(dtc.state)}'>{escape(dtc.state_label)}</span></td>"
            f"<td>{escape(dtc.title or 'Description non confirmée')}</td>"
            f"<td>0x{escape(dtc.status_hex)}<br><small>{escape(' · '.join(dtc.status_labels))}</small></td>"
            "</tr>"
        )
    ecu_rows = "".join(
        "<tr>"
        f"<td>{escape(ecu.name)}</td><td>{'Détecté' if ecu.detected else 'Non détecté'}</td>"
        f"<td>0x{ecu.request_id:X} → 0x{ecu.response_id:X}</td>"
        f"<td>{escape(ecu.probe_method or '—')}</td><td>{escape(ecu.dtc_error or ecu.error or '—')}</td>"
        "</tr>"
        for ecu in report.ecus if ecu.request_id is not None and ecu.response_id is not None
    )
    return f"""<!doctype html>
<html lang='fr'><head><meta charset='utf-8'><title>Rapport OpenDiag {escape(report.vin or '')}</title>
<style>
body{{font-family:Arial,sans-serif;color:#171717;margin:36px}}h1{{margin-bottom:4px}}small,.muted{{color:#666}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:24px 0}}.metrics div{{border:1px solid #ddd;padding:12px;border-radius:8px}}
table{{width:100%;border-collapse:collapse;margin:12px 0 28px}}th,td{{border-bottom:1px solid #ddd;text-align:left;padding:9px;vertical-align:top}}th{{background:#f4f4f4}}
.state{{font-weight:bold}}.active{{color:#b00020}}.historical{{color:#9a5b00}}.not_tested{{color:#666}}.inactive{{color:#2d6b3c}}
@media print{{body{{margin:12mm}}}}
</style></head><body>
<p class='muted'>OpenDiag Auto · rapport diagnostic en lecture seule</p>
<h1>{escape(report.manufacturer or '')} {escape(report.model or '')}</h1>
<p>VIN <strong>{escape(report.vin or 'Non identifié')}</strong> · {escape(report.scanned_at or '')} · scan {escape(report.scan_id or '')}</p>
<div class='metrics'><div>Actifs<br><strong>{summary.active}</strong></div><div>Historiques<br><strong>{summary.historical}</strong></div><div>Tests non exécutés<br><strong>{summary.not_tested}</strong></div><div>ECU détectés<br><strong>{sum(1 for ecu in report.ecus if ecu.detected)}/{len(report.ecus)}</strong></div></div>
<h2>Calculateurs</h2><table><thead><tr><th>Calculateur</th><th>Présence</th><th>Adresses</th><th>Preuve</th><th>Remarque</th></tr></thead><tbody>{ecu_rows}</tbody></table>
<h2>Codes diagnostic</h2><table><thead><tr><th>Code</th><th>Calculateur</th><th>État</th><th>Description</th><th>Statut UDS</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan=5>Aucun code retourné.</td></tr>'}</tbody></table>
<p class='muted'>Les descriptions constructeur communautaires sont indicatives. Le code brut, le sous-type et les bits de statut UDS font foi. Aucune opération d'effacement ou de télécodage n'a été exécutée.</p>
</body></html>"""
