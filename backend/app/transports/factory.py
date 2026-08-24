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


def _profile_can_bitrate(vehicle_profile: str | None) -> int | None:
    """Return the CAN bitrate associated with the selected vehicle profile."""
    vehicle = KnowledgeBase().vehicle(vehicle_profile)
    diagnostic_network = vehicle.get("networks", {}).get("diagnostic_can", {})
    raw_bitrate = diagnostic_network.get("bitrate")
    if raw_bitrate is None:
        return None
    bitrate = int(str(raw_bitrate), 0)
    if bitrate not in {250_000, 500_000}:
        raise ValueError(
            f"Débit CAN non pris en charge par la passerelle ESP32 : {bitrate} bit/s."
        )
    return bitrate


def build_transport(
    debug_sink: Callable[[dict], None] | None = None,
    safety_profile: TxSafetyProfile = "diagnostic_read_only",
    receive_buses: Iterable[str] | None = ("default", "diagnostic"),
    require_diagnostic_can: bool = True,
    vehicle_profile: str | None = None,
) -> Transport:
    profile_can_bitrate = _profile_can_bitrate(vehicle_profile)
    if settings.transport == "virtual":
        knowledge = KnowledgeBase()
        vehicle = knowledge.vehicle(vehicle_profile)
        response_ids = {
            ecu.request_id: ecu.response_id
            for ecu in knowledge.ecus(vehicle_profile)
            if ecu.request_id is not None and ecu.response_id is not None
        }
        diagnostic = knowledge.vehicle(vehicle_profile).get("diagnostic", {})
        obd_request_id = diagnostic.get("obd_request_id")
        obd_response_id = diagnostic.get("obd_response_id")
        flow_control_ids: dict[int, int] = {}
        if obd_request_id is not None and obd_response_id is not None:
            request_id = int(str(obd_request_id), 0)
            response_ids[request_id] = int(str(obd_response_id), 0)
            if diagnostic.get("obd_flow_control_id") is not None:
                flow_control_ids[request_id] = int(str(diagnostic["obd_flow_control_id"]), 0)
        transport = VirtualVehicleTransport(
            read_only=settings.read_only,
            maintenance=settings.dtc_clear_enabled,
            response_ids=response_ids,
            flow_control_ids=flow_control_ids,
            safety_profile=safety_profile,
            simulated_vin={
                "Peugeot": "VF3LJHNYWJS123456",
                "Fiat": "ZFA31200001234567",
                "Renault": "VF1FLAHA6BY123456",
            }.get(str(vehicle.get("manufacturer"))),
        )
    elif settings.transport == "esp32_serial":
        key = (
            "esp32_serial",
            settings.serial_port,
            settings.serial_baud,
            settings.can_tx_enabled,
            settings.esp32_handshake_timeout,
            profile_can_bitrate,
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
                target_live_bitrate=profile_can_bitrate,
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
            profile_can_bitrate,
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
                target_live_bitrate=profile_can_bitrate,
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
