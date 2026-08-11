from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import re
import threading
import uuid

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.history import active_vehicle
from app.diagnostic.isotp import UdsSession
from app.diagnostic.psa_advanced import (
    _find_ecu,
    _require_advanced_read,
    _require_lab_preconditions,
    _trace_sink,
    _unlock_security,
)
from app.diagnostic.uds import enter_extended_session, read_data_by_identifier, write_data_by_identifier
from app.models import (
    TelecodingBackupSummary,
    TelecodingCatalogResult,
    TelecodingExecuteRequest,
    TelecodingExecuteResult,
    TelecodingFieldChange,
    TelecodingPreviewRequest,
    TelecodingPreviewResult,
    TelecodingSnapshotRequest,
    TelecodingSnapshotResult,
)
from app.safety import authorize_psa_lab_uds
from app.session import SessionWriter
from app.transports.factory import build_transport


_SNAPSHOT_ID = re.compile(r"^telecoding-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_AUDIT_LOCK = threading.Lock()


class StaleTelecodingSnapshotError(RuntimeError):
    """Raised before any write when the ECU no longer matches the backup."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat(timespec="seconds")


def _root() -> Path:
    path = settings.telecoding_backup_dir
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        path = (backend_root / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _security_audit(payload: dict) -> None:
    path = settings.security_audit_file
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        path = (backend_root / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": _iso_now(), "type": "telecoding_execution", **payload}
    with _AUDIT_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _active_vin() -> str | None:
    vehicle = active_vehicle()
    return str(vehicle.get("vin")) if vehicle and vehicle.get("vin") else None


def _variant_and_zone(ecu_key: str, variant_id: str, did: int) -> tuple[object, dict, dict]:
    ecu = _find_ecu(ecu_key)
    kb = KnowledgeBase()
    if ecu.telecoding_variant and variant_id != ecu.telecoding_variant:
        raise ValueError(
            f"La variante {variant_id} ne correspond pas à la variante identifiée "
            f"sur ce véhicule ({ecu.telecoding_variant})."
        )
    variant = kb.telecoding_variant(ecu.family, variant_id)
    if variant["request_id"] != ecu.request_id or variant["response_id"] != ecu.response_id:
        raise ValueError(
            "L'adressage de la variante PyPSADiag ne correspond pas au calculateur du profil véhicule."
        )
    zone = next((item for item in variant["zones"] if item["did"] == did), None)
    if zone is None:
        raise KeyError(f"Zone 0x{did:04X} absente de la variante {variant_id}.")
    return ecu, variant, zone


def telecoding_catalog(ecu_key: str) -> TelecodingCatalogResult:
    ecu = _find_ecu(ecu_key)
    kb = KnowledgeBase()
    metadata = kb.pypsadiag_metadata()
    variants = kb.telecoding_variants_for_family(ecu.family)
    if ecu.telecoding_variant:
        variants = [item for item in variants if item["id"] == ecu.telecoding_variant]
    for variant in variants:
        address_matches = (
            variant["request_id"] == ecu.request_id
            and variant["response_id"] == ecu.response_id
        )
        variant["write_supported"] = bool(
            variant["write_supported"]
            and address_matches
            and ecu.telecoding_write_allowed
        )
        if not ecu.telecoding_write_allowed:
            variant["security_keys"] = []
    return TelecodingCatalogResult(
        ecu_key=ecu.key,
        ecu_name=ecu.name,
        ecu_family=ecu.family,
        ecu_request_id=ecu.request_id,
        ecu_response_id=ecu.response_id,
        source=metadata.get("source"),
        revision=metadata.get("revision"),
        license=metadata.get("license"),
        warning=(
            f"Variante {ecu.telecoding_variant} confirmée par les lectures du véhicule. "
            "Lecture et sauvegarde autorisées ; écriture verrouillée tant que la clé "
            "application exacte de cet ESP n'est pas prouvée."
            if ecu.telecoding_variant and not ecu.telecoding_write_allowed
            else "Données communautaires non validées sur ce VIN. La variante doit être confirmée "
                 "par l'identification du calculateur avant toute écriture."
        ),
        variants=variants,
    )


def _snapshot_path(vin: str | None, snapshot_id: str) -> Path:
    return _root() / "backups" / (vin or "sans-vin") / f"{snapshot_id}.json"


def _execution_path(vin: str | None, execution_id: str) -> Path:
    return _root() / "executions" / (vin or "sans-vin") / f"{execution_id}.json"


def _load_snapshot(snapshot_id: str) -> dict:
    if not _SNAPSHOT_ID.fullmatch(snapshot_id):
        raise KeyError("Identifiant de sauvegarde invalide.")
    matches = list((_root() / "backups").glob(f"*/{snapshot_id}.json"))
    if len(matches) != 1:
        raise KeyError(f"Sauvegarde de télécodage introuvable : {snapshot_id}.")
    try:
        payload = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Sauvegarde de télécodage illisible.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Format de sauvegarde de télécodage invalide.")
    return payload


def create_telecoding_snapshot(ecu_key: str, request: TelecodingSnapshotRequest) -> TelecodingSnapshotResult:
    _require_advanced_read()
    ecu, variant, zone = _variant_and_zone(ecu_key, request.variant_id, request.did)
    if variant["protocol"] != "uds":
        raise ValueError("La lecture de cette variante KWP n'est pas encore supportée par le transport UDS.")

    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    opened = False
    try:
        transport.open()
        opened = True
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=True,
            flow_control_id=ecu.flow_control_id,
            flow_control_blocksize=ecu.flow_control_blocksize,
            tx_padding=ecu.isotp_tx_padding,
        ) as session:
            enter_extended_session(session)
            _, raw = read_data_by_identifier(session, request.did)
    finally:
        if opened:
            transport.close()
        if trace:
            trace.finish()

    captured_at = _iso_now()
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = f"telecoding-{stamp}-{uuid.uuid4().hex[:8]}"
    digest = sha256(raw).hexdigest().upper()
    fields = KnowledgeBase.decode_telecoding_fields(zone, raw)
    vin = _active_vin()
    path = _snapshot_path(vin, snapshot_id)
    payload = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "captured_at": captured_at,
        "ecu_key": ecu.key,
        "ecu_name": ecu.name,
        "variant_id": variant["id"],
        "variant_name": variant["name"],
        "did": request.did,
        "did_hex": f"{request.did:04X}",
        "zone_name": zone["name"],
        "vin": vin,
        "raw_hex": raw.hex().upper(),
        "sha256": digest,
        "fields": fields,
        "source": variant.get("source"),
        "session_id": trace.id if trace else None,
        "backup_file": str(path.resolve()),
    }
    _atomic_json(path, payload)
    return TelecodingSnapshotResult(**payload)


def list_telecoding_backups(ecu_key: str | None = None) -> list[TelecodingBackupSummary]:
    summaries: list[TelecodingBackupSummary] = []
    for path in sorted((_root() / "backups").glob("*/*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if ecu_key and payload.get("ecu_key") != ecu_key:
                continue
            summaries.append(TelecodingBackupSummary(
                snapshot_id=payload["snapshot_id"],
                captured_at=payload["captured_at"],
                ecu_key=payload["ecu_key"],
                variant_id=payload["variant_id"],
                did=payload["did"],
                did_hex=payload["did_hex"],
                zone_name=payload["zone_name"],
                vin=payload.get("vin"),
                sha256=payload["sha256"],
                raw_length=len(bytes.fromhex(payload["raw_hex"])),
            ))
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            continue
    return summaries[:100]


def get_telecoding_backup(snapshot_id: str) -> TelecodingSnapshotResult:
    return TelecodingSnapshotResult(**_load_snapshot(snapshot_id))


def _preview_payload(snapshot: dict, request: TelecodingPreviewRequest) -> TelecodingPreviewResult:
    ecu, variant, zone = _variant_and_zone(
        snapshot["ecu_key"], snapshot["variant_id"], int(snapshot["did"])
    )
    if request.snapshot_id != snapshot["snapshot_id"]:
        raise ValueError("La demande ne correspond pas à la sauvegarde chargée.")
    if len({change.field_key for change in request.changes}) != len(request.changes):
        raise ValueError("Un même paramètre ne peut apparaître qu'une fois dans un plan.")

    before = bytes.fromhex(snapshot["raw_hex"])
    if sha256(before).hexdigest().upper() != snapshot["sha256"]:
        raise ValueError("L'empreinte de la sauvegarde ne correspond plus à son contenu.")
    patched = bytearray(before)
    decoded_before = {
        field["key"]: field
        for field in KnowledgeBase.decode_telecoding_fields(zone, before)
    }
    field_changes: list[TelecodingFieldChange] = []
    occupied_bits: set[tuple[int, int]] = set()

    for change in request.changes:
        field = next((item for item in zone["fields"] if item["key"] == change.field_key), None)
        if field is None:
            raise KeyError(f"Paramètre inconnu : {change.field_key}.")
        current = decoded_before.get(change.field_key)
        if not field["writable"] or not current or not current["available"]:
            raise PermissionError(f"Le paramètre {field['name']} n'est pas écrivable pour cette zone.")
        option = next(
            (item for item in field["options"] if item["key"] == change.option_key),
            None,
        )
        if option is None:
            raise KeyError(f"Option inconnue pour {field['name']} : {change.option_key}.")

        start = field["byte"]
        length = field["byte_length"]
        mask = int(field["mask_hex"], 16)
        encoded = int(option["encoded_hex"], 16)
        if encoded & ~mask:
            raise ValueError(f"L'option {option['name']} dépasse le masque documenté.")
        for local_bit in range(length * 8):
            if mask & (1 << local_bit):
                absolute_bit = (start + length - 1 - local_bit // 8, local_bit % 8)
                if absolute_bit in occupied_bits:
                    raise ValueError("Deux changements du plan modifient les mêmes bits.")
                occupied_bits.add(absolute_bit)
        segment = int.from_bytes(patched[start:start + length], "big")
        patched[start:start + length] = ((segment & ~mask) | encoded).to_bytes(length, "big")
        field_changes.append(TelecodingFieldChange(
            field_key=field["key"],
            field_name=field["name"],
            previous_option_key=current.get("value_key"),
            previous_value=current.get("value"),
            requested_option_key=option["key"],
            requested_value=option["name"],
        ))

    after = bytes(patched)
    changed_indexes = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    blockers: list[str] = []
    if not ecu.telecoding_write_allowed:
        blockers.append(
            "L'écriture est verrouillée pour ce calculateur dans le profil véhicule ; "
            "lecture et sauvegarde uniquement."
        )
    if not variant["write_supported"]:
        blockers.append("La variante ou son protocole ne permet pas l'écriture UDS contrôlée.")
    if not zone["writable"]:
        blockers.append("Cette zone ne contient aucun champ structuré écrivable.")
    if not changed_indexes:
        blockers.append("Le plan ne modifie aucun octet : la valeur demandée est déjà active.")
    plan_document = {
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_sha256": snapshot["sha256"],
        "ecu_key": snapshot["ecu_key"],
        "variant_id": snapshot["variant_id"],
        "did": snapshot["did"],
        "raw_after_hex": after.hex().upper(),
        "changes": [item.model_dump() for item in field_changes],
    }
    plan_hash = sha256(
        json.dumps(plan_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest().upper()
    return TelecodingPreviewResult(
        snapshot_id=snapshot["snapshot_id"],
        plan_hash=plan_hash,
        ecu_key=snapshot["ecu_key"],
        variant_id=snapshot["variant_id"],
        did=snapshot["did"],
        raw_before_hex=before.hex().upper(),
        raw_after_hex=after.hex().upper(),
        changed_byte_indexes=changed_indexes,
        changes=field_changes,
        fields_after=KnowledgeBase.decode_telecoding_fields(zone, after),
        executable=not blockers,
        blockers=blockers,
    )


def preview_telecoding(request: TelecodingPreviewRequest) -> TelecodingPreviewResult:
    return _preview_payload(_load_snapshot(request.snapshot_id), request)


def execute_telecoding(request: TelecodingExecuteRequest) -> TelecodingExecuteResult:
    if not settings.psa_telecoding_write_enabled:
        raise PermissionError("Écriture télécodage verrouillée : PSA_TELECODING_WRITE_ENABLED=false.")
    if not settings.psa_security_access_enabled:
        raise PermissionError("Écriture télécodage impossible : PSA_SECURITY_ACCESS_ENABLED=false.")
    snapshot = _load_snapshot(request.snapshot_id)
    preview = _preview_payload(snapshot, request)
    if preview.plan_hash != request.plan_hash.upper():
        raise PermissionError("Le plan a changé depuis sa validation : génère un nouveau diff.")
    if not preview.executable:
        raise PermissionError("Plan non exécutable : " + ", ".join(preview.blockers))

    ecu, variant, zone = _variant_and_zone(
        snapshot["ecu_key"], snapshot["variant_id"], int(snapshot["did"])
    )
    if not ecu.telecoding_write_allowed:
        raise PermissionError(
            "Écriture interdite pour ce calculateur dans le profil véhicule ; "
            "la clé application exacte n'est pas confirmée."
        )
    expected_confirmation = f"TELECODER {ecu.key.upper()} {snapshot['did_hex']}"
    _require_lab_preconditions(
        ecu.key,
        request.confirmation,
        expected_confirmation,
        vehicle_stationary=request.vehicle_stationary,
        ignition_on_engine_off=request.ignition_on_engine_off,
        stable_battery_voltage=request.stable_battery_voltage,
        workshop_or_private_site=request.workshop_or_private_site,
    )
    active_vin = _active_vin()
    if not snapshot.get("vin") or not active_vin or snapshot["vin"] != active_vin:
        raise PermissionError(
            "La sauvegarde doit appartenir au VIN actuellement sélectionné dans le Garage."
        )
    allowed_keys = {item["key_hex"].upper() for item in variant["security_keys"]}
    if request.application_key_hex.upper() not in allowed_keys:
        raise PermissionError("La clé application ne fait pas partie de la variante sélectionnée.")

    trace = SessionWriter()
    transport = build_transport(_trace_sink(trace), safety_profile="psa_lab")
    opened = False
    after_bytes: bytes | None = None
    execution_id = f"telecoding-execution-{_utc_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    report_path = _execution_path(active_vin, execution_id)
    try:
        transport.open()
        opened = True
        policy = lambda payload: authorize_psa_lab_uds(ecu.request_id, payload)
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=False,
            safety_policy=policy,
            flow_control_id=ecu.flow_control_id,
            flow_control_blocksize=ecu.flow_control_blocksize,
            tx_padding=ecu.isotp_tx_padding,
        ) as session:
            enter_extended_session(session)
            _unlock_security(session, request.application_key_hex.upper())
            _, current_bytes = read_data_by_identifier(session, snapshot["did"])
            if current_bytes.hex().upper() != preview.raw_before_hex:
                trace.write({
                    "type": "telecoding_stale_snapshot",
                    "snapshot_id": snapshot["snapshot_id"],
                    "expected_hex": preview.raw_before_hex,
                    "actual_hex": current_bytes.hex().upper(),
                })
                raise StaleTelecodingSnapshotError(
                    "Le calculateur a changé depuis la sauvegarde. Aucune écriture n'a été envoyée ; relis la zone."
                )
            requested_bytes = bytes.fromhex(preview.raw_after_hex)
            write_data_by_identifier(session, snapshot["did"], requested_bytes)
            _, after_bytes = read_data_by_identifier(session, snapshot["did"])
            try:
                session.request(bytes.fromhex("1001"))
            except Exception:
                pass

        verified = after_bytes.hex().upper() == preview.raw_after_hex
        message = (
            "Écriture confirmée octet par octet par une relecture dans la même session."
            if verified
            else "L'ECU a acquitté l'écriture, mais la relecture diffère du plan. N'enchaîne aucune autre opération."
        )
        result = TelecodingExecuteResult(
            execution_id=execution_id,
            snapshot_id=snapshot["snapshot_id"],
            ecu_key=ecu.key,
            variant_id=variant["id"],
            did=snapshot["did"],
            verified=verified,
            raw_before_hex=preview.raw_before_hex,
            raw_requested_hex=preview.raw_after_hex,
            raw_after_hex=after_bytes.hex().upper(),
            changes=preview.changes,
            message=message,
            session_id=trace.id,
            report_file=str(report_path.resolve()),
        )
        report = {
            "schema_version": 1,
            "executed_at": _iso_now(),
            "vin": active_vin,
            "plan_hash": preview.plan_hash,
            **result.model_dump(mode="json"),
            "fields_after": KnowledgeBase.decode_telecoding_fields(zone, after_bytes),
        }
        _atomic_json(report_path, report)
        trace.write({"type": "telecoding_execution_result", "payload": result.model_dump(mode="json")})
        _security_audit({
            "outcome": "verified" if verified else "verification_mismatch",
            "vin": active_vin,
            "ecu_key": ecu.key,
            "variant_id": variant["id"],
            "did_hex": snapshot["did_hex"],
            "snapshot_id": snapshot["snapshot_id"],
            "plan_hash": preview.plan_hash,
            "execution_id": execution_id,
            "session_id": trace.id,
        })
        return result
    except Exception as exc:
        _security_audit({
            "outcome": "rejected_or_failed",
            "vin": active_vin,
            "ecu_key": ecu.key,
            "variant_id": variant["id"],
            "did_hex": snapshot["did_hex"],
            "snapshot_id": snapshot["snapshot_id"],
            "plan_hash": preview.plan_hash,
            "execution_id": execution_id,
            "session_id": trace.id,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        raise
    finally:
        if opened:
            transport.close()
        trace.finish()
