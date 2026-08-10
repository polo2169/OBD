from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, Iterator

from app.models import CanFrame
from app.safety import TxSafetyProfile


def validate_gateway_tx_policy(
    hello: dict[str, Any],
    *,
    tx_enabled: bool,
    safety_profile: TxSafetyProfile,
    require_diagnostic_can: bool,
) -> None:
    """Reject gateways whose firmware can transmit outside an allowlist.

    This check is deliberately enforced even for a receive-only backend. A raw
    active firmware remains reachable through USB/Wi-Fi by another client and
    must not be treated as a verified OpenDiag gateway.
    """
    readonly = bool(hello.get("readonly", True))
    diagnostic_read_only = hello.get("diagnostic_read_only") is True
    psa_lab = hello.get("psa_lab") is True
    live_obd_read_only = hello.get("live_obd_read_only") is True
    announced_policy = str(hello.get("tx_policy") or "").strip().lower()

    if announced_policy == "unrestricted" or not (
        readonly or diagnostic_read_only or psa_lab or live_obd_read_only
    ):
        raise RuntimeError(
            "Le firmware ESP32 autorise une émission CAN non filtrée et "
            "n'annonce pas le verrou diagnostic lecture seule. "
            "OpenDiag refuse les profils TX génériques ; flashez un profil "
            "passif, diagnostic_read_only ou psa_lab avec allowlist."
        )

    if not tx_enabled:
        return
    if readonly:
        raise RuntimeError(
            "CAN_TX_ENABLED=true mais le firmware ESP32 est compilé en écoute seule."
        )
    if (
        require_diagnostic_can
        and hello.get("dual_can") is True
        and hello.get("diagnostic_can_ready") is not True
    ):
        raise RuntimeError(
            "Le bus CAN diagnostic 3/8 n'est pas initialisé sur la passerelle."
        )
    if safety_profile == "psa_lab" and not psa_lab:
        raise RuntimeError(
            "Le firmware ESP32 n'annonce pas la capacité PSA lab avec allowlist."
        )
    if (
        require_diagnostic_can
        and safety_profile == "diagnostic_read_only"
        and not diagnostic_read_only
        and not psa_lab
    ):
        raise RuntimeError(
            "Le firmware ESP32 n'annonce pas le verrou diagnostic lecture seule "
            "ni le profil PSA lab compatible."
        )


class Transport(ABC):
    _debug_sink: Callable[[dict], None] | None = None

    def set_debug_sink(self, sink: Callable[[dict], None] | None) -> None:
        self._debug_sink = sink

    def debug(self, event_type: str, **details) -> None:
        if self._debug_sink is None:
            return
        try:
            self._debug_sink({"type": event_type, **details})
        except Exception:
            # La journalisation ne doit jamais interrompre un échange diagnostic.
            pass

    @contextmanager
    def diagnostic_transaction(self) -> Iterator[None]:
        """Reserve the diagnostic request/response channel for one ISO-TP session.

        Dedicated transports do not need additional arbitration. Shared gateways
        override this hook so two clients cannot consume each other's replies.
        """
        yield

    @abstractmethod
    def open(self) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def receive(self, timeout: float = 0.1) -> CanFrame | None:
        ...

    @abstractmethod
    def send(self, frame: CanFrame) -> None:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
