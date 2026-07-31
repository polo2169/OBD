from pathlib import Path
import yaml

from app.config import settings
from app.learn.analyzer import analyze_session


def export_proposals(session_id: str) -> Path:
    report = analyze_session(session_id)
    out_dir = settings.database_dir / "psa" / "proposals"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{session_id}.yaml"

    payload = {
        "session_id": session_id,
        "status": "experimental",
        "validation_required": True,
        "warnings": report.warnings,
        "candidates": [
            {
                "request_id": f"0x{candidate.request_id:X}",
                "response_id": f"0x{candidate.response_id:X}",
                "service": f"0x{candidate.service:02X}",
                "request_payload": candidate.request_payload_hex,
                "response_payload": candidate.response_payload_hex,
                "occurrences": candidate.occurrences,
                "confidence": round(candidate.confidence, 3),
                "access": candidate.access,
                "rationale": candidate.rationale,
                "verified_on": [],
                "source": "community_capture",
            }
            for candidate in report.candidates
        ],
    }

    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path
