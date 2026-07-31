from abc import ABC, abstractmethod
from collections.abc import Callable
from app.models import CanFrame


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
