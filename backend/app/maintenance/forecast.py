from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
import re
import unicodedata

from pydantic import BaseModel, Field

from app.diagnostic.maintenance_history import MaintenanceRecord


class MaintenanceForecastItem(BaseModel):
    id: str
    kind: str
    title: str
    mileage_km: int = Field(ge=0)
    due_date: date
    status: str
    estimated_cost_min: int | None = Field(default=None, ge=0)
    estimated_cost_max: int | None = Field(default=None, ge=0)
    source_label: str
    confidence: str
    record_id: str | None = None
    recommendation_index: int | None = None
    component_code: str | None = None
    sequence: int | None = None


class MaintenanceForecast(BaseModel):
    vin: str
    start_date: date
    start_date_estimated: bool
    current_date: date
    current_mileage_km: int
    horizon_mileage_km: int
    annual_mileage_km: int
    annual_mileage_source: str
    items: list[MaintenanceForecastItem]


@dataclass(frozen=True)
class RecurringRule:
    component_code: str
    title: str
    interval_km: int | None
    interval_months: int | None
    estimated_cost_min: int
    estimated_cost_max: int


RULES = (
    RecurringRule("engine.oil_service", "Vidange moteur et filtre à huile", 15_000, 12, 100, 190),
    RecurringRule("brakes.pads.rear", "Remplacement des plaquettes arrière", 60_000, None, 160, 300),
    RecurringRule("brakes.pads.front", "Remplacement des plaquettes avant", 60_000, None, 170, 320),
    RecurringRule("brakes.discs.front", "Remplacement des disques avant", 120_000, None, 320, 560),
    RecurringRule("brakes.fluid", "Remplacement du liquide de frein", None, 24, 70, 130),
    RecurringRule("engine.spark_plugs", "Remplacement des bougies d’allumage", 50_000, 48, 130, 260),
    RecurringRule("engine.air_filter", "Remplacement du filtre à air", 50_000, 48, 50, 110),
    RecurringRule("cabin.filter", "Remplacement du filtre d’habitacle", 50_000, 24, 45, 100),
    RecurringRule("engine.timing_belt", "Remplacement du kit de distribution", 200_000, 144, 750, 1_300),
)


def _plain(value: str | None) -> str:
    return " ".join(
        "".join(
            character
            for character in unicodedata.normalize("NFKD", value or "")
            if not unicodedata.combining(character)
        ).casefold().replace("/", " ").replace("-", " ").split()
    )


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _date_for_mileage(
    mileage_km: int,
    *,
    current_mileage_km: int,
    current_date: date,
    annual_mileage_km: int,
) -> date:
    distance = mileage_km - current_mileage_km
    return current_date + timedelta(days=round(distance / annual_mileage_km * 365.25))


def _mileage_for_date(
    value: date,
    *,
    current_mileage_km: int,
    current_date: date,
    annual_mileage_km: int,
) -> int:
    elapsed_days = (value - current_date).days
    return round(current_mileage_km + elapsed_days / 365.25 * annual_mileage_km)


def _annual_mileage(records: list[MaintenanceRecord]) -> tuple[int, str]:
    observations = sorted({
        (record.performed_at or record.purchased_at, record.mileage_km)
        for record in records
        if (record.performed_at or record.purchased_at) and record.mileage_km is not None
    })
    if len(observations) < 2:
        return 15_000, "Valeur par défaut modifiable"
    latest_date = observations[-1][0]
    assert latest_date is not None
    recent_limit = _add_months(latest_date, -36)
    recent = [value for value in observations if value[0] and value[0] >= recent_limit]
    selected = recent if len(recent) >= 2 else observations
    first_date, first_mileage = selected[0]
    last_date, last_mileage = selected[-1]
    assert first_date is not None and last_date is not None
    days = max(1, (last_date - first_date).days)
    estimate = round(((int(last_mileage) - int(first_mileage)) / days * 365.25) / 500) * 500
    if not 3_000 <= estimate <= 60_000:
        return 15_000, "Valeur par défaut modifiable"
    return estimate, "Estimé sur les 3 dernières années de l’historique"


def _record_signatures(record: MaintenanceRecord) -> set[str]:
    if record.record_status != "confirmed" or not record.performed_at:
        return set()
    plain_title = _plain(record.title)
    if "achat" in plain_title and not any(
        value in plain_title for value in ("remplac", "vidange", "pose", "monte")
    ):
        return set()
    action_text = " ".join([
        record.title,
        *(part.name for part in record.parts if part.usage in {"installed", "consumed"}),
        *(line.description for line in record.cost_lines if line.line_type in {"part", "product", "service", "labor"}),
    ])
    text = _plain(action_text)
    signatures: set[str] = set()
    rear = bool(re.search(r"\b(?:ar|arr|arriere|ard|arg)\b", text))
    front = bool(re.search(r"\b(?:av|avant|avd|avg)\b", text))
    if "plaquette" in text:
        signatures.add("brakes.pads.rear" if rear else "brakes.pads.front" if front else "brakes.pads")
    if "disque" in text and any(value in text for value in ("frein", "plaquette", "brakes")):
        signatures.add("brakes.discs.rear" if rear else "brakes.discs.front" if front else "brakes.discs")
    if "vidange" in text or "huile moteur" in text or "revision huile" in text:
        signatures.add("engine.oil_service")
    if "liquide de frein" in text and any(value in text for value in ("purge", "remplac", "vidange")):
        signatures.add("brakes.fluid")
    if "bougie" in text:
        signatures.add("engine.spark_plugs")
    if "filtre a air" in text or "element filtre air" in text:
        signatures.add("engine.air_filter")
    if "filtre habitacle" in text or "filtre a pollen" in text:
        signatures.add("cabin.filter")
    if "distribution" in text and any(value in text for value in ("kit", "courroie", "remplac")):
        signatures.add("engine.timing_belt")
    return signatures


def _recommendation_cost(title: str) -> tuple[int | None, int | None]:
    text = _plain(title)
    if "pneu" in text:
        return (280, 500) if any(value in text for value in ("arriere", "2 pneu")) else (300, 650)
    if "bras inferieur" in text or "silentbloc" in text:
        return 450, 900
    if "rotule" in text:
        return 250, 550
    if "brouillard" in text:
        return 30, 120
    if "voyant huile" in text:
        return 0, 120
    if "plaquette" in text:
        return 160, 320
    if "disque" in text and "frein" in text:
        return 320, 560
    return None, None


def _due_mileage(recommendation, current_mileage_km: int) -> int:
    if recommendation.due_mileage_km is not None:
        return max(0, recommendation.due_mileage_km)
    if recommendation.recommended_at_km is not None and recommendation.follow_up_after_km is not None:
        return recommendation.recommended_at_km + recommendation.follow_up_after_km
    return max(current_mileage_km, recommendation.recommended_at_km or 0)


def build_maintenance_forecast(
    vin: str,
    records: list[MaintenanceRecord],
    *,
    horizon_mileage_km: int = 500_000,
    annual_mileage_override: int | None = None,
) -> MaintenanceForecast:
    current_date = date.today()
    observed_annual, annual_source = _annual_mileage(records)
    annual_mileage = annual_mileage_override or observed_annual
    if not 1_000 <= annual_mileage <= 100_000:
        raise ValueError("Le kilométrage annuel doit être compris entre 1 000 et 100 000 km.")
    current_mileage = max((record.mileage_km or 0 for record in records), default=0)
    if horizon_mileage_km <= current_mileage or horizon_mileage_km > 1_000_000:
        raise ValueError("L’horizon doit être supérieur au kilométrage actuel et limité à 1 000 000 km.")
    annual_source = "Réglé manuellement" if annual_mileage_override else annual_source

    dated_observations = [
        (record.performed_at or record.purchased_at, record.mileage_km)
        for record in records
        if (record.performed_at or record.purchased_at) and record.mileage_km is not None
    ]
    if dated_observations:
        first_date, first_mileage = min(dated_observations)
        assert first_date is not None and first_mileage is not None
        start_date = first_date - timedelta(days=round(first_mileage / annual_mileage * 365.25))
        start_estimated = True
    else:
        start_date = date(min(record.performed_at.year for record in records if record.performed_at), 1, 1) if any(record.performed_at for record in records) else current_date
        start_estimated = True

    items: list[MaintenanceForecastItem] = []
    for record in records:
        event_date = record.performed_at or record.purchased_at
        if not event_date or record.mileage_km is None:
            continue
        items.append(MaintenanceForecastItem(
            id=f"history:{record.id}", kind="history", title=record.title,
            mileage_km=record.mileage_km, due_date=event_date, status="completed",
            estimated_cost_min=round(record.invoice_total) if record.invoice_total is not None else None,
            estimated_cost_max=round(record.invoice_total) if record.invoice_total is not None else None,
            source_label="Historique confirmé", confidence="confirmed", record_id=record.id,
        ))

    for record in records:
        for index, recommendation in enumerate(record.recommendations):
            if recommendation.status not in {"open", "monitoring"}:
                continue
            mileage = _due_mileage(recommendation, current_mileage)
            mileage = min(max(mileage, 0), horizon_mileage_km)
            projected_date = _date_for_mileage(
                max(mileage, current_mileage), current_mileage_km=current_mileage,
                current_date=current_date, annual_mileage_km=annual_mileage,
            )
            due_date = recommendation.due_date or projected_date
            if due_date < current_date or mileage <= current_mileage:
                due_date = current_date
            cost_min, cost_max = _recommendation_cost(recommendation.title)
            items.append(MaintenanceForecastItem(
                id=f"recommendation:{record.id}:{index}", kind="recommendation",
                title=recommendation.title, mileage_km=max(mileage, current_mileage),
                due_date=due_date, status="due" if mileage <= current_mileage or due_date <= current_date else "upcoming",
                estimated_cost_min=cost_min, estimated_cost_max=cost_max,
                source_label=f"Recommandation · {record.title}", confidence=recommendation.confidence,
                record_id=record.id, recommendation_index=index,
            ))

    latest_by_component: dict[str, MaintenanceRecord] = {}
    for record in sorted(records, key=lambda value: value.performed_at or date.min):
        for signature in _record_signatures(record):
            latest_by_component[signature] = record

    for rule in RULES:
        last_record = latest_by_component.get(rule.component_code)
        if not last_record or not last_record.performed_at:
            continue
        base_date = last_record.performed_at
        base_mileage = last_record.mileage_km
        if base_mileage is None:
            base_mileage = max(0, _mileage_for_date(
                base_date, current_mileage_km=current_mileage,
                current_date=current_date, annual_mileage_km=annual_mileage,
            ))
        sequence = 0
        while sequence < 40:
            sequence += 1
            date_from_interval = _add_months(base_date, rule.interval_months) if rule.interval_months else None
            mileage_due = (
                base_mileage + rule.interval_km
                if rule.interval_km
                else _mileage_for_date(
                    date_from_interval or base_date,
                    current_mileage_km=current_mileage,
                    current_date=current_date,
                    annual_mileage_km=annual_mileage,
                )
            )
            date_from_mileage = _date_for_mileage(
                mileage_due, current_mileage_km=current_mileage,
                current_date=current_date, annual_mileage_km=annual_mileage,
            )
            date_due = date_from_interval or date_from_mileage
            if rule.interval_km and rule.interval_months:
                date_due = min(date_due, date_from_mileage)
                mileage_due = min(mileage_due, _mileage_for_date(
                    date_due, current_mileage_km=current_mileage,
                    current_date=current_date, annual_mileage_km=annual_mileage,
                ))
            if date_due <= current_date or mileage_due <= current_mileage:
                date_due = current_date
                mileage_due = current_mileage
            if mileage_due > horizon_mileage_km:
                break
            items.append(MaintenanceForecastItem(
                id=f"scheduled:{rule.component_code}:{sequence}", kind="scheduled",
                title=rule.title, mileage_km=mileage_due, due_date=date_due,
                status="due" if mileage_due <= current_mileage or date_due <= current_date else "upcoming",
                estimated_cost_min=rule.estimated_cost_min,
                estimated_cost_max=rule.estimated_cost_max,
                source_label=f"Prévision depuis « {last_record.title} »",
                confidence="estimated", record_id=last_record.id,
                component_code=rule.component_code, sequence=sequence,
            ))
            base_mileage = mileage_due
            base_date = date_due

    items.sort(key=lambda item: (item.mileage_km, item.due_date, item.kind, item.title))
    return MaintenanceForecast(
        vin=vin, start_date=start_date, start_date_estimated=start_estimated,
        current_date=current_date, current_mileage_km=current_mileage,
        horizon_mileage_km=horizon_mileage_km, annual_mileage_km=annual_mileage,
        annual_mileage_source=annual_source, items=items,
    )
