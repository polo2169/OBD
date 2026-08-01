from __future__ import annotations

from collections.abc import Callable, Iterable
import queue
import threading

from app.models import CanFrame
from app.safety import TxSafetyProfile
from app.transports.base import Transport


PhysicalFactory = Callable[[], Transport]


class SharedGatewayClient(Transport):
    """One logical consumer of a single physical ESP32 connection."""

    def __init__(
        self,
        hub: SharedGatewayHub,
        receive_buses: Iterable[str] | None,
        safety_profile: TxSafetyProfile,
        queue_size: int,
        require_diagnostic_can: bool = True,
    ) -> None:
        self._hub = hub
        self._receive_buses = frozenset(receive_buses) if receive_buses is not None else None
        self.safety_profile = safety_profile
        self.require_diagnostic_can = require_diagnostic_can
        self._frames: queue.Queue[CanFrame] = queue.Queue(maxsize=queue_size)
        self._opened = False
        self.queue_overflow_count = 0

    @property
    def name(self) -> str:
        return self._hub.name

    @property
    def hello(self) -> dict | None:
        return self._hub.hello

    @property
    def last_stats(self) -> dict | None:
        return self._hub.last_stats

    def open(self) -> None:
        if self._opened:
            return
        self._hub.attach(self)
        self._opened = True

    def close(self) -> None:
        if not self._opened:
            return
        self._opened = False
        self._hub.detach(self)
        self._clear_frames()

    def receive(self, timeout: float = 0.1) -> CanFrame | None:
        if not self._opened:
            raise RuntimeError("Transport partagé fermé.")
        try:
            return self._frames.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return None

    def send(self, frame: CanFrame) -> None:
        if not self._opened:
            raise RuntimeError("Transport partagé fermé.")
        self._hub.send(self, frame)

    def accepts(self, frame: CanFrame) -> bool:
        return self._receive_buses is None or frame.bus in self._receive_buses

    def deliver(self, frame: CanFrame) -> None:
        if not self.accepts(frame):
            return
        try:
            self._frames.put_nowait(frame)
            return
        except queue.Full:
            pass

        # Never block the physical reader: discard the oldest item for this
        # slow consumer while leaving all other dashboard/diagnostic clients intact.
        try:
            self._frames.get_nowait()
        except queue.Empty:
            pass
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            pass
        self.queue_overflow_count += 1
        self.debug(
            "shared_transport_queue_overflow",
            transport=self.name,
            dropped=self.queue_overflow_count,
            buses=sorted(self._receive_buses) if self._receive_buses is not None else "all",
        )

    def _clear_frames(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return


class SharedGatewayHub:
    """Multiplex one serial/TCP gateway between live capture and diagnostics."""

    def __init__(self, physical_factory: PhysicalFactory, name: str) -> None:
        self._physical_factory = physical_factory
        self._name = name
        self._physical: Transport | None = None
        self._clients: set[SharedGatewayClient] = set()
        self._clients_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._reader_error: Exception | None = None

    @property
    def name(self) -> str:
        physical = self._physical
        return physical.name if physical is not None else self._name

    @property
    def hello(self) -> dict | None:
        physical = self._physical
        hello = getattr(physical, "hello", None) if physical is not None else None
        return hello if isinstance(hello, dict) else None

    @property
    def last_stats(self) -> dict | None:
        physical = self._physical
        stats = getattr(physical, "last_stats", None) if physical is not None else None
        return stats if isinstance(stats, dict) else None

    def client(
        self,
        receive_buses: Iterable[str] | None,
        safety_profile: TxSafetyProfile,
        queue_size: int,
        require_diagnostic_can: bool = True,
    ) -> SharedGatewayClient:
        return SharedGatewayClient(
            self,
            receive_buses,
            safety_profile,
            queue_size,
            require_diagnostic_can,
        )

    def attach(self, client: SharedGatewayClient) -> None:
        with self._lifecycle_lock:
            created_physical = False
            if self._physical is None:
                physical = self._physical_factory()
                physical.set_debug_sink(self._broadcast_debug)
                try:
                    physical.open()
                except Exception:
                    physical.close()
                    raise
                self._physical = physical
                created_physical = True
                self._reader_error = None
                self._stop.clear()
            try:
                self._validate_client(client)
            except Exception:
                if created_physical and self._physical is not None:
                    self._physical.close()
                    self._physical = None
                raise
            with self._clients_lock:
                self._clients.add(client)
            if self._reader is None or not self._reader.is_alive():
                self._reader = threading.Thread(
                    target=self._read_loop,
                    name="opendiag-shared-esp32",
                    daemon=True,
                )
                self._reader.start()
        client.debug(
            "shared_transport_attached",
            transport=self.name,
            hello=self.hello,
        )

    def detach(self, client: SharedGatewayClient) -> None:
        with self._clients_lock:
            self._clients.discard(client)
            has_clients = bool(self._clients)
        if has_clients:
            return

        with self._lifecycle_lock:
            with self._clients_lock:
                if self._clients:
                    return
            self._stop.set()
            reader = self._reader
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=1.0)
            self._reader = None
            physical = self._physical
            self._physical = None
            if physical is not None:
                physical.close()

    def send(self, client: SharedGatewayClient, frame: CanFrame) -> None:
        physical = self._physical
        if physical is None:
            raise RuntimeError("Passerelle ESP32 partagée fermée.")
        if self._reader_error is not None:
            raise RuntimeError(f"Lecture de la passerelle interrompue : {self._reader_error}")
        with self._send_lock:
            previous_profile = getattr(physical, "safety_profile", None)
            if previous_profile is not None:
                physical.safety_profile = client.safety_profile
            try:
                physical.send(frame)
            finally:
                if previous_profile is not None:
                    physical.safety_profile = previous_profile

    def _read_loop(self) -> None:
        physical = self._physical
        if physical is None:
            return
        try:
            while not self._stop.is_set():
                frame = physical.receive(timeout=0.05)
                if frame is None:
                    continue
                with self._clients_lock:
                    clients = tuple(self._clients)
                for client in clients:
                    client.deliver(frame)
        except Exception as exc:
            self._reader_error = exc
            self._broadcast_debug({
                "type": "shared_transport_reader_error",
                "transport": self.name,
                "error": str(exc),
            })

    def _broadcast_debug(self, event: dict) -> None:
        if (
            event.get("type") == "gateway_message"
            and isinstance(event.get("message"), dict)
            and event["message"].get("type") == "can_rx"
        ):
            # Each consumer receives the decoded CanFrame through its own bus
            # queue; duplicating every high-rate frame in debug traces wastes IO.
            return
        with self._clients_lock:
            clients = tuple(self._clients)
        for client in clients:
            client.debug(str(event.get("type", "gateway_event")), **{
                key: value for key, value in event.items() if key != "type"
            })

    def _validate_client(self, client: SharedGatewayClient) -> None:
        hello = self.hello or {}
        if (
            client.require_diagnostic_can
            and hello.get("dual_can") is True
            and hello.get("diagnostic_can_ready") is not True
        ):
            raise RuntimeError(
                "Le bus CAN diagnostic 3/8 n'est pas initialisé sur le MCP2515."
            )
        if client.safety_profile == "psa_lab" and hello.get("psa_lab") is not True:
            raise RuntimeError(
                "Le firmware ESP32 partagé n'annonce pas la capacité PSA lab."
            )


_registry_lock = threading.Lock()
_hubs: dict[tuple, SharedGatewayHub] = {}


def shared_gateway_client(
    key: tuple,
    physical_factory: PhysicalFactory,
    name: str,
    receive_buses: Iterable[str] | None,
    safety_profile: TxSafetyProfile,
    queue_size: int = 16_384,
    require_diagnostic_can: bool = True,
) -> SharedGatewayClient:
    with _registry_lock:
        hub = _hubs.get(key)
        if hub is None:
            hub = SharedGatewayHub(physical_factory, name)
            _hubs[key] = hub
    client = hub.client(
        receive_buses,
        safety_profile,
        queue_size,
        require_diagnostic_can,
    )
    return client
