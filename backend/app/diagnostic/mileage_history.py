from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
import mmap
import re

from pydantic import BaseModel, Field

from app.config import settings
from app.diagnostic.history import vehicle_storage_dir
from app.diagnostic.maintenance_history import list_maintenance_records
from app.diagnostic.oil_log import list_oil_log


_ODOMETER_KEY = b'"odometer_km"'
_MAX_INTERPOLATION_DAYS = 365
_MAX_NEAREST_DAYS = 45


class MileageObservation(BaseModel):
    observed_at: datetime
    mileage_km: int = Field(ge=0, le=9_999_999)
    source: Literal["can_session", "maintenance", "invoice", "oil_log"]
    label: str


class MileageEstimate(BaseModel):
    vin: str
    requested_date: date
    mileage_km: int | None = Field(default=None, ge=0, le=9_999_999)
    method: Literal[
        "exact_date",
        "interpolated",
        "nearest_before",
        "nearest_after",
        "unavailable",
    ]
    confidence: Literal["high", "medium", "low", "unavailable"]
    is_estimate: bool
    message: str
    observations: list[MileageObservation] = Field(default_factory=list)


def _session_root() -> Path:
    path = settings.session_dir
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


def _number_after(mapped: mmap.mmap, position: int) -> float | None:
    sample = mapped[position + len(_ODOMETER_KEY): position + len(_ODOMETER_KEY) + 48]
    match = re.match(rb"\s*:\s*(-?\d+(?:\.\d+)?)", sample)
    return float(match.group(1)) if match else None


def _first_odometer(mapped: mmap.mmap) -> float | None:
    position = mapped.find(_ODOMETER_KEY)
    while position >= 0:
        value = _number_after(mapped, position)
        if value is not None:
            return value
        position = mapped.find(_ODOMETER_KEY, position + len(_ODOMETER_KEY))
    return None


def _last_odometer(mapped: mmap.mmap) -> float | None:
    position = mapped.rfind(_ODOMETER_KEY)
    while position >= 0:
        value = _number_after(mapped, position)
        if value is not None:
            return value
        position = mapped.rfind(_ODOMETER_KEY, 0, position)
    return None


def _cached_session_observations(vin: str) -> list[MileageObservation]:
    observations: list[MileageObservation] = []
    directory = _session_root()
    if not directory.exists():
        return observations
    for path in directory.glob("learn-*.replay.json"):
        try:
            with path.open("rb") as stream:
                with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                    header = mapped[: min(len(mapped), 512 * 1024)]
                    cached_vin = re.search(rb'"vin"\s*:\s*"([A-HJ-NPR-Z0-9]{17})"', header)
                    start = re.search(rb'"start_timestamp_us"\s*:\s*(\d+)', header)
                    duration = re.search(rb'"duration_ms"\s*:\s*(\d+)', header)
                    if not cached_vin or cached_vin.group(1).decode("ascii") != vin or not start:
                        continue
                    started_at = datetime.fromtimestamp(int(start.group(1)) / 1_000_000, timezone.utc)
                    duration_ms = int(duration.group(1)) if duration else 0
                    first = _first_odometer(mapped)
                    last = _last_odometer(mapped)
                    if first is not None and 0 <= first <= 9_999_999:
                        observations.append(MileageObservation(
                            observed_at=started_at,
                            mileage_km=round(first),
                            source="can_session",
                            label=f"Capture CAN {path.stem.removesuffix('.replay')}",
                        ))
                    if last is not None and 0 <= last <= 9_999_999 and (last != first or duration_ms > 0):
                        observations.append(MileageObservation(
                            observed_at=started_at + timedelta(milliseconds=duration_ms),
                            mileage_km=round(last),
                            source="can_session",
                            label=f"Fin de capture CAN {path.stem.removesuffix('.replay')}",
                        ))
        except (OSError, ValueError, OverflowError):
            continue
    return observations


def mileage_observations(vin: str) -> list[MileageObservation]:
    vehicle_storage_dir(vin)
    observations = _cached_session_observations(vin)
    for record in list_maintenance_records(vin):
        if record.mileage_km is None or record.performed_at is None:
            continue
        source: Literal["maintenance", "invoice"] = (
            "invoice" if record.mileage_source == "invoice" else "maintenance"
        )
        observations.append(MileageObservation(
            observed_at=datetime.combine(record.performed_at, time(hour=12), timezone.utc),
            mileage_km=record.mileage_km,
            source=source,
            label=record.title,
        ))
    for entry in list_oil_log(vin=vin):
        observations.append(MileageObservation(
            observed_at=entry.recorded_at,
            mileage_km=round(entry.mileage_km),
            source="oil_log",
            label="Relevé kilométrage / huile",
        ))
    observations.sort(key=lambda item: item.observed_at)
    return observations


def estimate_mileage(vin: str, requested_date: date) -> MileageEstimate:
    points = mileage_observations(vin)
    target = datetime.combine(requested_date, time(hour=12), timezone.utc)
    same_day = [point for point in points if point.observed_at.date() == requested_date]
    if same_day:
        selected = min(same_day, key=lambda point: abs((point.observed_at - target).total_seconds()))
        return MileageEstimate(
            vin=vin,
            requested_date=requested_date,
            mileage_km=selected.mileage_km,
            method="exact_date",
            confidence="high",
            is_estimate=False,
            message=f"Relevé {selected.source.replace('_', ' ')} trouvé à cette date.",
            observations=[selected],
        )

    before = max((point for point in points if point.observed_at < target), default=None, key=lambda item: item.observed_at)
    after = min((point for point in points if point.observed_at > target), default=None, key=lambda item: item.observed_at)
    if before and after:
        span_seconds = (after.observed_at - before.observed_at).total_seconds()
        span_days = span_seconds / 86_400
        distance = after.mileage_km - before.mileage_km
        plausible_daily_distance = distance / span_days if span_days > 0 else -1
        if (
            0 < span_seconds
            and span_days <= _MAX_INTERPOLATION_DAYS
            and distance >= 0
            and plausible_daily_distance <= 1_500
        ):
            ratio = (target - before.observed_at).total_seconds() / span_seconds
            mileage = round(before.mileage_km + ratio * distance)
            confidence = "high" if span_days <= 30 else "medium" if span_days <= 90 else "low"
            return MileageEstimate(
                vin=vin,
                requested_date=requested_date,
                mileage_km=mileage,
                method="interpolated",
                confidence=confidence,
                is_estimate=True,
                message=(
                    f"Estimation entre {before.mileage_km:,} km le {before.observed_at:%d/%m/%Y} "
                    f"et {after.mileage_km:,} km le {after.observed_at:%d/%m/%Y}."
                ).replace(",", " "),
                observations=[before, after],
            )

    nearest_candidates = [point for point in (before, after) if point is not None]
    if nearest_candidates:
        nearest = min(nearest_candidates, key=lambda point: abs((point.observed_at - target).total_seconds()))
        age_days = abs((nearest.observed_at - target).total_seconds()) / 86_400
        if age_days <= _MAX_NEAREST_DAYS:
            is_before = nearest.observed_at < target
            return MileageEstimate(
                vin=vin,
                requested_date=requested_date,
                mileage_km=nearest.mileage_km,
                method="nearest_before" if is_before else "nearest_after",
                confidence="low",
                is_estimate=True,
                message=(
                    f"Faute de deux relevés encadrants, valeur la plus proche : "
                    f"{nearest.mileage_km:,} km le {nearest.observed_at:%d/%m/%Y}. À confirmer."
                ).replace(",", " "),
                observations=[nearest],
            )

    return MileageEstimate(
        vin=vin,
        requested_date=requested_date,
        method="unavailable",
        confidence="unavailable",
        is_estimate=True,
        message="Pas assez de relevés kilométriques proches pour proposer une valeur fiable.",
    )
