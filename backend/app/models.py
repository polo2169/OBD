from typing import Literal
from pydantic import BaseModel, Field


class CanFrame(BaseModel):
    timestamp_us: int
    arbitration_id: int = Field(ge=0)
    extended: bool = False
    data: bytes
    direction: Literal["rx", "tx"] = "rx"

    def as_json(self) -> dict:
        return {
            "timestamp_us": self.timestamp_us,
            "arbitration_id": self.arbitration_id,
            "extended": self.extended,
            "data_hex": self.data.hex().upper(),
            "direction": self.direction,
        }


class EcuDefinition(BaseModel):
    key: str
    name: str
    request_id: int | None = None
    response_id: int | None = None
    protocol: str = "uds"
    confidence: str = "experimental"
    access: str = "read_only"
    family: str | None = None
    network: str = "diagnostic_can"
    optional: bool = True
    source: str | None = None
    notes: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    dtc_catalogs: list[str] = Field(default_factory=list)


class DidReadResult(BaseModel):
    did: int
    name: str
    codec: str
    value: str | int | float | bool | None = None
    raw_hex: str | None = None
    source: str | None = None
    confidence: str = "experimental"
    error: str | None = None


class DtcReadResult(BaseModel):
    code: str
    raw_hex: str
    failure_type: int
    status: int
    status_hex: str
    status_labels: list[str] = Field(default_factory=list)
    title: str | None = None
    catalogs: list[str] = Field(default_factory=list)
    source: str | None = None
    confidence: str = "raw_only"


class ObservedDtcInput(BaseModel):
    code: str = Field(pattern=r"^[PpBbCcUu][0-9A-Fa-f]{4}$")
    ecu_key: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    source: str = Field(default="user_reported", max_length=80)


class ObservedDtcResult(ObservedDtcInput):
    code: str
    ecu_name: str
    title: str | None = None
    catalogs: list[str] = Field(default_factory=list)
    catalog_source: str | None = None
    confidence: str = "user_reported"
    recorded_at: str


class DebugSummary(BaseModel):
    session_id: str | None = None
    trace_file: str | None = None
    duration_ms: float = 0
    event_count: int = 0
    dropped_events: int = 0
    event_types: dict[str, int] = Field(default_factory=dict)


class SensorValue(BaseModel):
    key: str
    pid: int
    name: str
    value: float | int | None = None
    unit: str | None = None
    raw_hex: str | None = None
    error: str | None = None


class SensorSnapshot(BaseModel):
    transport: str
    request_id: int
    response_id: int
    supported_pids: list[int] = Field(default_factory=list)
    values: list[SensorValue] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    debug: DebugSummary = Field(default_factory=DebugSummary)


class EcuScanResult(BaseModel):
    key: str
    name: str
    detected: bool
    request_id: int | None
    response_id: int | None
    family: str | None = None
    network: str = "diagnostic_can"
    confidence: str = "experimental"
    optional: bool = True
    source: str | None = None
    vin: str | None = None
    identification: list[DidReadResult] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    dtcs: list[DtcReadResult] = Field(default_factory=list)
    dtc_status_availability_mask: int | None = None
    dtc_error: str | None = None
    raw_responses: list[str] = Field(default_factory=list)
    error: str | None = None


class ScanReport(BaseModel):
    vehicle_profile: str
    transport: str
    readonly: bool
    ecus: list[EcuScanResult]
    warnings: list[str] = Field(default_factory=list)
    debug: DebugSummary = Field(default_factory=DebugSummary)


class ClearDtcRequest(BaseModel):
    confirmation: str
    vehicle_stationary: bool = False
    ignition_on_engine_off: bool = False
    stable_battery_voltage: bool = False
    report_saved: bool = False


class ClearDtcResult(BaseModel):
    ecu_key: str
    cleared: bool
    group: str = "FFFFFF"
    response_hex: str | None = None
    message: str
    session_id: str | None = None
