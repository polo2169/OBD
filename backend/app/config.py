from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Diagbox++ OpenDiag PSA"
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
    diagnostic_timeout: float = 1.0
    read_dtcs: bool = True
    debug_sessions_enabled: bool = True
    trace_can_frames: bool = True
    trace_max_events: int = 250_000
    esp32_handshake_timeout: float = 3.0
    dtc_clear_enabled: bool = False
    safety_ecu_clear_enabled: bool = False
    database_dir: Path = Path("../database")
    session_dir: Path = Path("../data/sessions")
    vehicle_profile: str = "peugeot_308_t9_2018"
    opendbc_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
