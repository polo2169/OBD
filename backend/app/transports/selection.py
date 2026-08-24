from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import json

from serial.tools import list_ports

from app.config import settings
from app.transports.factory import build_transport


_connection_lock = Lock()
_last_probe: dict[str, Any] = {
    "verified": False,
    "transport": None,
    "endpoint": None,
    "verified_at": None,
    "hello": None,
    "error": None,
}


def _serial_label(device: str, description: str | None) -> str:
    short_name = Path(device).name
    detail = description if description and description.lower() != "n/a" else "Port série USB"
    return f"ESP32 USB · {detail} · {short_name}"


def available_transport_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen_devices: set[str] = set()
    for port in list_ports.comports():
        description = str(port.description or "")
        looks_like_usb = (
            port.vid is not None
            or "usb" in port.device.lower()
            or "usb" in description.lower()
            or "cp210" in description.lower()
        )
        if not looks_like_usb:
            continue
        seen_devices.add(port.device)
        options.append({
            "id": f"serial:{port.device}",
            "transport": "esp32_serial",
            "endpoint": port.device,
            "label": _serial_label(port.device, description),
            "detected": True,
            "baud": settings.serial_baud,
            "vid": port.vid,
            "pid": port.pid,
        })

    if settings.serial_port and settings.serial_port not in seen_devices:
        options.append({
            "id": f"serial:{settings.serial_port}",
            "transport": "esp32_serial",
            "endpoint": settings.serial_port,
            "label": f"ESP32 USB configuré · {Path(settings.serial_port).name}",
            "detected": False,
            "baud": settings.serial_baud,
            "vid": None,
            "pid": None,
        })

    wifi_endpoint = f"{settings.esp32_wifi_host}:{settings.esp32_wifi_port}"
    options.append({
        "id": f"wifi:{wifi_endpoint}",
        "transport": "esp32_wifi",
        "endpoint": wifi_endpoint,
        "label": f"ESP32 Wi-Fi privé · {wifi_endpoint}",
        "detected": None,
        "baud": None,
        "vid": None,
        "pid": None,
    })
    return options


def connection_probe_status() -> dict[str, Any]:
    with _connection_lock:
        endpoint = (
            f"{settings.esp32_wifi_host}:{settings.esp32_wifi_port}"
            if settings.transport == "esp32_wifi"
            else settings.serial_port if settings.transport == "esp32_serial" else None
        )
        matches = _last_probe["transport"] == settings.transport and _last_probe["endpoint"] == endpoint
        return {**_last_probe, "verified": bool(_last_probe["verified"] and matches)}


def _persist_selection(transport_name: str, endpoint: str, baud: int | None) -> None:
    path = settings.transport_selection_file
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "transport": transport_name,
        "endpoint": endpoint,
        "baud": baud,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def probe_and_select_transport(
    transport_name: str,
    endpoint: str,
    baud: int | None = None,
    vehicle_profile: str | None = None,
) -> dict[str, Any]:
    if transport_name not in {"esp32_serial", "esp32_wifi"}:
        raise ValueError("Seules les connexions ESP32 USB et Wi-Fi sont disponibles.")

    previous = (
        settings.transport,
        settings.serial_port,
        settings.serial_baud,
        settings.esp32_wifi_host,
        settings.esp32_wifi_port,
    )
    normalized_endpoint = endpoint.strip()
    if transport_name == "esp32_serial":
        detected = {option["endpoint"] for option in available_transport_options() if option["transport"] == "esp32_serial"}
        if normalized_endpoint not in detected:
            raise ValueError("Ce port série n’est pas présent dans la liste des interfaces détectées.")
        settings.transport = transport_name
        settings.serial_port = normalized_endpoint
        if baud is not None:
            settings.serial_baud = baud
    else:
        host, separator, raw_port = normalized_endpoint.rpartition(":")
        if not separator or not host:
            raise ValueError("Adresse Wi-Fi attendue sous la forme hôte:port.")
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError("Le port Wi-Fi ESP32 est invalide.") from exc
        if not 1 <= port <= 65_535:
            raise ValueError("Le port Wi-Fi ESP32 doit être compris entre 1 et 65535.")
        settings.transport = transport_name
        settings.esp32_wifi_host = host
        settings.esp32_wifi_port = port

    transport = None
    hello: dict[str, Any] | None = None
    try:
        transport = (
            build_transport(vehicle_profile=vehicle_profile)
            if vehicle_profile is not None
            else build_transport()
        )
        transport.open()
        hello = getattr(transport, "hello", None)
    except Exception as exc:
        (
            settings.transport,
            settings.serial_port,
            settings.serial_baud,
            settings.esp32_wifi_host,
            settings.esp32_wifi_port,
        ) = previous
        with _connection_lock:
            _last_probe.update({
                "verified": False,
                "transport": transport_name,
                "endpoint": normalized_endpoint,
                "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "hello": None,
                "error": str(exc),
            })
        raise
    finally:
        if transport is not None:
            transport.close()

    verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    selected_baud = settings.serial_baud if transport_name == "esp32_serial" else None
    _persist_selection(transport_name, normalized_endpoint, selected_baud)
    with _connection_lock:
        _last_probe.update({
            "verified": True,
            "transport": transport_name,
            "endpoint": normalized_endpoint,
            "verified_at": verified_at,
            "hello": hello,
            "error": None,
        })
    return connection_probe_status()
