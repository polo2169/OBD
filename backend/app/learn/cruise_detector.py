from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import pstdev


@dataclass(frozen=True)
class CruiseDetection:
    probable: bool
    confidence: float
    state: str
    reason: str


class CruiseDetector:
    """
    Détection comportementale expérimentale du régulateur.

    Ce résultat ne remplace pas le futur décodage direct du signal CAN.
    """

    def __init__(
        self,
        sample_period_ms: int = 100,
        window_seconds: float = 3.0,
    ) -> None:
        window_size = max(
            5,
            round(window_seconds * 1000 / sample_period_ms),
        )

        self._speeds: deque[float] = deque(maxlen=window_size)
        self._positive_samples = 0
        self._negative_samples = 0
        self._active = False

    def reset(self) -> None:
        self._speeds.clear()
        self._positive_samples = 0
        self._negative_samples = 0
        self._active = False

    def update(
        self,
        *,
        speed_kph: float | None,
        accelerator_d_pct: float | None,
        accelerator_e_pct: float | None,
        engine_load_pct: float | None,
        throttle_pct: float | None,
        brake_active: bool | None,
    ) -> CruiseDetection:
        if (
            speed_kph is None
            or accelerator_d_pct is None
            or accelerator_e_pct is None
        ):
            return CruiseDetection(
                probable=False,
                confidence=0.0,
                state="unavailable",
                reason="Signaux requis indisponibles",
            )

        speed = float(speed_kph)
        pedal_d = float(accelerator_d_pct)
        pedal_e = float(accelerator_e_pct)

        self._speeds.append(speed)

        # Valeurs de repos observées sur cette Peugeot 308 :
        # voie D ≈ 7,84 %, voie E ≈ 7,45 %.
        pedal_released = pedal_d <= 2.0 and pedal_e <= 2.0
        pedal_coherent = abs(pedal_d - pedal_e) <= 2.0

        enough_history = len(self._speeds) == self._speeds.maxlen

        if enough_history:
            speed_std = pstdev(self._speeds)
            speed_range = max(self._speeds) - min(self._speeds)
        else:
            speed_std = float("inf")
            speed_range = float("inf")

        speed_stable = (
            enough_history
            and speed_std <= 1.8
            and speed_range <= 5.0
        )

        load = (
            float(engine_load_pct)
            if engine_load_pct is not None
            else 0.0
        )

        throttle = (
            float(throttle_pct)
            if throttle_pct is not None
            else 0.0
        )

        engine_driving = load >= 12.0 or throttle >= 18.0

        candidate = (
            speed >= 35.0
            and pedal_released
            and pedal_coherent
            and speed_stable
            and engine_driving
            and not bool(brake_active)
        )

        if candidate:
            self._positive_samples += 1
            self._negative_samples = 0
        else:
            self._negative_samples += 1
            self._positive_samples = 0

        # 10 échantillons à 100 ms = environ une seconde.
        if self._positive_samples >= 10:
            self._active = True

        # Coupure immédiate au freinage.
        if bool(brake_active) or self._negative_samples >= 20:
            self._active = False

        confidence = 0.0

        if pedal_released:
            confidence += 0.25
        if speed_stable:
            confidence += 0.35
        if engine_driving:
            confidence += 0.25
        if speed >= 35.0:
            confidence += 0.10
        if pedal_coherent:
            confidence += 0.05

        if bool(brake_active):
            confidence = 0.0

        if bool(brake_active):
            state = "braking"
            reason = "Frein actif"
        elif self._active:
            state = "probable_active"
            reason = (
                "Pédale relâchée, vitesse stable et moteur en charge"
            )
        elif not pedal_released:
            state = "driver_accelerating"
            reason = "Conducteur sur l’accélérateur"
        elif speed >= 35.0 and not speed_stable:
            state = "coasting"
            reason = "Pédale relâchée mais vitesse non stable"
        else:
            state = "inactive"
            reason = "Conditions insuffisantes"

        return CruiseDetection(
            probable=self._active,
            confidence=round(min(confidence, 1.0), 2),
            state=state,
            reason=reason,
        )
