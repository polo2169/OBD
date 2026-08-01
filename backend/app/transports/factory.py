from collections.abc import Callable
from collections.abc import Iterable

from app.config import settings
from app.database import KnowledgeBase
from app.transports.base import Transport
from app.transports.serial_gateway import Esp32SerialTransport
from app.transports.socketcan import SocketCanTransport
from app.transports.virtual import VirtualVehicleTransport
from app.transports.wifi_gateway import Esp32WifiTransport
from app.transports.shared_gateway import shared_gateway_client
from app.safety import TxSafetyProfile


def build_transport(
    debug_sink: Callable[[dict], None] | None = None,
    safety_profile: TxSafetyProfile = "diagnostic_read_only",
    receive_buses: Iterable[str] | None = ("default", "diagnostic"),
    require_diagnostic_can: bool = True,
) -> Transport:
    if settings.transport == "virtual":
        response_ids = {
            ecu.request_id: ecu.response_id
            for ecu in KnowledgeBase().ecus()
            if ecu.request_id is not None and ecu.response_id is not None
        }
        transport = VirtualVehicleTransport(
            read_only=settings.read_only,
            maintenance=settings.dtc_clear_enabled,
            response_ids=response_ids,
            safety_profile=safety_profile,
        )
    elif settings.transport == "esp32_serial":
        key = (
            "esp32_serial",
            settings.serial_port,
            settings.serial_baud,
            settings.can_tx_enabled,
            settings.esp32_handshake_timeout,
        )
        transport = shared_gateway_client(
            key,
            lambda: Esp32SerialTransport(
                settings.serial_port,
                settings.serial_baud,
                tx_enabled=settings.can_tx_enabled,
                handshake_timeout=settings.esp32_handshake_timeout,
                safety_profile="diagnostic_read_only",
                require_diagnostic_can=False,
            ),
            f"esp32:{settings.serial_port}",
            receive_buses,
            safety_profile,
            require_diagnostic_can=require_diagnostic_can,
        )
    elif settings.transport == "esp32_wifi":
        key = (
            "esp32_wifi",
            settings.esp32_wifi_host,
            settings.esp32_wifi_port,
            settings.can_tx_enabled,
            settings.esp32_handshake_timeout,
            settings.esp32_wifi_reconnect_interval,
        )
        transport = shared_gateway_client(
            key,
            lambda: Esp32WifiTransport(
                settings.esp32_wifi_host,
                settings.esp32_wifi_port,
                tx_enabled=settings.can_tx_enabled,
                handshake_timeout=settings.esp32_handshake_timeout,
                reconnect_interval=settings.esp32_wifi_reconnect_interval,
                safety_profile="diagnostic_read_only",
                require_diagnostic_can=False,
            ),
            f"esp32_wifi:{settings.esp32_wifi_host}:{settings.esp32_wifi_port}",
            receive_buses,
            safety_profile,
            require_diagnostic_can=require_diagnostic_can,
        )
    elif settings.transport == "socketcan":
        transport = SocketCanTransport(
            settings.can_channel,
            settings.can_interface,
            tx_enabled=settings.can_tx_enabled,
            safety_profile=safety_profile,
        )
    else:
        raise ValueError(f"Transport inconnu : {settings.transport}")

    transport.set_debug_sink(debug_sink)
    return transport
