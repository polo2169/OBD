from __future__ import annotations

from collections.abc import Iterable

from app.models import DtcReadResult, DtcSummary, EcuScanResult


TEST_FAILED = 0x01
TEST_FAILED_THIS_CYCLE = 0x02
PENDING = 0x04
CONFIRMED = 0x08
NOT_COMPLETED_SINCE_CLEAR = 0x10
FAILED_SINCE_CLEAR = 0x20
NOT_COMPLETED_THIS_CYCLE = 0x40
WARNING_REQUESTED = 0x80


def classify_dtc_status(status: int) -> dict[str, str | bool]:
    """Turn ISO 14229 DTC status bits into a user-facing state.

    The raw status remains authoritative. This classification deliberately
    avoids treating ``testNotCompleted`` bits as faults, which is essential on
    PSA ECUs that expose large capability lists through service 0x19.
    """
    current_failure = bool(status & (TEST_FAILED | TEST_FAILED_THIS_CYCLE | PENDING | WARNING_REQUESTED))
    historical_failure = bool(status & (CONFIRMED | FAILED_SINCE_CLEAR))
    not_completed = bool(status & (NOT_COMPLETED_SINCE_CLEAR | NOT_COMPLETED_THIS_CYCLE))

    if current_failure:
        return {
            "state": "active",
            "state_label": "Actif / à contrôler",
            "state_detail": "Au moins un indicateur d'échec, d'attente ou de voyant est actif.",
            "actionable": True,
        }
    if historical_failure:
        return {
            "state": "historical",
            "state_label": "Historique",
            "state_detail": "Le défaut a échoué ou a été confirmé depuis le dernier effacement, sans échec actuel.",
            "actionable": False,
        }
    if not_completed:
        return {
            "state": "not_tested",
            "state_label": "Test non exécuté",
            "state_detail": "Le calculateur décrit un moniteur qui n'a pas encore terminé son test ; ce n'est pas une panne active.",
            "actionable": False,
        }
    return {
        "state": "inactive",
        "state_label": "Inactif",
        "state_detail": "Aucun indicateur d'échec actif ou historique n'est positionné.",
        "actionable": False,
    }


def apply_dtc_classification(dtc: DtcReadResult) -> DtcReadResult:
    return dtc.model_copy(update=classify_dtc_status(dtc.status))


def summarize_dtcs(ecus: Iterable[EcuScanResult]) -> DtcSummary:
    counts = {"active": 0, "historical": 0, "not_tested": 0, "inactive": 0}
    affected_ecus: set[str] = set()
    total = 0
    for ecu in ecus:
        for dtc in ecu.dtcs:
            total += 1
            counts[dtc.state] += 1
            if dtc.state in {"active", "historical"}:
                affected_ecus.add(ecu.key)
    return DtcSummary(
        **counts,
        total=total,
        affected_ecus=len(affected_ecus),
    )
