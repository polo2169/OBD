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
