from pathlib import Path
import json
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Diagbox++ OpenDiag PSA"
    environment: str = "development"
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 5173
    cors_allow_local_ports: bool = True
    transport: str = "virtual"
    serial_port: str = "/dev/ttyACM0"
    serial_baud: int = 921_600
    esp32_wifi_host: str = "192.168.4.1"
    esp32_wifi_port: int = 35_000
    esp32_wifi_reconnect_interval: float = 0.5
    can_channel: str = "vcan0"
    can_interface: str = "socketcan"
    can_tx_enabled: bool = False
    read_only: bool = True
    runtime_mode_switch_enabled: bool = False
    diagnostic_timeout: float = 1.0
    read_dtcs: bool = True
    debug_sessions_enabled: bool = True
    trace_can_frames: bool = True
    trace_max_events: int = 250_000
    live_obd_enabled: bool = True
    esp32_handshake_timeout: float = 3.0
    dtc_clear_enabled: bool = False
    safety_ecu_clear_enabled: bool = False
    psa_advanced_enabled: bool = True
    psa_security_access_enabled: bool = False
    psa_actuator_enabled: bool = False
    psa_actuator_max_duration_ms: int = 3_000
    database_dir: Path = Path("../database")
    session_dir: Path = Path("../data/sessions")
    sensor_overrides_file: Path = Path("../data/sensor_overrides.json")
    manual_signal_validations_file: Path = Path("../data/manual_signal_validations.json")
    live_sensor_registry_file: Path = Path("../data/live_sensor_registry.json")
    observed_dtcs_file: Path = Path("../data/observed_dtcs.json")
    diagnostic_history_dir: Path = Path("../data/diagnostics")
    diagnostic_trace_import_dir: Path = Path("../data/diagbox_imports")
    transport_selection_file: Path = Path("../data/transport_selection.json")
    security_audit_file: Path = Path("../data/security_audit.jsonl")
    vehicle_profile: str = "peugeot_308_t9_2018"
    opendbc_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def _apply_saved_transport_selection() -> None:
    # Une variable d'environnement explicite reste prioritaire, notamment pour les tests.
    if "TRANSPORT" in os.environ or not settings.transport_selection_file.exists():
        return
    try:
        selection = json.loads(settings.transport_selection_file.read_text(encoding="utf-8"))
        transport_name = selection.get("transport")
        endpoint = str(selection.get("endpoint") or "")
        if transport_name == "esp32_serial" and endpoint:
            settings.transport = transport_name
            settings.serial_port = endpoint
            if isinstance(selection.get("baud"), int):
                settings.serial_baud = selection["baud"]
        elif transport_name == "esp32_wifi" and ":" in endpoint:
            host, raw_port = endpoint.rsplit(":", 1)
            port = int(raw_port)
            if host and 1 <= port <= 65_535:
                settings.transport = transport_name
                settings.esp32_wifi_host = host
                settings.esp32_wifi_port = port
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # Une préférence invalide ne doit jamais empêcher le backend de démarrer.
        return


_apply_saved_transport_selection()
