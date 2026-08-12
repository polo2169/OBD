import type { PowertrainProfile } from "./sensorInventory";

export type Status = {
  application: string;
  transport: string;
  read_only: boolean;
  can_tx_enabled: boolean;
  read_dtcs: boolean;
  debug_sessions_enabled: boolean;
  trace_can_frames: boolean;
  dtc_clear_enabled: boolean;
  safety_ecu_clear_enabled: boolean;
  psa_advanced_enabled: boolean;
  psa_security_access_enabled: boolean;
  psa_actuator_enabled: boolean;
  psa_ecu_reset_enabled: boolean;
  psa_telecoding_write_enabled: boolean;
  vehicle_profile: string;
  gateway_endpoint?: string | null;
  gateway_verified?: boolean;
  gateway_hello?: Record<string, unknown> | null;
  gateway_error?: string | null;
  operating_mode?: "read_only" | "maintenance";
  runtime_mode_switch_enabled?: boolean;
};

export type OperatingModeState = {
  mode: "read_only" | "maintenance";
  read_only: boolean;
  maintenance_available: boolean;
  runtime_switch_enabled: boolean;
  can_tx_enabled: boolean;
  gateway_ready: boolean;
  capture_active: boolean;
  blockers: string[];
  capabilities: {
    diagnostic_reads: boolean;
    dtc_clear: boolean;
    safety_ecu_clear: boolean;
    psa_actions: boolean;
    security_access: boolean;
    ecu_reset: boolean;
    telecoding: boolean;
  };
};

export type TransportOption = {
  id: string;
  transport: "esp32_serial" | "esp32_wifi";
  endpoint: string;
  label: string;
  detected?: boolean | null;
  baud?: number | null;
};

export type TransportConnection = {
  verified: boolean;
  transport?: string | null;
  endpoint?: string | null;
  verified_at?: string | null;
  hello?: Record<string, unknown> | null;
  error?: string | null;
};

export type TransportCatalog = {
  options: TransportOption[];
  current_id?: string | null;
  capture_active: boolean;
  connection: TransportConnection;
};

export type TelecodingParameterValue = {
  key: string;
  name: string;
  byte: number;
  raw_hex: string;
  value?: string | null;
  options: string[];
};

export type TelecodingZoneInfo = {
  did: number;
  name: string;
  family: string;
  parameters: TelecodingParameterValue[];
  source?: string | null;
  confidence: string;
};

export type DidValue = {
  did: number;
  name: string;
  codec: string;
  value?: string | number | boolean | null;
  raw_hex?: string | null;
  source?: string | null;
  confidence: string;
  request_hex?: string | null;
  response_hex?: string | null;
  nrc?: number | null;
  nrc_name?: string | null;
  error?: string | null;
  telecoding?: TelecodingZoneInfo | null;
};

export type ProbeAttempt = {
  request_hex: string;
  response_hex?: string | null;
  outcome: "positive" | "negative_response" | "timeout";
  nrc?: number | null;
  nrc_name?: string | null;
  error?: string | null;
};

export type DtcValue = {
  code: string;
  raw_hex: string;
  failure_type: number;
  failure_type_label?: string | null;
  status: number;
  status_hex: string;
  status_labels: string[];
  title?: string | null;
  catalogs: string[];
  source?: string | null;
  confidence: string;
  state: "active" | "historical" | "not_tested" | "inactive";
  state_label: string;
  state_detail: string;
  actionable: boolean;
};

export type DtcSnapshotResult = {
  ecu_key: string;
  code: string;
  dtc_raw_hex: string;
  record_number_requested: number;
  status?: number | null;
  status_hex?: string | null;
  status_labels: string[];
  snapshot_record_number?: number | null;
  identifier_count?: number | null;
  raw_data_hex?: string | null;
  request_hex: string;
  response_hex?: string | null;
  nrc?: number | null;
  nrc_name?: string | null;
  error?: string | null;
};

export type DidSweepHit = {
  did: number;
  outcome: "positive" | "negative_response";
  raw_hex?: string | null;
  response_hex?: string | null;
  nrc?: number | null;
  nrc_name?: string | null;
  telecoding?: TelecodingZoneInfo | null;
};

export type DidSweepResult = {
  ecu_key: string;
  did_start: number;
  did_end: number;
  scanned_count: number;
  hits: DidSweepHit[];
  unsupported_count: number;
  timeout_count: number;
};

export type ObservedDtc = {
  code: string;
  ecu_key?: string | null;
  ecu_name: string;
  label?: string | null;
  note?: string | null;
  source: string;
  title?: string | null;
  catalogs: string[];
  catalog_source?: string | null;
  confidence: string;
  recorded_at: string;
};

export type Ecu = {
  key: string;
  name: string;
  detected: boolean;
  request_id: number | null;
  response_id: number | null;
  family?: string | null;
  network: string;
  confidence: string;
  optional: boolean;
  source?: string | null;
  vin?: string | null;
  identification: DidValue[];
  aliases: string[];
  dtcs: DtcValue[];
  dtc_status_availability_mask?: number | null;
  dtc_status_mask_used?: number | null;
  dtc_request_hex?: string | null;
  dtc_response_hex?: string | null;
  dtc_error?: string | null;
  active_session?: number | null;
  active_session_source?: string | null;
  probe_method?: string | null;
  probe_response_hex?: string | null;
  probe_attempts?: ProbeAttempt[];
  error?: string | null;
  did_sweep_hits?: DidSweepHit[];
  did_sweep_range?: string | null;
  did_sweep_error?: string | null;
};

export type DebugSummary = {
  session_id?: string | null;
  trace_file?: string | null;
  duration_ms: number;
  event_count: number;
  dropped_events: number;
  event_types: Record<string, number>;
};

export type Report = {
  scan_id?: string | null;
  scanned_at?: string | null;
  vehicle_profile: string;
  vin?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  transport: string;
  readonly: boolean;
  ecus: Ecu[];
  dtc_summary: {
    active: number;
    historical: number;
    not_tested: number;
    inactive: number;
    total: number;
    affected_ecus: number;
  };
  comparison?: {
    previous_scan_id?: string | null;
    previous_scanned_at?: string | null;
    comparable_ecus: string[];
    excluded_ecus: string[];
    appeared: DtcChange[];
    resolved: DtcChange[];
    changed: DtcChange[];
    unchanged: number;
  } | null;
  warnings: string[];
  debug: DebugSummary;
};

export type DtcChange = {
  ecu_key: string;
  ecu_name: string;
  code: string;
  raw_hex: string;
  title?: string | null;
  before_state?: DtcValue["state"] | null;
  after_state?: DtcValue["state"] | null;
  before_status_hex?: string | null;
  after_status_hex?: string | null;
};

export type DiagnosticVehicle = {
  vin: string;
  vehicle_profile: string;
  manufacturer: string;
  model: string;
  year?: string | number | null;
  first_seen?: string | null;
  last_seen?: string | null;
  latest_scan_id?: string | null;
  latest_identity_session_id?: string | null;
  last_selected_at?: string | null;
  is_active?: boolean;
  scan_count: number;
};

export type VehicleTimelineEntry = {
  id: string;
  kind: "diagnostic" | "capture" | "identity";
  timestampMs: number;
  title: string;
  description: string;
  badge: string;
  scanId?: string;
  sessionId?: string;
  severity?: "good" | "warning" | "neutral";
};

export type DiagnosticReportSummary = {
  scan_id: string;
  scanned_at: string;
  vin: string;
  vehicle_profile: string;
  manufacturer?: string | null;
  model?: string | null;
  dtc_summary: Report["dtc_summary"];
  detected_ecus: number;
};

export type DiagnosticSensorCatalogEntry = {
  key: string;
  pid: number;
  name: string;
  unit: string;
  group: string;
  description: string;
  source?: string;
  confidence?: string;
  access?: string;
  request_hex?: string;
};

export type DiagnosticSensorValue = {
  key: string;
  pid: number;
  name: string;
  value?: number | null;
  unit?: string | null;
  group?: string | null;
  description?: string | null;
  source?: string | null;
  confidence?: string;
  raw_hex?: string | null;
  error?: string | null;
};

export type TraceImportResult = {
  import_id: string;
  name: string;
  frame_count: number;
  payload_count: number;
  exchange_count: number;
  unparsed_line_count: number;
  observed_dids: Array<{ ecu_key?: string | null; did: number; value_hex: string }>;
  observed_actions: Array<{
    ecu_key?: string | null;
    service: number;
    service_name: string;
    identifier?: number | null;
    request_hex: string;
    response_hex?: string | null;
    status: string;
    review_required: boolean;
    executable: false;
  }>;
  warnings: string[];
  saved_file: string;
};

export type RegressionResult = {
  baseline: string;
  scan_id?: string | null;
  connectivity_match: boolean;
  dtc_match: boolean;
  match: boolean;
  differences: Array<{
    scope: "connectivity" | "dtc";
    ecu: string;
    field: string;
    expected: unknown;
    actual: unknown;
  }>;
};

export type ClearDtcResult = {
  ecu_key: string;
  cleared: boolean;
  request_hex: string;
  response_hex?: string | null;
  before_dtcs: DtcValue[];
  after_dtcs: DtcValue[];
  persistent_dtcs: DtcValue[];
  verified: boolean;
  verification_error?: string | null;
  message: string;
  session_id?: string | null;
};

export type DiagnosticSensorSnapshot = {
  transport: string;
  vehicle_profile?: string | null;
  request_id: number;
  response_id: number;
  mil_on?: boolean | null;
  emissions_dtc_count?: number | null;
  readiness_raw_hex?: string | null;
  supported_pids: number[];
  values: DiagnosticSensorValue[];
  errors: string[];
  debug: DebugSummary;
};

export type VehicleProfileSummary = {
  key: string;
  manufacturer: string;
  model: string;
  platform?: string | null;
  year?: string | number | null;
  architecture?: string | null;
  confidence: string;
  identity_scope: "full_profile" | "identity_only" | string;
  vin_methods: string[];
  notes: string[];
};

export type VehicleIdentityAttempt = {
  key: string;
  label: string;
  protocol: "uds" | "obd";
  request_id: number;
  response_id: number;
  command_hex: string;
  source?: string | null;
  confidence: string;
  success: boolean;
  vin?: string | null;
  raw_hex?: string | null;
  error?: string | null;
};

export type VehicleIdentityField = {
  key: string;
  name: string;
  protocol: "uds" | "obd";
  command_hex: string;
  value?: string | null;
  raw_hex?: string | null;
  source?: string | null;
  confidence: string;
  error?: string | null;
};

export type VehicleIdentityResult = {
  vehicle_profile: string;
  manufacturer: string;
  model: string;
  year?: string | number | null;
  transport: string;
  found: boolean;
  vin?: string | null;
  wmi?: string | null;
  detected_manufacturer?: string | null;
  profile_match?: boolean | null;
  attempts: VehicleIdentityAttempt[];
  fields: VehicleIdentityField[];
  warnings: string[];
  debug: DebugSummary;
};

export type PsaSecurityKey = { variant: string; key_hex: string };

export type PsaTelecodingZoneRef = { did: string; name: string };

export type PsaAdvancedEcu = {
  key: string;
  name: string;
  family?: string | null;
  request_id?: number | null;
  response_id?: number | null;
  protocol: string;
  optional: boolean;
  telecoding_variant?: string | null;
  telecoding_write_allowed: boolean;
  security_keys: PsaSecurityKey[];
  telecoding_zones: PsaTelecodingZoneRef[];
};

export type PsaAdvancedAction = {
  key: string;
  ecu_key: string;
  name: string;
  description: string;
  available: boolean;
  timed: boolean;
  start_payload_hex?: string | null;
  stop_payload_hex?: string | null;
  confirmation?: string | null;
  confidence: string;
  source: string;
  unavailable_reason?: string | null;
  validation_status: "source_confirmed_not_vehicle_tested" | "vehicle_confirmed" | "not_documented";
  requires_detected_ecu: boolean;
  vehicle_confirmed: boolean;
};

export type PsaAdvancedCatalog = {
  enabled: boolean;
  security_access_enabled: boolean;
  actuator_enabled: boolean;
  ecu_reset_enabled: boolean;
  telecoding_write_enabled: boolean;
  read_only: boolean;
  can_tx_enabled: boolean;
  required_firmware_policy: string;
  wiring: { vehicle_can: string; standard_obd: string; source: string; warning: string };
  ecus: PsaAdvancedEcu[];
  actions: PsaAdvancedAction[];
  sources: string[];
};

export type EcuResetResult = {
  ecu_key: string;
  reset: boolean;
  response_hex?: string | null;
  message: string;
  session_id?: string | null;
};

export type TelecodingWriteResult = {
  ecu_key: string;
  did: number;
  parameter_key: string;
  requested_option: string;
  previous_value?: string | null;
  new_value?: string | null;
  verified: boolean;
  raw_before_hex: string;
  raw_after_hex: string;
  message: string;
  session_id?: string | null;
};

export type TelecodingOptionDefinition = {
  key: string;
  name: string;
  encoded_hex: string;
};

export type TelecodingFieldDefinition = {
  key: string;
  name: string;
  form_type: string;
  value_type: string;
  byte: number;
  byte_length: number;
  mask_hex?: string | null;
  available_logic: string;
  accepted_zone_lengths: number[];
  read_only: boolean;
  writable: boolean;
  options: TelecodingOptionDefinition[];
};

export type TelecodingDecodedField = TelecodingFieldDefinition & {
  available: boolean;
  raw_hex?: string | null;
  value_key?: string | null;
  value?: string | null;
};

export type TelecodingZoneDefinition = {
  did: number;
  did_hex: string;
  name: string;
  tab: string;
  tab_name: string;
  value_type: string;
  form_type: string;
  read_only: boolean;
  coding_candidate: boolean;
  writable: boolean;
  fields: TelecodingFieldDefinition[];
};

export type TelecodingVariantDefinition = {
  id: string;
  name: string;
  family: string;
  protocol: string;
  request_id?: number | null;
  response_id?: number | null;
  security_keys: PsaSecurityKey[];
  tabs: Record<string, string>;
  zones: TelecodingZoneDefinition[];
  zone_count: number;
  coding_zone_count: number;
  writable_zone_count: number;
  write_supported: boolean;
  source?: string | null;
};

export type TelecodingCatalogResult = {
  ecu_key: string;
  ecu_name: string;
  ecu_family?: string | null;
  ecu_request_id: number;
  ecu_response_id: number;
  source?: string | null;
  revision?: string | null;
  license?: string | null;
  warning: string;
  variants: TelecodingVariantDefinition[];
};

export type TelecodingSnapshotResult = {
  snapshot_id: string;
  captured_at: string;
  ecu_key: string;
  ecu_name: string;
  variant_id: string;
  variant_name: string;
  did: number;
  did_hex: string;
  zone_name: string;
  vin?: string | null;
  raw_hex: string;
  sha256: string;
  fields: TelecodingDecodedField[];
  source?: string | null;
  backup_file: string;
};

export type TelecodingChangeRequest = { field_key: string; option_key: string };

export type TelecodingFieldChange = {
  field_key: string;
  field_name: string;
  previous_option_key?: string | null;
  previous_value?: string | null;
  requested_option_key: string;
  requested_value: string;
};

export type TelecodingPreviewResult = {
  snapshot_id: string;
  plan_hash: string;
  ecu_key: string;
  variant_id: string;
  did: number;
  raw_before_hex: string;
  raw_after_hex: string;
  changed_byte_indexes: number[];
  changes: TelecodingFieldChange[];
  fields_after: TelecodingDecodedField[];
  executable: boolean;
  blockers: string[];
};

export type TelecodingExecuteResult = {
  execution_id: string;
  snapshot_id: string;
  ecu_key: string;
  variant_id: string;
  did: number;
  verified: boolean;
  stale_snapshot: boolean;
  raw_before_hex: string;
  raw_requested_hex: string;
  raw_after_hex?: string | null;
  changes: TelecodingFieldChange[];
  message: string;
  session_id?: string | null;
  report_file: string;
};

export type TelecodingBackupSummary = {
  snapshot_id: string;
  captured_at: string;
  ecu_key: string;
  variant_id: string;
  did: number;
  did_hex: string;
  zone_name: string;
  vin?: string | null;
  sha256: string;
  raw_length: number;
};

export type PsaSeedKeyResult = {
  seed_hex: string;
  application_key_hex: string;
  response_key_hex: string;
  source: string;
  transmitted: boolean;
};

export type PsaActionResult = {
  action_key: string;
  executed: boolean;
  started_response_hex?: string | null;
  stopped_response_hex?: string | null;
  duration_ms: number;
  message: string;
  session_id?: string | null;
};

export type MaintenanceService = {
  key: string;
  name: string;
  category: string;
  description: string;
  risk: "low" | "medium" | "high" | "restricted";
  applicability: "applicable" | "if_equipped" | "not_applicable" | "unknown";
  implementation_status: "vehicle_validated" | "procedure_required" | "equipment_confirmation_required" | "not_applicable" | "research_required";
  execution_enabled: boolean;
  reason: string;
};

export type MaintenanceCatalog = {
  vehicle_profile: string;
  manufacturer: string;
  model: string;
  policy: string;
  execution_enabled: boolean;
  service_count: number;
  counts: Record<string, number>;
  services: MaintenanceService[];
  notes: string[];
  protocol_coverage: { key: string; name: string; supported: boolean; detail: string }[];
};

export type PsaUnlockResult = {
  ecu_key: string;
  unlocked: boolean;
  seed_hex: string;
  response_key_hex: string;
  response_hex: string;
  message: string;
  session_id?: string | null;
};

export type SensorInventoryStatus = "measured" | "supported" | "to_test" | "to_observe" | "to_decode" | "unsupported" | "not_applicable";

export type SensorInventoryRow = {
  id: string;
  label: string;
  system: string;
  description: string;
  source: "OBD-II" | "CAN / OBD direct" | "Fiat spécifique" | "PSA spécifique";
  status: SensorInventoryStatus;
  statusLabel: string;
  priority: 1 | 2 | 3;
  optional: boolean;
  value?: string | null;
  reference?: string;
};

export type PassiveCanSignal = {
  key: string;
  arbitration_id: number;
  message: string;
  signal: string;
  display_name: string;
  description: string;
  category: string;
  ecu_family?: string | null;
  value?: string | number | boolean | null;
  raw_value?: string | number | boolean | null;
  unit?: string | null;
  source_unit?: string | null;
  factor: number;
  offset: number;
  customized: boolean;
  essential: boolean;
  updated_at_us: number;
  raw_hex: string;
  source: "can" | "obd";
  pid?: number | null;
  confidence: "validated" | "vehicle_observed_candidate" | "dbc_candidate" | "standardized";
  user_defined?: boolean;
  definition_key?: string | null;
  derived_from?: string | null;
};

export type PassiveSteeringSnapshot = {
  detected: boolean;
  angle_degrees?: number | null;
  rate_degrees_s?: number | null;
  driver_torque?: number | null;
  angle_source?: string | null;
  torque_source?: string | null;
  warning?: string | null;
};

export type PassiveSensorSnapshot = {
  session_id: string;
  active: boolean;
  strict_passive?: boolean | null;
  frame_count: number;
  observed_can_id_count: number;
  observed_message_count: number;
  unknown_can_id_count: number;
  unknown_can_ids: number[];
  decoded_signal_count: number;
  generated_at_us: number;
  cursor_us: number;
  steering: PassiveSteeringSnapshot;
  signals: PassiveCanSignal[];
  warnings: string[];
  source_url?: string | null;
  hybrid_obd_enabled: boolean;
  hybrid_obd_ready: boolean;
  obd_sample_count: number;
  obd_error?: string | null;
};

export type LiveSensorDefinition = {
  key: string;
  source_key: string;
  vin?: string | null;
  label: string;
  description: string;
  category: string;
  unit?: string | null;
  factor: number;
  offset: number;
  state: "discovered" | "observed" | "validated" | "documented" | "published";
  archived: boolean;
  created_at: string;
  updated_at: string;
};

export type CaptureStatus = {
  session_id: string;
  active: boolean;
  source: string;
  frame_count: number;
  live_frame_count: number;
  diagnostic_frame_count: number;
  marker_count: number;
  gps_point_count: number;
  gps_last_accuracy_m?: number | null;
  path: string;
  name: string;
  started_at_us?: number | null;
  strict_passive?: boolean | null;
  dual_can?: boolean;
  live_can_ready?: boolean | null;
  diagnostic_can_ready?: boolean | null;
  hybrid_obd_enabled: boolean;
  hybrid_obd_ready: boolean;
  obd_sample_count: number;
  obd_supported_pids: number[];
  obd_error?: string | null;
  error?: string | null;
  vin?: string | null;
  vehicle_profile?: string | null;
  vehicle_label?: string | null;
  mode?: "learn_passive" | "live_data" | null;
};

export type DiscoverySession = {
  session_id: string;
  name: string;
  source: string;
  started_at_us?: number | null;
  duration_ms: number;
  frame_count: number;
  live_frame_count?: number;
  diagnostic_frame_count?: number;
  marker_count: number;
  gps_point_count?: number;
  markers: string[];
  size_bytes: number;
  analyzed: boolean;
  error?: string | null;
  vin?: string | null;
  vehicle_profile?: string | null;
  vehicle_label?: string | null;
};

export type ByteProfile = {
  index: number;
  distinct_values: number;
  minimum: number;
  maximum: number;
  toggle_count: number;
  entropy: number;
};

export type CanIdProfile = {
  arbitration_id: number;
  extended: boolean;
  frame_count: number;
  frequency_hz: number;
  dlc_counts: Record<string, number>;
  changing_bytes: number[];
  byte_profiles: ByteProfile[];
  opendbc_message?: string | null;
  opendbc_signals: string[];
};

export type OpendbcSourceInfo = {
  enabled: boolean;
  loaded: boolean;
  database: string;
  revision: string;
  license: string;
  source_url: string;
  compatibility: string;
  message_count: number;
  signal_count: number;
  observed_message_count: number;
  observed_messages: string[];
  decoded_frame_count: number;
  decode_error_count: number;
  error?: string | null;
};

export type OpendbcCatalog = {
  source: OpendbcSourceInfo;
  messages: unknown[];
};

export type SignalCandidate = {
  arbitration_id: number;
  extended: boolean;
  kind: "bit" | "byte" | "frequency" | "dbc_signal";
  byte_index?: number | null;
  bit_index?: number | null;
  before_value: string;
  after_value: string;
  before_samples: number;
  after_samples: number;
  effect: number;
  score: number;
  confidence: "faible" | "moyenne" | "forte";
  rationale: string[];
  source: "statistical" | "opendbc";
  dbc_message?: string | null;
  dbc_signal?: string | null;
  unit?: string | null;
  source_url?: string | null;
};

export type MarkerCorrelation = {
  marker: string;
  notes: string[];
  occurrences: number;
  before_ms: number;
  after_ms: number;
  candidates: SignalCandidate[];
};

export type BehavioralAnalysis = {
  session_id: string;
  generated_at: string;
  total_frames: number;
  unique_ids: number;
  duration_ms: number;
  marker_count: number;
  inventory: CanIdProfile[];
  correlations: MarkerCorrelation[];
  opendbc?: OpendbcSourceInfo | null;
  warnings: string[];
  analysis_path?: string | null;
};

export type ReplaySample = {
  t_ms: number;
  speed_kph?: number | null;
  engine_rpm?: number | null;
  engine_load_pct?: number | null;
  absolute_engine_load_pct?: number | null;
  fuel_pressure_kpa?: number | null;
  manifold_pressure_kpa?: number | null;
  mass_air_flow_g_s?: number | null;
  throttle_position_pct?: number | null;
  relative_throttle_position_pct?: number | null;
  throttle_position_b_pct?: number | null;
  throttle_position_c_pct?: number | null;
  commanded_throttle_actuator_pct?: number | null;
  fiat_throttle_candidate_pct?: number | null;
  fiat_air_load_candidate_raw?: number | null;
  ignition_advance_deg?: number | null;
  fuel_injection_timing_deg?: number | null;
  short_fuel_trim_pct?: number | null;
  long_fuel_trim_pct?: number | null;
  oxygen_sensor_b1s1_v?: number | null;
  oxygen_sensor_b1s2_v?: number | null;
  commanded_equivalence_ratio?: number | null;
  evap_purge_pct?: number | null;
  engine_runtime_s?: number | null;
  fuel_level_pct?: number | null;
  fuel_rate_lph?: number | null;
  steering_angle_deg?: number | null;
  steering_rate_deg_s?: number | null;
  driver_torque?: number | null;
  accelerator_pct?: number | null;
  accelerator_secondary_pct?: number | null;
  relative_accelerator_position_pct?: number | null;
  engine_torque_nm?: number | null;
  idle_setpoint_rpm?: number | null;
  fuel_consumption_candidate_mm3?: number | null;
  virtual_fuel_consumption_candidate_mm3?: number | null;
  current_gear?: number | null;
  target_gear?: number | null;
  gear_shift_active?: boolean | null;
  drivetrain_engaged_state?: number | null;
  longitudinal_accel_ms2?: number | null;
  lateral_accel_ms2?: number | null;
  yaw_rate_deg_s?: number | null;
  brake_active?: boolean | null;
  brake_system_state?: number | null;
  brake_pressure_raw?: number | null;
  turn_signal?: "off" | "right" | "left" | "hazard" | null;
  low_beam?: boolean | null;
  high_beam?: boolean | null;
  reverse?: boolean | null;
  parking_brake?: boolean | null;
  parking_brake_state?: number | null;
  driver_door?: boolean | null;
  passenger_door?: boolean | null;
  rear_left_door?: boolean | null;
  rear_right_door?: boolean | null;
  rear_door_ajar_candidate?: boolean | null;
  front_wiper_status?: number | null;
  fuel_liters_raw?: number | null;
  fuel_liters?: number | null;
  oil_temperature_c?: number | null;
  coolant_temperature_c?: number | null;
  intake_air_temperature_c?: number | null;
  oil_pressure_switch?: boolean | null;
  battery_voltage_v?: number | null;
  battery_temperature_c?: number | null;
  battery_charge_pct?: number | null;
  ambient_temperature_c?: number | null;
  atmospheric_pressure_hpa?: number | null;
  obd_error?: boolean | null;
  mil_on?: boolean | null;
  mil_blinking?: boolean | null;
  esp_acknowledged?: boolean | null;
  esp_fault_state?: number | null;
  esp_intervention_state?: number | null;
  esp_intervention?: boolean | null;
  tcs_intervention?: boolean | null;
  esp_exclusive_intervention?: boolean | null;
  abs_intervention?: boolean | null;
  gearbox_fault?: boolean | null;
  generic_warning_requested?: boolean | null;
  brake_fault?: boolean | null;
  low_fuel_warning?: boolean | null;
  fuel_level_fault_state?: number | null;
  headlamp_fault?: boolean | null;
  driver_seatbelt_state?: number | null;
  passenger_seatbelt_state?: number | null;
  lane_assist_status?: number | null;
  lane_departure?: number | null;
  lka_mode?: number | null;
  lka_active?: boolean | null;
  lka_torque_command_raw?: number | null;
  lka_angle_setpoint_deg?: number | null;
  lka_torque_factor_raw?: number | null;
  acc_mode?: number | null;
  acc_requested?: boolean | null;
  lvv_requested?: boolean | null;
  speed_setpoint_kph?: number | null;
  cruise_probable?: boolean | null;
  cruise_confidence?: number | null;
  cruise_detection_state?: string | null;
  cruise_detection_reason?: string | null;
  cruise_switch_candidate?: boolean | null;
  cruise_xvv_state?: number | null;
  cruise_active_candidate?: boolean | null;
  cruise_mode_raw?: number | null;
  cruise_on?: boolean | null;
  cruise_activation_request?: boolean | null;
  cruise_button_event?: "set_plus" | "set_minus" | "resume" | "cancel" | null;
  cruise_button_event_source?: "setpoint_delta" | "state_transition" | null;
  cruise_setpoint_kph?: number | null;
  cruise_setpoint_direction?: "up" | "down" | null;
  cruise_setpoint_step_kph?: number | null;
  climate_ac_active?: boolean | null;
  climate_ac_power_kw?: number | null;
  interior_temp_candidate_c?: number | null;
  front_sensor_b0_raw?: number | null;
  front_sensor_b2_raw?: number | null;
  front_sensor_b4_raw?: number | null;
  engine_rpm_3b8_candidate?: number | null;
  accelerator_pct_3b8_candidate?: number | null;
  accelerator_pct_2e8_candidate?: number | null;
  engine_state_57c_candidate_raw?: number | null;
  gear_torque_table_2e8_candidate_raw?: number | null;
  speed_389_candidate_raw?: number | null;
  fiat_clock_hour_candidate?: number | null;
  fiat_clock_minute_candidate?: number | null;
  fiat_start_stop_state_raw?: number | null;
  fiat_clutch_pedal_candidate?: boolean | null;
  fiat_battery_voltage_candidate_v?: number | null;
  fiat_a1_fast_nibble_candidate?: number | null;
  fiat_mode_flag_candidate?: boolean | null;
  fiat_mode_analog_candidate_raw?: number | null;
  wheel_front_left_kph?: number | null;
  wheel_front_right_kph?: number | null;
  wheel_rear_left_kph?: number | null;
  wheel_rear_right_kph?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  gps_accuracy_m?: number | null;
  gps_altitude_m?: number | null;
  gps_heading_deg?: number | null;
  gps_speed_kph?: number | null;
  x_m: number;
  y_m: number;
  heading_deg: number;
  distance_m: number;
};

export type ReplayEvent = {
  t_ms: number;
  kind: string;
  label: string;
  value?: string | number | boolean | null;
};

export type ReplayData = {
  version: number;
  session_id: string;
  name: string;
  vehicle: string;
  vin?: string | null;
  vehicle_profile?: string | null;
  source: string;
  source_size_bytes: number;
  start_timestamp_us: number;
  duration_ms: number;
  sample_period_ms: number;
  frame_count: number;
  decoded_frame_count: number;
  max_speed_kph: number;
  average_moving_speed_kph: number;
  distance_km: number;
  estimated_fuel_consumption_l_100km?: number | null;
  fuel_consumption_note?: string | null;
  gps_available: boolean;
  gps_point_count: number;
  route_method: string;
  steering_zero_offset_deg: number;
  route_bounds: Record<string, number>;
  available_fields: string[];
  field_quality: Record<string, string>;
  warnings: string[];
  events: ReplayEvent[];
  gps_points: Array<{
    t_ms: number;
    timestamp_us: number;
    latitude: number;
    longitude: number;
    accuracy_m: number;
    altitude_m?: number | null;
    altitude_accuracy_m?: number | null;
    heading_deg?: number | null;
    speed_kph?: number | null;
  }>;
  points: ReplaySample[];
};

export type SignalValidation = {
  key: string;
  label: string;
  status: "validated" | "plausible" | "candidate" | "suspicious" | "unavailable";
  sample_count: number;
  minimum?: number | null;
  maximum?: number | null;
  transitions: number;
  evidence: string[];
  manual_validation?: boolean | null;
};

export type ReplayValidation = {
  version: number;
  session_id: string;
  generated_at: string;
  signal_count: number;
  validated_count: number;
  plausible_count: number;
  suspicious_count: number;
  signals: SignalValidation[];
  warnings: string[];
};

export type RouteGeometry = {
  path: string;
  coordinates: { x: number; y: number }[];
  gpsCoordinates: { x: number; y: number; accuracyPx: number }[];
  mapTiles: { key: string; href: string; x: number; y: number }[];
  mapZoom: number | null;
};

export type ReplayGaugeDefinition = {
  key: keyof ReplaySample;
  label: string;
  unit: string;
  minimum: number;
  maximum: number;
  precision?: number;
  color: string;
  note: string;
  status?: boolean;
  rejected?: boolean;
  experimental?: boolean;
};

export type ReplayIndicatorColor = "red" | "amber" | "green" | "blue";

export type ReplayIndicatorDefinition = {
  key: string;
  label: string;
  color: ReplayIndicatorColor;
  icon: string;
  fields: (keyof ReplaySample)[];
  note: string;
  referenceOnly?: boolean;
};

export type ReplayIndicatorState = {
  available: boolean;
  active: boolean | null;
  detail: string;
  inferred?: boolean;
};

export type ReplayGraphGeometry = {
  path: string;
  minimum: number;
  maximum: number;
};

export type VehicleVisualProfile = {
  label: string;
  topImage: string;
  steeringImage: string;
  topAlt: string;
  steeringAlt: string;
  frontAtTop: boolean;
};

export type StudioWidgetKind = "speed" | "steering" | "gear" | "vehicle" | "capture" | "gauge" | "graph" | "numeric" | "lamp" | "indicator";

export type StudioSensorStyle = "gauge" | "graph" | "numeric" | "lamp";

export type StudioGraphWindowSeconds = 10 | 30 | 60 | 300;

export type StudioWidget = {
  id: string;
  kind: StudioWidgetKind;
  key?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  windowSeconds?: StudioGraphWindowSeconds;
};
