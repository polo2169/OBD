from typing import Literal
from pydantic import BaseModel, Field


class CanFrame(BaseModel):
    timestamp_us: int
    arbitration_id: int = Field(ge=0)
    extended: bool = False
    data: bytes
    direction: Literal["rx", "tx"] = "rx"
    bus: Literal["default", "live", "diagnostic"] = "default"

    def as_json(self) -> dict:
        return {
            "timestamp_us": self.timestamp_us,
            "arbitration_id": self.arbitration_id,
            "extended": self.extended,
            "data_hex": self.data.hex().upper(),
            "direction": self.direction,
            "bus": self.bus,
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
    address_candidates: list[dict] = Field(default_factory=list)
    dtc_status_masks: list[int] = Field(default_factory=list)


class TelecodingParameterValue(BaseModel):
    key: str
    name: str
    byte: int
    raw_hex: str
    value: str | None = None


class TelecodingZoneInfo(BaseModel):
    did: int
    name: str
    family: str
    parameters: list[TelecodingParameterValue] = Field(default_factory=list)
    source: str | None = None
    confidence: str = "community_unverified_telecoding"


class DidReadResult(BaseModel):
    did: int
    name: str
    codec: str
    value: str | int | float | bool | None = None
    raw_hex: str | None = None
    source: str | None = None
    confidence: str = "experimental"
    request_hex: str | None = None
    response_hex: str | None = None
    nrc: int | None = None
    nrc_name: str | None = None
    error: str | None = None
    telecoding: TelecodingZoneInfo | None = None


class DtcReadResult(BaseModel):
    code: str
    raw_hex: str
    failure_type: int
    failure_type_label: str | None = None
    status: int
    status_hex: str
    status_labels: list[str] = Field(default_factory=list)
    title: str | None = None
    catalogs: list[str] = Field(default_factory=list)
    source: str | None = None
    confidence: str = "raw_only"
    state: Literal["active", "historical", "not_tested", "inactive"] = "inactive"
    state_label: str = "Inactif"
    state_detail: str = "Aucun indicateur d'échec actif."
    actionable: bool = False


class DtcSnapshotRequest(BaseModel):
    dtc_raw_hex: str = Field(min_length=6, max_length=6, pattern=r"^[0-9A-Fa-f]{6}$")
    record_number: int = Field(default=0xFF, ge=0, le=0xFF)
    vehicle_profile: str | None = Field(default=None, min_length=1, max_length=100)


class DtcSnapshotResult(BaseModel):
    ecu_key: str
    code: str
    dtc_raw_hex: str
    record_number_requested: int
    status: int | None = None
    status_hex: str | None = None
    status_labels: list[str] = Field(default_factory=list)
    snapshot_record_number: int | None = None
    identifier_count: int | None = None
    raw_data_hex: str | None = None
    request_hex: str
    response_hex: str | None = None
    nrc: int | None = None
    nrc_name: str | None = None
    error: str | None = None


class DidSweepRequest(BaseModel):
    did_start: int = Field(ge=0, le=0xFFFF)
    did_end: int = Field(ge=0, le=0xFFFF)
    vehicle_profile: str | None = Field(default=None, min_length=1, max_length=100)


class DidSweepHit(BaseModel):
    did: int
    outcome: Literal["positive", "negative_response"]
    raw_hex: str | None = None
    response_hex: str | None = None
    nrc: int | None = None
    nrc_name: str | None = None
    telecoding: TelecodingZoneInfo | None = None


class DidSweepResult(BaseModel):
    ecu_key: str
    did_start: int
    did_end: int
    scanned_count: int
    hits: list[DidSweepHit] = Field(default_factory=list)
    unsupported_count: int = 0
    timeout_count: int = 0


class ObservedDtcInput(BaseModel):
    code: str = Field(pattern=r"^[PpBbCcUu][0-9A-Fa-f]{4}$")
    ecu_key: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    source: str = Field(default="user_reported", max_length=80)
    vin: str | None = Field(
        default=None,
        min_length=17,
        max_length=17,
        pattern=r"^[A-HJ-NPR-Z0-9]{17}$",
    )
    vehicle_profile: str | None = Field(default=None, max_length=100)


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
    group: str | None = None
    description: str | None = None
    source: str | None = None
    confidence: str = "standardized"
    raw_hex: str | None = None
    error: str | None = None


class SensorSnapshot(BaseModel):
    transport: str
    vehicle_profile: str | None = None
    request_id: int
    response_id: int
    mil_on: bool | None = None
    emissions_dtc_count: int | None = None
    readiness_raw_hex: str | None = None
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
    dtc_status_mask_used: int | None = None
    dtc_request_hex: str | None = None
    dtc_response_hex: str | None = None
    dtc_error: str | None = None
    active_session: int | None = None
    active_session_source: str | None = None
    probe_method: str | None = None
    probe_response_hex: str | None = None
    probe_attempts: list[dict] = Field(default_factory=list)
    raw_responses: list[str] = Field(default_factory=list)
    error: str | None = None
    did_sweep_hits: list["DidSweepHit"] = Field(default_factory=list)
    did_sweep_range: str | None = None
    did_sweep_error: str | None = None


class DtcSummary(BaseModel):
    active: int = 0
    historical: int = 0
    not_tested: int = 0
    inactive: int = 0
    total: int = 0
    affected_ecus: int = 0


class DtcChange(BaseModel):
    ecu_key: str
    ecu_name: str
    code: str
    raw_hex: str
    title: str | None = None
    before_state: Literal["active", "historical", "not_tested", "inactive"] | None = None
    after_state: Literal["active", "historical", "not_tested", "inactive"] | None = None
    before_status_hex: str | None = None
    after_status_hex: str | None = None


class ScanComparison(BaseModel):
    previous_scan_id: str | None = None
    previous_scanned_at: str | None = None
    comparable_ecus: list[str] = Field(default_factory=list)
    excluded_ecus: list[str] = Field(default_factory=list)
    appeared: list[DtcChange] = Field(default_factory=list)
    resolved: list[DtcChange] = Field(default_factory=list)
    changed: list[DtcChange] = Field(default_factory=list)
    unchanged: int = 0


class ScanReport(BaseModel):
    scan_id: str | None = None
    scanned_at: str | None = None
    vehicle_profile: str
    vin: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    transport: str
    readonly: bool
    ecus: list[EcuScanResult]
    dtc_summary: DtcSummary = Field(default_factory=DtcSummary)
    comparison: ScanComparison | None = None
    warnings: list[str] = Field(default_factory=list)
    debug: DebugSummary = Field(default_factory=DebugSummary)


class ScanRequest(BaseModel):
    vehicle_profile: str | None = Field(default=None, min_length=1, max_length=100)
    vin: str | None = Field(
        default=None,
        min_length=17,
        max_length=17,
        pattern=r"^[A-HJ-NPR-Z0-9]{17}$",
    )
    extended_probe: bool = False


class VehicleSelectionRequest(BaseModel):
    vin: str = Field(
        min_length=17,
        max_length=17,
        pattern=r"^[A-HJ-NPR-Z0-9]{17}$",
    )


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
    request_hex: str = "14FFFFFF"
    before_dtcs: list[DtcReadResult] = Field(default_factory=list)
    after_dtcs: list[DtcReadResult] = Field(default_factory=list)
    persistent_dtcs: list[DtcReadResult] = Field(default_factory=list)
    verified: bool = False
    verification_error: str | None = None
    message: str
    session_id: str | None = None


class DiagnosticTraceImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=5_000_000)
    vehicle_profile: str = Field(default="peugeot_308_t9_2018", min_length=1, max_length=100)
    source_format: Literal["auto", "text", "csv", "jsonl"] = "auto"


class TransportConnectRequest(BaseModel):
    transport: Literal["esp32_serial", "esp32_wifi"]
    endpoint: str = Field(min_length=3, max_length=255)
    baud: int | None = Field(default=None, ge=9_600, le=4_000_000)


class OperatingModeRequest(BaseModel):
    mode: Literal["read_only", "maintenance"]
    confirmation: str = ""
    vin: str | None = Field(
        default=None,
        min_length=17,
        max_length=17,
        pattern=r"^[A-HJ-NPR-Z0-9]{17}$",
    )
    vehicle_stationary: bool = False
    ignition_on_engine_off: bool = False
    stable_battery_voltage: bool = False
    workshop_or_private_site: bool = False


class PsaSeedKeyRequest(BaseModel):
    seed_hex: str = Field(pattern=r"^[0-9A-Fa-f]{8}$")
    application_key_hex: str = Field(pattern=r"^[0-9A-Fa-f]{4}$")


class PsaSeedKeyResult(BaseModel):
    seed_hex: str
    application_key_hex: str
    response_key_hex: str
    source: str
    transmitted: bool = False


class PsaUnlockRequest(BaseModel):
    application_key_hex: str = Field(pattern=r"^[0-9A-Fa-f]{4}$")
    confirmation: str
    vehicle_stationary: bool = False
    ignition_on_engine_off: bool = False
    stable_battery_voltage: bool = False
    workshop_or_private_site: bool = False


class PsaUnlockResult(BaseModel):
    ecu_key: str
    unlocked: bool
    seed_hex: str
    response_key_hex: str
    response_hex: str
    message: str
    session_id: str | None = None


class PsaActionRequest(BaseModel):
    confirmation: str
    vehicle_stationary: bool = False
    ignition_on_engine_off: bool = False
    stable_battery_voltage: bool = False
    workshop_or_private_site: bool = False
    duration_ms: int = Field(default=1_500, ge=250, le=3_000)


class PsaActionResult(BaseModel):
    action_key: str
    executed: bool
    started_response_hex: str | None = None
    stopped_response_hex: str | None = None
    duration_ms: int
    message: str
    session_id: str | None = None


class VehicleIdentityRequest(BaseModel):
    vehicle_profile: str = Field(min_length=1, max_length=100)


class VehicleIdentityAttempt(BaseModel):
    key: str
    label: str
    protocol: Literal["uds", "obd"]
    request_id: int
    response_id: int
    command_hex: str
    source: str | None = None
    confidence: str = "experimental"
    success: bool = False
    vin: str | None = None
    raw_hex: str | None = None
    error: str | None = None


class VehicleIdentityField(BaseModel):
    key: str
    name: str
    protocol: Literal["uds", "obd"]
    command_hex: str
    value: str | None = None
    raw_hex: str | None = None
    source: str | None = None
    confidence: str = "experimental"
    error: str | None = None


class VehicleIdentityResult(BaseModel):
    vehicle_profile: str
    manufacturer: str
    model: str
    year: str | int | None = None
    transport: str
    found: bool = False
    vin: str | None = None
    wmi: str | None = None
    detected_manufacturer: str | None = None
    profile_match: bool | None = None
    attempts: list[VehicleIdentityAttempt] = Field(default_factory=list)
    fields: list[VehicleIdentityField] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    debug: DebugSummary = Field(default_factory=DebugSummary)
