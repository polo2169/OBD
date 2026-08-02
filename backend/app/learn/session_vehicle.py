from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re

from app.config import settings
from app.learn.models import SessionVehicleAssignment


_SESSION_ID = re.compile(r"^learn-[A-Za-z0-9TZ-]+$")


def _session_path(session_id: str) -> Path:
    if not _SESSION_ID.fullmatch(session_id):
        raise FileNotFoundError(f"Identifiant de session invalide : {session_id}")
    path = settings.session_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Session introuvable : {session_id}")
    return path


def assignment_path(session_id: str) -> Path:
    return _session_path(session_id).with_suffix(".vehicle.json")


def load_session_vehicle(session_id: str) -> dict:
    try:
        payload = json.loads(assignment_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError):
        return {}
    return payload if isinstance(payload, dict) else {}


def session_vehicle_mtime_ns(session_id: str) -> int | None:
    try:
        return assignment_path(session_id).stat().st_mtime_ns
    except (OSError, FileNotFoundError):
        return None


def assign_session_vehicle(session_id: str, assignment: SessionVehicleAssignment) -> dict:
    path = assignment_path(session_id)
    payload = {
        **assignment.model_dump(mode="json"),
        "session_id": session_id,
        "assigned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return payload
