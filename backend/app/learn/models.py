from typing import Literal
from pydantic import BaseModel, Field


class CaptureStart(BaseModel):
    name: str = Field(default="Nouvelle découverte", min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CaptureMarker(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CaptureStatus(BaseModel):
    session_id: str
    active: bool
    source: str
    frame_count: int
    marker_count: int
    path: str
    name: str = ""
    started_at_us: int | None = None
    strict_passive: bool | None = None
    error: str | None = None


class CapturedEvent(BaseModel):
    type: Literal["can_frame", "marker", "meta"]
    timestamp_us: int
    source_timestamp_us: int | None = None
    arbitration_id: int | None = None
    extended: bool = False
    data_hex: str | None = None
    direction: Literal["rx", "tx", "unknown"] = "unknown"
    name: str | None = None
    note: str | None = None


class UdsCandidate(BaseModel):
    request_id: int
    response_id: int
    service: int
    positive_response_service: int | None = None
    request_payload_hex: str
    response_payload_hex: str | None = None
    occurrences: int = 1
    confidence: float = Field(ge=0, le=1)
    rationale: list[str] = Field(default_factory=list)
    access: str = "read_only"
    status: str = "experimental"


class AnalysisReport(BaseModel):
    session_id: str
    total_frames: int
    unique_ids: int
    markers: list[str]
    candidates: list[UdsCandidate]
    warnings: list[str] = Field(default_factory=list)


class DiscoverySessionSummary(BaseModel):
    session_id: str
    name: str
    source: str
    started_at_us: int | None = None
    duration_ms: float = 0
    frame_count: int = 0
    marker_count: int = 0
    markers: list[str] = Field(default_factory=list)
    size_bytes: int = 0
    analyzed: bool = False
    error: str | None = None


class CorrelationOptions(BaseModel):
    before_ms: int = Field(default=1200, ge=100, le=10_000)
    after_ms: int = Field(default=1200, ge=100, le=10_000)
    min_samples: int = Field(default=3, ge=2, le=100)
    max_candidates_per_marker: int = Field(default=40, ge=1, le=250)


class OpendbcSignalDefinition(BaseModel):
    name: str
    start_bit: int
    length: int
    byte_order: str
    signed: bool
    scale: float
    offset: float
    unit: str | None = None
    choices: dict[str, str] = Field(default_factory=dict)


class OpendbcMessageDefinition(BaseModel):
    arbitration_id: int
    extended: bool
    name: str
    length: int
    senders: list[str] = Field(default_factory=list)
    signals: list[OpendbcSignalDefinition] = Field(default_factory=list)


class OpendbcSourceInfo(BaseModel):
    enabled: bool
    loaded: bool
    database: str = "psa_aee2010_r3"
    revision: str = ""
    license: str = "MIT"
    source_url: str = "https://github.com/commaai/opendbc"
    compatibility: str = "Non validé pour Peugeot 308 T9 2018"
    message_count: int = 0
    signal_count: int = 0
    observed_message_count: int = 0
    observed_messages: list[str] = Field(default_factory=list)
    decoded_frame_count: int = 0
    decode_error_count: int = 0
    error: str | None = None


class OpendbcCatalog(BaseModel):
    source: OpendbcSourceInfo
    messages: list[OpendbcMessageDefinition] = Field(default_factory=list)


class PassiveCanSignal(BaseModel):
    key: str
    arbitration_id: int
    message: str
    signal: str
    display_name: str
    description: str
    category: str
    value: str | int | float | bool | None = None
    raw_value: str | int | float | bool | None = None
    unit: str | None = None
    source_unit: str | None = None
    factor: float = 1.0
    offset: float = 0.0
    customized: bool = False
    essential: bool = False
    updated_at_us: int
    raw_hex: str
    confidence: Literal["validated", "dbc_candidate"] = "dbc_candidate"


class PassiveSensorOverride(BaseModel):
    key: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
    label: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=24)
    factor: float = Field(default=1.0, ge=-1_000_000, le=1_000_000)
    offset: float = Field(default=0.0, ge=-1_000_000_000, le=1_000_000_000)


class PassiveSteeringSnapshot(BaseModel):
    detected: bool = False
    angle_degrees: float | None = None
    rate_degrees_s: float | None = None
    driver_torque: float | None = None
    angle_source: str | None = None
    torque_source: str | None = None
    warning: str | None = None


class PassiveSensorSnapshot(BaseModel):
    session_id: str
    active: bool
    strict_passive: bool | None = None
    frame_count: int
    observed_can_id_count: int
    observed_message_count: int
    unknown_can_id_count: int
    unknown_can_ids: list[int] = Field(default_factory=list)
    decoded_signal_count: int
    generated_at_us: int
    cursor_us: int
    steering: PassiveSteeringSnapshot
    signals: list[PassiveCanSignal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_url: str | None = None


class ByteProfile(BaseModel):
    index: int
    distinct_values: int
    minimum: int
    maximum: int
    toggle_count: int
    entropy: float


class CanIdProfile(BaseModel):
    arbitration_id: int
    extended: bool
    frame_count: int
    frequency_hz: float
    dlc_counts: dict[str, int]
    changing_bytes: list[int]
    byte_profiles: list[ByteProfile]
    opendbc_message: str | None = None
    opendbc_signals: list[str] = Field(default_factory=list)


class SignalCandidate(BaseModel):
    arbitration_id: int
    extended: bool
    kind: Literal["bit", "byte", "frequency", "dbc_signal"]
    byte_index: int | None = None
    bit_index: int | None = None
    before_value: str
    after_value: str
    before_samples: int
    after_samples: int
    effect: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1)
    confidence: Literal["faible", "moyenne", "forte"]
    rationale: list[str] = Field(default_factory=list)
    source: Literal["statistical", "opendbc"] = "statistical"
    dbc_message: str | None = None
    dbc_signal: str | None = None
    unit: str | None = None
    source_url: str | None = None


class MarkerCorrelation(BaseModel):
    marker: str
    notes: list[str]
    occurrences: int
    before_ms: int
    after_ms: int
    candidates: list[SignalCandidate]


class BehavioralAnalysisReport(BaseModel):
    session_id: str
    generated_at: str
    total_frames: int
    unique_ids: int
    duration_ms: float
    marker_count: int
    inventory: list[CanIdProfile]
    correlations: list[MarkerCorrelation]
    opendbc: OpendbcSourceInfo | None = None
    warnings: list[str] = Field(default_factory=list)
    analysis_path: str | None = None


class ReplaySample(BaseModel):
    t_ms: int
    speed_kph: float | None = None
    engine_rpm: float | None = None
    steering_angle_deg: float | None = None
    steering_rate_deg_s: float | None = None
    driver_torque: float | None = None
    accelerator_pct: float | None = None
    engine_torque_nm: float | None = None
    longitudinal_accel_ms2: float | None = None
    brake_active: bool | None = None
    brake_system_state: int | None = None
    brake_pressure_raw: float | None = None
    turn_signal: Literal["off", "right", "left", "hazard"] | None = None
    low_beam: bool | None = None
    high_beam: bool | None = None
    reverse: bool | None = None
    parking_brake: bool | None = None
    driver_door: bool | None = None
    passenger_door: bool | None = None
    front_wiper_status: int | None = None
    fuel_liters: float | None = None
    oil_temperature_c: float | None = None
    coolant_temperature_c: float | None = None
    intake_air_temperature_c: float | None = None
    oil_pressure_switch: bool | None = None
    battery_voltage_v: float | None = None
    battery_temperature_c: float | None = None
    battery_charge_pct: float | None = None
    ambient_temperature_c: float | None = None
    atmospheric_pressure_hpa: float | None = None
    lane_assist_status: int | None = None
    lane_departure: int | None = None
    lka_active: bool | None = None
    acc_mode: int | None = None
    acc_requested: bool | None = None
    speed_setpoint_kph: float | None = None
    wheel_front_left_kph: float | None = None
    wheel_front_right_kph: float | None = None
    wheel_rear_left_kph: float | None = None
    wheel_rear_right_kph: float | None = None
    x_m: float = 0
    y_m: float = 0
    heading_deg: float = 0
    distance_m: float = 0


class ReplayEvent(BaseModel):
    t_ms: int
    kind: str
    label: str
    value: str | int | float | bool | None = None


class ReplayData(BaseModel):
    version: int
    session_id: str
    name: str
    vehicle: str
    source: str
    source_size_bytes: int
    source_mtime_ns: int
    start_timestamp_us: int
    duration_ms: int
    sample_period_ms: int
    frame_count: int
    decoded_frame_count: int
    max_speed_kph: float
    average_moving_speed_kph: float
    distance_km: float
    gps_available: bool = False
    route_method: str
    steering_zero_offset_deg: float
    route_bounds: dict[str, float]
    available_fields: list[str] = Field(default_factory=list)
    field_quality: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    events: list[ReplayEvent] = Field(default_factory=list)
    points: list[ReplaySample] = Field(default_factory=list)
