import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { sensorCandidatesForProfile } from "./sensorInventory";
import type { PowertrainProfile } from "./sensorInventory";

type Status = {
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
  vehicle_profile: string;
  gateway_endpoint?: string | null;
  gateway_verified?: boolean;
  gateway_hello?: Record<string, unknown> | null;
  gateway_error?: string | null;
  operating_mode?: "read_only" | "maintenance";
  runtime_mode_switch_enabled?: boolean;
};

type OperatingModeState = {
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
  };
};

type TransportOption = {
  id: string;
  transport: "esp32_serial" | "esp32_wifi";
  endpoint: string;
  label: string;
  detected?: boolean | null;
  baud?: number | null;
};

type TransportConnection = {
  verified: boolean;
  transport?: string | null;
  endpoint?: string | null;
  verified_at?: string | null;
  hello?: Record<string, unknown> | null;
  error?: string | null;
};

type TransportCatalog = {
  options: TransportOption[];
  current_id?: string | null;
  capture_active: boolean;
  connection: TransportConnection;
};

type TelecodingParameterValue = {
  key: string;
  name: string;
  byte: number;
  raw_hex: string;
  value?: string | null;
};

type TelecodingZoneInfo = {
  did: number;
  name: string;
  family: string;
  parameters: TelecodingParameterValue[];
  source?: string | null;
  confidence: string;
};

type DidValue = {
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

type ProbeAttempt = {
  request_hex: string;
  response_hex?: string | null;
  outcome: "positive" | "negative_response" | "timeout";
  nrc?: number | null;
  nrc_name?: string | null;
  error?: string | null;
};

type DtcValue = {
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

type DtcSnapshotResult = {
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

type DidSweepHit = {
  did: number;
  outcome: "positive" | "negative_response";
  raw_hex?: string | null;
  response_hex?: string | null;
  nrc?: number | null;
  nrc_name?: string | null;
  telecoding?: TelecodingZoneInfo | null;
};

type DidSweepResult = {
  ecu_key: string;
  did_start: number;
  did_end: number;
  scanned_count: number;
  hits: DidSweepHit[];
  unsupported_count: number;
  timeout_count: number;
};

type ObservedDtc = {
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

type Ecu = {
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

type DebugSummary = {
  session_id?: string | null;
  trace_file?: string | null;
  duration_ms: number;
  event_count: number;
  dropped_events: number;
  event_types: Record<string, number>;
};

type Report = {
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

type DtcChange = {
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

type DiagnosticVehicle = {
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

type VehicleTimelineEntry = {
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

type DiagnosticReportSummary = {
  scan_id: string;
  scanned_at: string;
  vin: string;
  vehicle_profile: string;
  manufacturer?: string | null;
  model?: string | null;
  dtc_summary: Report["dtc_summary"];
  detected_ecus: number;
};

type DiagnosticSensorCatalogEntry = {
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

type DiagnosticSensorValue = {
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

type TraceImportResult = {
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

type RegressionResult = {
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

type ClearDtcResult = {
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

type DiagnosticSensorSnapshot = {
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

type VehicleProfileSummary = {
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

type VehicleIdentityAttempt = {
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

type VehicleIdentityField = {
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

type VehicleIdentityResult = {
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

type PsaSecurityKey = { variant: string; key_hex: string };
type PsaAdvancedEcu = {
  key: string;
  name: string;
  family?: string | null;
  request_id?: number | null;
  response_id?: number | null;
  protocol: string;
  optional: boolean;
  security_keys: PsaSecurityKey[];
};
type PsaAdvancedAction = {
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
type PsaAdvancedCatalog = {
  enabled: boolean;
  security_access_enabled: boolean;
  actuator_enabled: boolean;
  read_only: boolean;
  can_tx_enabled: boolean;
  required_firmware_policy: string;
  wiring: { vehicle_can: string; standard_obd: string; source: string; warning: string };
  ecus: PsaAdvancedEcu[];
  actions: PsaAdvancedAction[];
  sources: string[];
};
type PsaSeedKeyResult = {
  seed_hex: string;
  application_key_hex: string;
  response_key_hex: string;
  source: string;
  transmitted: boolean;
};
type PsaActionResult = {
  action_key: string;
  executed: boolean;
  started_response_hex?: string | null;
  stopped_response_hex?: string | null;
  duration_ms: number;
  message: string;
  session_id?: string | null;
};

type MaintenanceService = {
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

type MaintenanceCatalog = {
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
type PsaUnlockResult = {
  ecu_key: string;
  unlocked: boolean;
  seed_hex: string;
  response_key_hex: string;
  response_hex: string;
  message: string;
  session_id?: string | null;
};

type SensorInventoryStatus = "measured" | "supported" | "to_test" | "to_observe" | "to_decode" | "unsupported" | "not_applicable";
type SensorInventoryRow = {
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

type PassiveCanSignal = {
  key: string;
  arbitration_id: number;
  message: string;
  signal: string;
  display_name: string;
  description: string;
  category: string;
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

type PassiveSteeringSnapshot = {
  detected: boolean;
  angle_degrees?: number | null;
  rate_degrees_s?: number | null;
  driver_torque?: number | null;
  angle_source?: string | null;
  torque_source?: string | null;
  warning?: string | null;
};

type PassiveSensorSnapshot = {
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

type LiveSensorDefinition = {
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

type CaptureStatus = {
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

type DiscoverySession = {
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

type ByteProfile = {
  index: number;
  distinct_values: number;
  minimum: number;
  maximum: number;
  toggle_count: number;
  entropy: number;
};

type CanIdProfile = {
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

type OpendbcSourceInfo = {
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

type OpendbcCatalog = {
  source: OpendbcSourceInfo;
  messages: unknown[];
};

type SignalCandidate = {
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

type MarkerCorrelation = {
  marker: string;
  notes: string[];
  occurrences: number;
  before_ms: number;
  after_ms: number;
  candidates: SignalCandidate[];
};

type BehavioralAnalysis = {
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

type ReplaySample = {
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
  driver_door?: boolean | null;
  passenger_door?: boolean | null;
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
  esp_fault_state?: number | null;
  esp_intervention?: boolean | null;
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
  lka_active?: boolean | null;
  acc_mode?: number | null;
  acc_requested?: boolean | null;
  speed_setpoint_kph?: number | null;
  cruise_probable?: boolean | null;
  cruise_confidence?: number | null;
  cruise_detection_state?: string | null;
  cruise_detection_reason?: string | null;
  cruise_switch_candidate?: boolean | null;
  cruise_xvv_state?: number | null;
  cruise_active_candidate?: boolean | null;
  cruise_setpoint_kph?: number | null;
  climate_ac_active?: boolean | null;
  climate_ac_power_kw?: number | null;
  interior_temp_candidate_c?: number | null;
  climate_air_temp_candidate_c?: number | null;
  front_sensor_b0_raw?: number | null;
  front_sensor_b2_raw?: number | null;
  front_sensor_b4_raw?: number | null;
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

type ReplayEvent = {
  t_ms: number;
  kind: string;
  label: string;
  value?: string | number | boolean | null;
};

type ReplayData = {
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

type SignalValidation = {
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

type ReplayValidation = {
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

type RouteGeometry = {
  path: string;
  coordinates: { x: number; y: number }[];
  gpsCoordinates: { x: number; y: number; accuracyPx: number }[];
  mapTiles: { key: string; href: string; x: number; y: number }[];
  mapZoom: number | null;
};

type ReplayGaugeDefinition = {
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

const replayGaugeCatalog: ReplayGaugeDefinition[] = [
  { key: "speed_kph", label: "Vitesse véhicule", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#62e39a", note: "Vitesse véhicule calculée à partir des roues ABS." },
  { key: "engine_rpm", label: "Régime moteur", unit: "tr/min", minimum: 0, maximum: 6500, color: "#8ce9b4", note: "Régime moteur diffusé par le calculateur moteur." },
  { key: "engine_load_pct", label: "Charge moteur", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#ff8d72", note: "Charge moteur calculée normalisée EOBD 01/04." },
  { key: "absolute_engine_load_pct", label: "Charge moteur absolue", unit: "%", minimum: 0, maximum: 150, precision: 1, color: "#ffb45f", note: "Charge absolue normalisée EOBD 01/43." },
  { key: "fuel_pressure_kpa", label: "Pression carburant basse", unit: "kPa", minimum: 0, maximum: 765, precision: 0, color: "#f2cc60", note: "Pression carburant relative EOBD 01/0A, uniquement si l'ECU Fiat l'annonce." },
  { key: "manifold_pressure_kpa", label: "Pression collecteur", unit: "kPa abs", minimum: 20, maximum: 110, precision: 0, color: "#72c6ff", note: "Capteur MAP normalisé EOBD 01/0B; particulièrement pertinent sur le 1.2 FIRE." },
  { key: "mass_air_flow_g_s", label: "Débit d'air massique", unit: "g/s", minimum: 0, maximum: 150, precision: 2, color: "#63e6e2", note: "Débit d'air MAF EOBD 01/10 lorsqu'un débitmètre est exposé." },
  { key: "throttle_position_pct", label: "Position papillon", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#62e39a", note: "Position absolue du papillon EOBD 01/11." },
  { key: "relative_throttle_position_pct", label: "Position relative papillon", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#8ce9b4", note: "Ouverture relative du papillon EOBD 01/45." },
  { key: "throttle_position_b_pct", label: "Papillon voie B", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#59a8ff", note: "Seconde piste de position du papillon EOBD 01/47." },
  { key: "throttle_position_c_pct", label: "Papillon voie C", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#89d7ff", note: "Troisième piste de position du papillon EOBD 01/48 lorsqu'elle existe." },
  { key: "commanded_throttle_actuator_pct", label: "Commande actionneur papillon", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#b8efc9", note: "Consigne envoyée au papillon motorisé EOBD 01/4C." },
  { key: "fiat_throttle_candidate_pct", label: "Papillon CAN Fiat candidat", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#62e39a", note: "Octet 7 de 0x0618A001 mis à l'échelle 0…100 %. À comparer au papillon EOBD 01/11." },
  { key: "fiat_air_load_candidate_raw", label: "Charge d'air Fiat candidate", unit: "brut", minimum: 0, maximum: 255, precision: 0, color: "#72c6ff", note: "Octet 4 de 0x0618A001. Sa dynamique suit l'admission, mais aucune unité physique n'est encore attribuée." },
  { key: "ignition_advance_deg", label: "Avance à l'allumage", unit: "°", minimum: -20, maximum: 60, precision: 1, color: "#b384ff", note: "Avance d'allumage essence EOBD 01/0E." },
  { key: "fuel_injection_timing_deg", label: "Calage d'injection", unit: "°", minimum: -90, maximum: 90, precision: 1, color: "#ff8ec7", note: "Calage normalisé de l'injection EOBD 01/5D si pris en charge." },
  { key: "short_fuel_trim_pct", label: "Correction richesse court terme", unit: "%", minimum: -25, maximum: 25, precision: 1, color: "#f2cc60", note: "STFT banque 1 normalisée EOBD 01/06." },
  { key: "long_fuel_trim_pct", label: "Correction richesse long terme", unit: "%", minimum: -25, maximum: 25, precision: 1, color: "#ffb45f", note: "LTFT banque 1 normalisée EOBD 01/07." },
  { key: "oxygen_sensor_b1s1_v", label: "Lambda amont B1S1", unit: "V", minimum: 0, maximum: 1.1, precision: 3, color: "#63e6e2", note: "Tension de la sonde amont EOBD 01/14 lorsqu'elle est exposée." },
  { key: "oxygen_sensor_b1s2_v", label: "Lambda aval B1S2", unit: "V", minimum: 0, maximum: 1.1, precision: 3, color: "#89d7ff", note: "Tension de la sonde aval EOBD 01/15 lorsqu'elle est exposée." },
  { key: "commanded_equivalence_ratio", label: "Richesse commandée", unit: "λ", minimum: .7, maximum: 1.3, precision: 3, color: "#b8efc9", note: "Rapport lambda commandé EOBD 01/44." },
  { key: "evap_purge_pct", label: "Purge canister", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#a7c7e7", note: "Commande de purge des vapeurs d'essence EOBD 01/2E." },
  { key: "engine_runtime_s", label: "Temps moteur", unit: "s", minimum: 0, maximum: 7200, precision: 0, color: "#8ce9b4", note: "Temps écoulé depuis le démarrage EOBD 01/1F." },
  { key: "fuel_level_pct", label: "Niveau carburant", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#f2cc60", note: "Niveau déclaré en EOBD 01/2F si le calculateur Fiat le relaie." },
  { key: "fuel_rate_lph", label: "Débit carburant", unit: "L/h", minimum: 0, maximum: 30, precision: 2, color: "#ff8d72", note: "Débit carburant normalisé EOBD 01/5E si pris en charge." },
  { key: "idle_setpoint_rpm", label: "Consigne de ralenti", unit: "tr/min", minimum: 650, maximum: 1100, color: "#b8efc9", note: "Consigne du calculateur moteur, validée par comparaison avec le régime réel au ralenti." },
  { key: "current_gear", label: "Rapport engagé", unit: "rapport", minimum: 0, maximum: 9, color: "#f2cc60", note: "Rapport réellement engagé diffusé par le calculateur moteur. Sur cette capture, le code 9 correspond à la marche arrière." },
  { key: "target_gear", label: "Rapport cible", unit: "rapport", minimum: 0, maximum: 9, color: "#ffb45f", note: "Rapport demandé pendant la stratégie de changement de vitesse. Le code 9 est affiché R." },
  { key: "steering_angle_deg", label: "Angle du volant", unit: "°", minimum: -540, maximum: 540, precision: 1, color: "#b384ff", note: "Angle du volant validé sur ce véhicule; négatif vers la droite." },
  { key: "brake_pressure_raw", label: "Pression de freinage brute", unit: "brut", minimum: 0, maximum: 255, color: "#ff6b65", note: "Signal de freinage non calibré : aucune unité physique ne doit être déduite." },
  { key: "oil_temperature_c", label: "Température d'huile", unit: "°C", minimum: 40, maximum: 150, color: "#ffb45f", note: "Température du carter moteur issue du message Dat_CMM." },
  { key: "coolant_temperature_c", label: "Liquide de refroidissement", unit: "°C", minimum: 40, maximum: 120, color: "#59a8ff", note: "Température d'eau moteur diffusée par le calculateur." },
  { key: "oil_pressure_switch", label: "Contacteur pression d'huile", unit: "état", minimum: 0, maximum: 1, color: "#ffcf66", note: "Signal logique uniquement : aucune pression en bar n'est disponible.", status: true },
  { key: "battery_voltage_v", label: "Tension batterie", unit: "V", minimum: 10, maximum: 15, precision: 2, color: "#62e39a", note: "Tension brute du réseau électrique diffusée par le BSI." },
  { key: "battery_charge_pct", label: "Charge batterie", unit: "%", minimum: 0, maximum: 100, color: "#8ce9b4", note: "Estimation de charge batterie du BSI." },
  { key: "battery_temperature_c", label: "Température batterie", unit: "°C", minimum: -20, maximum: 80, color: "#89d7ff", note: "Température batterie candidate OpenDBC." },
  { key: "ambient_temperature_c", label: "Température extérieure", unit: "°C", minimum: -20, maximum: 50, precision: 1, color: "#8fdcff", note: "Température ambiante diffusée à 1 Hz." },
  { key: "intake_air_temperature_c", label: "Air d'admission", unit: "°C", minimum: -20, maximum: 100, color: "#b384ff", note: "Température d'air à l'admission moteur." },
  { key: "atmospheric_pressure_hpa", label: "Pression atmosphérique", unit: "hPa", minimum: 850, maximum: 1100, color: "#a7c7e7", note: "Pression environnementale candidate OpenDBC." },
  { key: "fuel_liters", label: "Niveau carburant filtré", unit: "L", minimum: 0, maximum: 53, precision: 1, color: "#f2cc60", note: "Mesure du flotteur amortie sur 120 s pour réduire le ballottement; l'étalonnage absolu reste à confirmer." },
  { key: "engine_torque_nm", label: "Couple moteur", unit: "Nm", minimum: -100, maximum: 400, color: "#ff8d72", note: "Estimation de couple moteur réel." },
  { key: "accelerator_pct", label: "Accélérateur · voie D", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#62e39a", note: "Position de pédale; sur la Fiat, voie normalisée EOBD 01/49." },
  { key: "accelerator_secondary_pct", label: "Accélérateur · voie E", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#8ce9b4", note: "Seconde voie redondante de la pédale EOBD 01/4A." },
  { key: "relative_accelerator_position_pct", label: "Accélérateur relatif", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#b8efc9", note: "Position relative de l'accélérateur EOBD 01/5A." },
  { key: "cruise_xvv_state", label: "Régulateur · état brut", unit: "code", minimum: 0, maximum: 3, color: "#f2cc60", note: "0x208 Dyn_CMM, octet 4 bits 2-3 : 0 inactif, 2 actif, 3 transitoire (bascule). Candidat confirmé par corrélation sur plusieurs essais.", experimental: true },
  { key: "cruise_active_candidate", label: "Régulateur", unit: "état", minimum: 0, maximum: 1, color: "#62e39a", note: "Actif quand cruise_xvv_state = 2.", status: true, experimental: true },
  { key: "cruise_setpoint_kph", label: "Régulateur · consigne", unit: "km/h", minimum: 0, maximum: 150, precision: 0, color: "#89d7ff", note: "0x50E Dat_CLIM.P219_Com_xPrpReqRaw (255 = inactif). Confirmé sur 5 engagements, 4 essais indépendants.", experimental: true },
  { key: "climate_ac_active", label: "Climatisation active", unit: "état", minimum: 0, maximum: 1, color: "#59a8ff", note: "0x50E Dat_CLIM.P050_Com_stAC.", status: true },
  { key: "climate_ac_power_kw", label: "Climatisation · puissance", unit: "kW", minimum: 0, maximum: 6.4, precision: 2, color: "#59a8ff", note: "0x50E Dat_CLIM.P210_Com_pwrACDem × 0.025." },
  { key: "interior_temp_candidate_c", label: "Température intérieure (candidat)", unit: "°C", minimum: 0, maximum: 40, precision: 1, color: "#8fdcff", note: "0x3B8 octet 2, non documenté. Dérive lente et plage plausible sur un essai ; non validé.", experimental: true },
  { key: "climate_air_temp_candidate_c", label: "Climatisation · air soufflé (candidat)", unit: "°C", minimum: 0, maximum: 40, precision: 1, color: "#8fdcff", note: "0x3B8 octet 3, non documenté. Toujours ≥ à la température intérieure candidate, souvent invalide (0xFF). Varie trop pour une simple consigne ; probablement l'air mélangé/soufflage. Non validé.", experimental: true },
  { key: "front_sensor_b0_raw", label: "Radar avant · octet 0", unit: "brut", minimum: 0, maximum: 255, color: "#ff8ec7", note: "0x489 octet 0, non documenté. Candidat très précoce, non validé.", experimental: true },
  { key: "front_sensor_b2_raw", label: "Radar avant · octet 2", unit: "brut", minimum: 0, maximum: 255, color: "#ff8ec7", note: "0x489 octet 2, non documenté. Candidat très précoce, non validé.", experimental: true },
  { key: "front_sensor_b4_raw", label: "Radar avant · octet 4", unit: "brut", minimum: 0, maximum: 32, color: "#ff8ec7", note: "0x489 octet 4, non documenté. Bascule par à-coups dont la cadence semble suivre la proximité sur deux essais dédiés ; à confirmer.", experimental: true },
  { key: "fiat_clock_hour_candidate", label: "Fiat · horloge (heure)", unit: "h", minimum: 0, maximum: 23, color: "#89d7ff", note: "0x0C28A000 octet 0, BCD. Auto-validé : incrémente avec la minute.", experimental: true },
  { key: "fiat_clock_minute_candidate", label: "Fiat · horloge (minute)", unit: "min", minimum: 0, maximum: 59, color: "#89d7ff", note: "0x0C28A000 octet 1, BCD. Incrémente de +1 toutes les 60s réelles observées.", experimental: true },
  { key: "fiat_start_stop_state_raw", label: "Fiat · état Start&Stop", unit: "code", minimum: 0, maximum: 5, color: "#f2cc60", note: "0x0C1CA000 octet 1, brut. Un seul changement observé (coupure contact) ; à confirmer.", experimental: true },
  { key: "fiat_clutch_pedal_candidate", label: "Fiat · pédale d'embrayage", unit: "état", minimum: 0, maximum: 1, color: "#62e39a", note: "0x0628A001 octet 5 = 0x10. Impulsions brèves cohérentes avec des changements de rapport.", status: true, experimental: true },
  { key: "fiat_battery_voltage_candidate_v", label: "Fiat · tension batterie", unit: "V", minimum: 10, maximum: 15, precision: 1, color: "#62e39a", note: "0x0628A001 octet 3 × 0.1. Stable à 12.8V, avec de brefs écarts (11.6-13.8V) pile aux mêmes instants que la pédale d'embrayage.", experimental: true },
  { key: "fiat_a1_fast_nibble_candidate", label: "Fiat · 0x0A18A001 nibble rapide", unit: "brut", minimum: 0, maximum: 15, color: "#ff8ec7", note: "Change toutes les 100-300 ms : trop rapide pour un rapport de boîte, signification inconnue.", experimental: true },
  { key: "fiat_mode_flag_candidate", label: "Fiat · drapeau de mode", unit: "état", minimum: 0, maximum: 1, color: "#b384ff", note: "0x0A18A001 octet 4. Bascule par blocs de 1-2 minutes ; hypothèse : climatisation ou ralenti.", status: true, experimental: true },
  { key: "fiat_mode_analog_candidate_raw", label: "Fiat · valeur liée au mode", unit: "brut", minimum: 0, maximum: 255, color: "#b384ff", note: "0x0A18A001 octet 5. Plage très différente selon le drapeau de mode ; signification inconnue.", experimental: true },
  { key: "longitudinal_accel_ms2", label: "Accélération longitudinale", unit: "m/s²", minimum: -4, maximum: 4, precision: 2, color: "#72c6ff", note: "Accélération calculée à partir des roues." },
  { key: "lateral_accel_ms2", label: "Accélération latérale", unit: "m/s²", minimum: -5, maximum: 5, precision: 2, color: "#ff8ec7", note: "Trame 0x3CD, échelle 0,05 m/s² validée par corrélation avec les quatre roues et le volant." },
  { key: "yaw_rate_deg_s", label: "Vitesse de lacet", unit: "°/s", minimum: -40, maximum: 40, precision: 1, color: "#63e6e2", note: "Trame 0x3CD, échelle 0,1°/s validée par deux références CAN indépendantes." },
  { key: "driver_torque", label: "Effort au volant", unit: "brut", minimum: -60, maximum: 60, color: "#b5a2ff", note: "Valeur de colonne validée mais non calibrée en N·m." },
  { key: "steering_rate_deg_s", label: "Vitesse du volant", unit: "°/s", minimum: -120, maximum: 120, color: "#b384ff", note: "Vitesse et sens de rotation du volant." },
  { key: "wheel_front_left_kph", label: "Roue avant gauche", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
  { key: "wheel_front_right_kph", label: "Roue avant droite", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
  { key: "wheel_rear_left_kph", label: "Roue arrière gauche", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
  { key: "wheel_rear_right_kph", label: "Roue arrière droite", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
];

const defaultReplayGaugeKeys = [
  "oil_temperature_c",
  "coolant_temperature_c",
  "oil_pressure_switch",
  "battery_voltage_v",
];

type ReplayIndicatorColor = "red" | "amber" | "green" | "blue";
type ReplayIndicatorDefinition = {
  key: string;
  label: string;
  color: ReplayIndicatorColor;
  icon: string;
  fields: (keyof ReplaySample)[];
  note: string;
  referenceOnly?: boolean;
};

type ReplayIndicatorState = {
  available: boolean;
  active: boolean | null;
  detail: string;
  inferred?: boolean;
};

const laneAssistStatusLabels: Record<number, string> = {
  0: "Indisponible",
  1: "Non sélectionné",
  2: "Sélectionné",
  3: "Autorisé",
  4: "Actif",
  5: "Défaut",
  6: "Collision détectée",
  7: "Réservé",
};

function laneAssistStatusLabel(status?: number | null): string {
  return typeof status === "number"
    ? laneAssistStatusLabels[status] ?? `État inconnu ${status}`
    : "État absent";
}

const cruiseXvvStateLabels: Record<number, string> = {
  0: "Inactif",
  2: "Actif",
  3: "Transitoire",
};

function cruiseXvvStateLabel(state?: number | null): string {
  return typeof state === "number"
    ? cruiseXvvStateLabels[state] ?? `État inconnu ${state}`
    : "Signal absent";
}

type ReplayGraphGeometry = {
  path: string;
  minimum: number;
  maximum: number;
};

const replayIndicatorCatalog: ReplayIndicatorDefinition[] = [
  { key: "turn_left", label: "Clignotant gauche", color: "green", icon: "arrow-left", fields: ["turn_signal"], note: "Commande de clignotant enregistrée." },
  { key: "turn_right", label: "Clignotant droit", color: "green", icon: "arrow-right", fields: ["turn_signal"], note: "Commande de clignotant enregistrée." },
  { key: "low_beam", label: "Feux de croisement", color: "green", icon: "low-beam", fields: ["low_beam"], note: "État des feux de croisement." },
  { key: "high_beam", label: "Feux de route", color: "blue", icon: "high-beam", fields: ["high_beam"], note: "État des feux de route." },
  { key: "parking_brake", label: "Frein de stationnement", color: "red", icon: "parking", fields: ["parking_brake"], note: "État candidat du frein de stationnement." },
  { key: "brake_fault", label: "Défaut freinage", color: "red", icon: "brake", fields: ["brake_fault"], note: "Demande de témoin de défaut du frein principal." },
  { key: "abs", label: "ABS", color: "amber", icon: "abs", fields: ["abs_intervention"], note: "La capture expose l'intervention ABS, pas un défaut ABS confirmé." },
  { key: "esp", label: "ESP / antipatinage", color: "amber", icon: "esp", fields: ["esp_fault_state", "esp_intervention"], note: "Défaut ou intervention ESP selon les états CAN candidats." },
  { key: "oil_pressure", label: "Contacteur d'huile", color: "red", icon: "oil", fields: ["oil_pressure_switch"], note: "Contacteur logique brut; aucune pression en bar n'est disponible." },
  { key: "coolant", label: "Température moteur", color: "red", icon: "coolant", fields: ["coolant_temperature_c"], note: "Alerte visuelle estimée à partir de la température mesurée." },
  { key: "battery", label: "Charge batterie", color: "red", icon: "battery", fields: ["battery_voltage_v", "engine_rpm"], note: "Alerte estimée si la tension est basse moteur tournant." },
  { key: "fuel", label: "Réserve carburant", color: "amber", icon: "fuel", fields: ["low_fuel_warning"], note: "Demande de témoin de niveau carburant minimal." },
  { key: "engine", label: "Voyant moteur", color: "amber", icon: "engine", fields: ["mil_on", "mil_blinking", "obd_error"], note: "États OBD/MIL candidats diffusés par le moteur." },
  { key: "door", label: "Porte ouverte", color: "red", icon: "door", fields: ["driver_door", "passenger_door"], note: "Ouverture des portes avant enregistrée." },
  { key: "seatbelt", label: "Ceintures", color: "red", icon: "seatbelt", fields: ["driver_seatbelt_state", "passenger_seatbelt_state"], note: "États bruts présents; leur codage exact reste à valider." },
  { key: "lane", label: "Aide au maintien de voie", color: "green", icon: "lane", fields: ["lka_active", "lane_departure", "lane_assist_status"], note: "Activation ou alerte de franchissement de ligne." },
  { key: "lane_fault", label: "Défaut aide à la conduite", color: "amber", icon: "lane", fields: ["lane_assist_status"], note: "STATUS 5 = DEFECT dans la définition CAN observée sur cette 308." },
  { key: "reverse", label: "Marche arrière", color: "green", icon: "reverse", fields: ["reverse"], note: "État de marche arrière candidat BSI." },
  { key: "headlamp_fault", label: "Défaut d'éclairage", color: "amber", icon: "bulb", fields: ["headlamp_fault"], note: "Défaut déclaré sur un feu de croisement ou de route." },
  { key: "gearbox", label: "Défaut boîte", color: "amber", icon: "gearbox", fields: ["gearbox_fault"], note: "État de défaut système de boîte candidat." },
  { key: "stop", label: "STOP", color: "red", icon: "stop", fields: ["generic_warning_requested"], note: "Requête générique de lampe d'alerte issue du calculateur ABS." },
  { key: "front_fog", label: "Antibrouillard avant", color: "green", icon: "fog", fields: [], note: "Témoin classique; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "rear_fog", label: "Antibrouillard arrière", color: "amber", icon: "fog", fields: [], note: "Témoin classique; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "airbag", label: "Airbag", color: "red", icon: "airbag", fields: [], note: "Témoin classique; aucun état airbag fiable dans ce replay.", referenceOnly: true },
  { key: "tire_pressure", label: "Pression des pneus", color: "amber", icon: "tpms", fields: [], note: "Témoin classique; signal TPMS absent de cet enregistrement.", referenceOnly: true },
  { key: "power_steering", label: "Direction assistée", color: "red", icon: "steering", fields: [], note: "Témoin classique; aucun défaut de direction enregistré.", referenceOnly: true },
  { key: "service", label: "Service", color: "amber", icon: "service", fields: [], note: "Témoin classique; état d'entretien absent du replay.", referenceOnly: true },
  { key: "adblue", label: "AdBlue / SCR", color: "amber", icon: "adblue", fields: [], note: "Témoin classique diesel; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "glow_plug", label: "Préchauffage diesel", color: "amber", icon: "glow", fields: [], note: "Témoin classique diesel; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "washer", label: "Lave-glace", color: "amber", icon: "washer", fields: [], note: "Témoin classique; niveau de lave-glace non enregistré.", referenceOnly: true },
];

const defaultReplayGraphKeys = ["speed_kph", "engine_rpm", "steering_angle_deg", "oil_temperature_c"];
const defaultReplayIndicatorKeys = [
  "turn_left", "turn_right", "low_beam", "high_beam", "parking_brake", "brake_fault",
  "abs", "esp", "oil_pressure", "coolant", "battery", "fuel", "engine", "door", "seatbelt", "lane", "lane_fault",
];

const PEUGEOT_308_HANDBOOK_URL = "https://public.servicebox.peugeot.com/APddb/modeles/308n/eGuide_308n_308_ed01-18_dag/pdfs/9999_9999_226_en-GB.pdf";
const FIAT_500_HANDBOOK_URL = "https://aftersales.fiat.com/eLumData/EN/00/150_500/00_150_500_603.81.684_EN_01_02.10_L_LG/00_150_500_603.81.684_EN_01_02.10_L_LG.pdf";

type VehicleVisualProfile = {
  label: string;
  topImage: string;
  steeringImage: string;
  topAlt: string;
  steeringAlt: string;
  frontAtTop: boolean;
};

const PEUGEOT_308_VISUAL: VehicleVisualProfile = {
  label: "Peugeot 308",
  topImage: "/peugeot-308-top.png",
  steeringImage: "/peugeot-308-gt-steering.png",
  topAlt: "Peugeot 308 vue du dessus",
  steeringAlt: "Volant Peugeot 308 GT",
  frontAtTop: false,
};

const FIAT_500_VISUAL: VehicleVisualProfile = {
  label: "Fiat 500",
  topImage: "/fiat-500-top.png",
  steeringImage: "/fiat-500-steering.png",
  topAlt: "Fiat 500 vue du dessus",
  steeringAlt: "Volant Fiat 500",
  frontAtTop: true,
};

function vehicleVisualForProfile(profileKey?: string | null): VehicleVisualProfile {
  return profileKey === "fiat_500_generic" ? FIAT_500_VISUAL : PEUGEOT_308_VISUAL;
}

type StudioWidgetKind = "speed" | "steering" | "gear" | "vehicle" | "capture" | "gauge" | "graph" | "numeric" | "lamp" | "indicator";
type StudioSensorStyle = "gauge" | "graph" | "numeric" | "lamp";
type StudioGraphWindowSeconds = 10 | 30 | 60 | 300;
type StudioWidget = {
  id: string;
  kind: StudioWidgetKind;
  key?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  windowSeconds?: StudioGraphWindowSeconds;
};

const STUDIO_COLUMNS = 12;
const STUDIO_ROW_HEIGHT = 68;
const STUDIO_GRAPH_WINDOWS: StudioGraphWindowSeconds[] = [10, 30, 60, 300];
const defaultStudioWidgets: StudioWidget[] = [
  { id: "studio-speed", kind: "speed", x: 0, y: 0, w: 3, h: 4 },
  { id: "studio-steering", kind: "steering", x: 3, y: 0, w: 3, h: 4 },
  { id: "studio-gear", kind: "gear", x: 6, y: 0, w: 2, h: 4 },
  { id: "studio-vehicle", kind: "vehicle", x: 8, y: 0, w: 4, h: 6 },
  { id: "studio-speed-graph", kind: "graph", key: "speed_kph", x: 0, y: 4, w: 4, h: 3, windowSeconds: 60 },
  { id: "studio-oil", kind: "gauge", key: "oil_temperature_c", x: 4, y: 4, w: 2, h: 3 },
  { id: "studio-engine-light", kind: "indicator", key: "engine", x: 6, y: 4, w: 2, h: 2 },
  { id: "studio-lane-fault", kind: "indicator", key: "lane_fault", x: 6, y: 6, w: 2, h: 2 },
  { id: "studio-capture", kind: "capture", x: 0, y: 7, w: 6, h: 2 },
  { id: "studio-rpm", kind: "gauge", key: "engine_rpm", x: 6, y: 8, w: 3, h: 3 },
  { id: "studio-battery", kind: "gauge", key: "battery_voltage_v", x: 9, y: 8, w: 3, h: 3 },
];

type View = "dashboard" | "garage" | "studio" | "replay" | "sensors" | "inventory" | "identity" | "injection" | "maintenance" | "psa" | "ecus" | "dtcs" | "discovery" | "database" | "security";
type NavModule = "diagnostic" | "atelier" | "learn";

const views: View[] = ["dashboard", "garage", "studio", "replay", "sensors", "inventory", "identity", "injection", "maintenance", "psa", "ecus", "dtcs", "discovery", "database", "security"];
const LAB_MODE = new URLSearchParams(window.location.search).get("lab") === "1"
  || import.meta.env.VITE_LAB_MODE === "true";

function initialView(): View {
  const requested = new URLSearchParams(window.location.search).get("view");
  if (requested === "psa" && !LAB_MODE) return "security";
  return views.includes(requested as View) ? (requested as View) : "dashboard";
}

const API_BASE = import.meta.env.VITE_API_URL
  ?? `${window.location.protocol}//${window.location.hostname}:8000`;

const viewTitles: Record<View, { eyebrow: string; title: string; description: string }> = {
  dashboard: {
    eyebrow: "Vue d'ensemble",
    title: "Atelier diagnostic",
    description: "État du véhicule, sécurité et accès rapide aux opérations.",
  },
  garage: {
    eyebrow: "Dossier véhicule",
    title: "Garage & suivi temporel",
    description: "Charge le bon VIN et retrouve diagnostics, trajets et interventions dans une chronologie unique.",
  },
  studio: {
    eyebrow: "Composition libre",
    title: "Dashboard libre",
    description: "Dispose, redimensionne et enregistre tes instruments comme tu le souhaites.",
  },
  replay: {
    eyebrow: "Post-traitement temporel",
    title: "Replay véhicule",
    description: "Trajectoire reconstruite, commandes conducteur, instruments et aides à la conduite.",
  },
  sensors: {
    eyebrow: "CAN passif + OBD temps réel",
    title: "Capteurs en direct",
    description: "Trames constructeur passives et lectures Mode 01 normalisées, avec provenance explicite.",
  },
  inventory: {
    eyebrow: "Validation guidée",
    title: "Validation des capteurs",
    description: "Une file de travail claire pour observer, tester et confirmer chaque information utile.",
  },
  identity: {
    eyebrow: "OBD-II / UDS · lecture seule",
    title: "VIN & identité véhicule",
    description: "Lecture multi-source du VIN, du logiciel, de la calibration et du nom ECU pour Peugeot ou Fiat.",
  },
  injection: {
    eyebrow: "Calculateur moteur · OBD-II",
    title: "Injection & moteur",
    description: "Air, carburant, pression de rampe, combustion, EGR et températures en lecture seule.",
  },
  maintenance: {
    eyebrow: "Capacités par véhicule",
    title: "Services de maintenance",
    description: "29 fonctions classées par applicabilité, équipement, risque et niveau de validation.",
  },
  psa: {
    eyebrow: "UDS constructeur · accès protégé",
    title: "Centre d’autorisation PSA",
    description: "Lecture, commandes nommées et outils experts séparés par des niveaux d’autorisation explicites.",
  },
  ecus: {
    eyebrow: "Architecture et défauts",
    title: "Diagnostic véhicule",
    description: "Identifier les calculateurs, lire les défauts et conserver un rapport par VIN.",
  },
  dtcs: {
    eyebrow: "Mémoire défauts",
    title: "Codes DTC",
    description: "Défauts décodés, états UDS et provenance des catalogues.",
  },
  discovery: {
    eyebrow: "OpenDiag Learn",
    title: "Découverte & corrélation",
    description: "Enregistrer passivement, annoter les actions et analyser hors ligne.",
  },
  database: {
    eyebrow: "Connaissance ouverte",
    title: "Database OpenDiag",
    description: "ECU, capteurs, DTC, procédures, sources et niveaux de confiance.",
  },
  security: {
    eyebrow: "Moteur interne de protection",
    title: "Security & Workflow",
    description: "Préconditions, autorisations, journalisation, contrôle et rapports pour chaque opération.",
  },
};

const markerPresets = [
  "frein_appuye",
  "frein_relache",
  "phares_allumes",
  "phares_eteints",
  "clignotant_gauche",
  "clignotant_droit",
  "marche_arriere",
  "porte_ouverte",
  "volant_gauche",
  "volant_droite",
  "volant_centre",
  "accelerateur_appuye",
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail ?? `Erreur HTTP ${response.status}`);
  }
  return payload as T;
}

function hexadecimal(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `0x${value.toString(16).toUpperCase()}`;
}

function formatDate(timestampUs?: number | null) {
  if (!timestampUs) return "Date inconnue";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(timestampUs / 1000));
}

function formatIsoDate(value?: string | null) {
  if (!value) return "Date inconnue";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(timestamp));
}

function formatDuration(milliseconds: number) {
  if (milliseconds < 1000) return `${milliseconds.toFixed(0)} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} s`;
  return `${(milliseconds / 60_000).toFixed(1)} min`;
}

function formatReplayTime(milliseconds: number) {
  const totalSeconds = Math.max(0, milliseconds) / 1000;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const tenths = Math.floor((totalSeconds % 1) * 10);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

function replayPointIndex(points: ReplaySample[], timeMs: number) {
  let low = 0;
  let high = points.length - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (points[middle].t_ms <= timeMs) low = middle + 1;
    else high = middle - 1;
  }
  return Math.max(0, Math.min(points.length - 1, high));
}

function routeGeometry(replay: ReplayData | null): RouteGeometry {
  if (!replay?.points.length) return { path: "", coordinates: [], gpsCoordinates: [], mapTiles: [], mapZoom: null };
  const width = 760;
  const height = 470;
  const padding = 52;
  const geographicPoints = replay.points.filter((point) =>
    typeof point.latitude === "number"
    && Number.isFinite(point.latitude)
    && typeof point.longitude === "number"
    && Number.isFinite(point.longitude),
  );
  if (geographicPoints.length === replay.points.length) {
    const tileSize = 256;
    const project = (latitude: number, longitude: number, zoom: number) => {
      const scale = tileSize * 2 ** zoom;
      const safeLatitude = Math.max(-85.05112878, Math.min(85.05112878, latitude));
      const sinLatitude = Math.sin(safeLatitude * Math.PI / 180);
      return {
        x: (longitude + 180) / 360 * scale,
        y: (0.5 - Math.log((1 + sinLatitude) / (1 - sinLatitude)) / (4 * Math.PI)) * scale,
      };
    };
    let zoom = 18;
    let projected = geographicPoints.map((point) => project(point.latitude as number, point.longitude as number, zoom));
    for (; zoom > 2; zoom -= 1) {
      projected = geographicPoints.map((point) => project(point.latitude as number, point.longitude as number, zoom));
      const xs = projected.map((point) => point.x);
      const ys = projected.map((point) => point.y);
      if (Math.max(...xs) - Math.min(...xs) <= width - padding * 2
        && Math.max(...ys) - Math.min(...ys) <= height - padding * 2) break;
    }
    const xs = projected.map((point) => point.x);
    const ys = projected.map((point) => point.y);
    const centerX = (Math.min(...xs) + Math.max(...xs)) / 2;
    const centerY = (Math.min(...ys) + Math.max(...ys)) / 2;
    const viewportLeft = centerX - width / 2;
    const viewportTop = centerY - height / 2;
    const coordinates = projected.map((point) => ({ x: point.x - viewportLeft, y: point.y - viewportTop }));
    const pathStep = Math.max(1, Math.ceil(coordinates.length / 2400));
    const pathCoordinates = coordinates.filter((_, index) => index % pathStep === 0 || index === coordinates.length - 1);
    const path = pathCoordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const tileCount = 2 ** zoom;
    const mapTiles: RouteGeometry["mapTiles"] = [];
    const firstTileX = Math.floor(viewportLeft / tileSize);
    const lastTileX = Math.floor((viewportLeft + width) / tileSize);
    const firstTileY = Math.max(0, Math.floor(viewportTop / tileSize));
    const lastTileY = Math.min(tileCount - 1, Math.floor((viewportTop + height) / tileSize));
    for (let tileY = firstTileY; tileY <= lastTileY; tileY += 1) {
      for (let rawTileX = firstTileX; rawTileX <= lastTileX; rawTileX += 1) {
        const tileX = ((rawTileX % tileCount) + tileCount) % tileCount;
        mapTiles.push({
          key: `${zoom}-${rawTileX}-${tileY}`,
          href: `https://tile.openstreetmap.org/${zoom}/${tileX}/${tileY}.png`,
          x: rawTileX * tileSize - viewportLeft,
          y: tileY * tileSize - viewportTop,
        });
      }
    }
    const referenceLatitude = geographicPoints[Math.floor(geographicPoints.length / 2)].latitude as number;
    const metersPerPixel = Math.cos(referenceLatitude * Math.PI / 180) * 2 * Math.PI * 6378137 / (tileSize * 2 ** zoom);
    const gpsCoordinates = replay.gps_points.map((point) => {
      const projectedGps = project(point.latitude, point.longitude, zoom);
      return {
        x: projectedGps.x - viewportLeft,
        y: projectedGps.y - viewportTop,
        accuracyPx: Math.max(3, Math.min(80, point.accuracy_m / Math.max(0.01, metersPerPixel))),
      };
    });
    return { path, coordinates, gpsCoordinates, mapTiles, mapZoom: zoom };
  }
  const minX = replay.route_bounds.min_x ?? 0;
  const maxX = replay.route_bounds.max_x ?? 1;
  const minY = replay.route_bounds.min_y ?? 0;
  const maxY = replay.route_bounds.max_y ?? 1;
  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  const coordinates = replay.points.map((point) => ({
    x: width / 2 + (point.x_m - centerX) * scale,
    y: height / 2 - (point.y_m - centerY) * scale,
  }));
  const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  return { path, coordinates, gpsCoordinates: [], mapTiles: [], mapZoom: null };
}

function replayGraphGeometry(replay: ReplayData, definition: ReplayGaugeDefinition): ReplayGraphGeometry {
  const numericPoints = replay.points.filter((point) => typeof point[definition.key] === "number");
  if (!numericPoints.length) return { path: "", minimum: definition.minimum, maximum: definition.maximum };
  const values = numericPoints.map((point) => Number(point[definition.key]));
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  const observedSpan = maximum - minimum;
  const padding = observedSpan > 0 ? observedSpan * 0.08 : Math.max(1, Math.abs(maximum) * 0.04);
  minimum -= padding;
  maximum += padding;
  const span = Math.max(0.001, maximum - minimum);
  const sampleStep = Math.max(1, Math.ceil(replay.points.length / 720));
  const sampled = replay.points.filter((_, index) => index % sampleStep === 0 || index === replay.points.length - 1);
  let drawing = false;
  const commands: string[] = [];
  sampled.forEach((point) => {
    const value = point[definition.key];
    if (typeof value !== "number") {
      drawing = false;
      return;
    }
    const x = replay.duration_ms ? point.t_ms / replay.duration_ms * 900 : 0;
    const y = 172 - (value - minimum) / span * 164;
    commands.push(`${drawing ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`);
    drawing = true;
  });
  return { path: commands.join(" "), minimum, maximum };
}

function TelecodingDetails({ zone }: { zone: TelecodingZoneInfo }) {
  return (
    <div className="telecoding-details">
      <p className="telecoding-heading">{zone.name} <small>· famille {zone.family} · {zone.confidence}</small></p>
      {zone.parameters.length === 0 ? (
        <p className="inline-alert">Aucun paramètre de télécodage documenté pour cette valeur.</p>
      ) : (
        <ul className="telecoding-parameter-list">
          {zone.parameters.map((param) => (
            <li key={param.key}>
              <code>{param.raw_hex}</code>
              <span>{param.name}</span>
              <strong>{param.value ?? "valeur non répertoriée"}</strong>
            </li>
          ))}
        </ul>
      )}
      {zone.source && <small>Source : {zone.source} (communauté, non vérifié sur ce véhicule)</small>}
    </div>
  );
}

function ExperimentalSignalsPanel({
  point,
  validation,
  onValidate,
  onClear,
  busyKey,
}: {
  point: ReplaySample | null;
  validation?: ReplayValidation | null;
  onValidate?: (key: string, validated: boolean) => void;
  onClear?: (key: string) => void;
  busyKey?: string;
}) {
  const definitions = replayGaugeCatalog.filter((definition) => definition.experimental);
  if (!point) return null;
  return (
    <section className="panel experimental-signals-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">En cours de validation</span>
          <h2>Signaux expérimentaux</h2>
          <p>Candidats trouvés par corrélation, pas encore confirmés officiellement.{onValidate ? " Valeur en direct et confirmation manuelle ci-dessous." : " Valeur en direct pendant le test."}</p>
        </div>
      </div>
      <div className="experimental-signal-list">
        {definitions.map((definition) => {
          const raw = point[definition.key];
          const value = typeof raw === "number"
            ? `${raw.toFixed(definition.precision ?? 0)} ${definition.unit}`
            : typeof raw === "boolean"
              ? (raw ? "Actif" : "Inactif")
              : "—";
          const signal = validation?.signals.find((item) => item.key === definition.key);
          return (
            <article key={definition.key}>
              <div><strong>{definition.label}</strong><small>{definition.note}</small></div>
              <div className="experimental-signal-value">{value}</div>
              {signal && <span className={`validation-badge ${signal.status}`}>{signal.status === "validated" ? "Validé" : signal.status === "plausible" ? "Plausible" : signal.status === "suspicious" ? "Suspect" : signal.status === "unavailable" ? "Indisponible" : "À confirmer"}</span>}
              {onValidate && onClear && signal && signal.status !== "unavailable" && (
                <div className="validation-manual-actions">
                  {signal.manual_validation === true ? (
                    <>
                      <span className="manual-validation-tag confirmed">Confirmé</span>
                      <button className="ghost-button" disabled={busyKey === definition.key} onClick={() => onClear(definition.key)}>Retirer</button>
                    </>
                  ) : signal.manual_validation === false ? (
                    <>
                      <span className="manual-validation-tag rejected">Invalidé</span>
                      <button className="ghost-button" disabled={busyKey === definition.key} onClick={() => onClear(definition.key)}>Retirer</button>
                    </>
                  ) : (
                    <>
                      <button className="secondary-button" disabled={busyKey === definition.key} onClick={() => onValidate(definition.key, true)}>Confirmer</button>
                      <button className="ghost-button" disabled={busyKey === definition.key} onClick={() => onValidate(definition.key, false)}>Invalide</button>
                    </>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function passiveSnapshotToReplaySample(snapshot: PassiveSensorSnapshot): { point: ReplaySample; availableFields: string[] } {
  const signals = new Map(snapshot.signals.map((signal) => [signal.key, signal.value]));
  const numeric = (key: string): number | null => {
    const value = signals.get(key);
    if (typeof value === "boolean") return Number(value);
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    return value;
  };
  const logical = (key: string): boolean | null => {
    const value = signals.get(key);
    if (typeof value === "boolean") return value;
    if (typeof value === "number" && Number.isFinite(value)) return value !== 0;
    return null;
  };
  const integer = (key: string): number | null => {
    const value = numeric(key);
    return value === null ? null : Math.round(value);
  };
  const bounded = (key: string, minimum: number, maximum: number): number | null => {
    const value = numeric(key);
    return value !== null && value >= minimum && value <= maximum ? value : null;
  };
  const turnSignalValue = integer("HS2_DAT_MDD_CMD_452.TURN_SIGNAL_STATUS");
  const headlampFaults = [
    logical("HS2_DAT7_BSI_612.DEF_FEU_CROISMNT_D"), logical("HS2_DAT7_BSI_612.DEF_FEU_CROISMNT_G"),
    logical("HS2_DAT7_BSI_612.DEF_FEU_ROUTE_D"), logical("HS2_DAT7_BSI_612.DEF_FEU_ROUTE_G"),
  ];
  const fiatWheelSpeeds = [
    numeric("FIAT_ABS.WHEEL_FRONT_LEFT_SPEED"),
    numeric("FIAT_ABS.WHEEL_FRONT_RIGHT_SPEED"),
    numeric("FIAT_ABS.WHEEL_REAR_LEFT_SPEED"),
    numeric("FIAT_ABS.WHEEL_REAR_RIGHT_SPEED"),
  ];
  const fiatAverageWheelSpeed = fiatWheelSpeeds.every((value) => value !== null)
    ? fiatWheelSpeeds.reduce<number>((total, value) => total + (value ?? 0), 0) / fiatWheelSpeeds.length
    : null;
  const point: ReplaySample = {
    t_ms: 0,
    x_m: 0,
    y_m: 0,
    heading_deg: 0,
    distance_m: 0,
    speed_kph: numeric("HS2_DYN_ABR_38D.VITESSE_VEHICULE_ROUES") ?? numeric("OBD01.vehicle_speed") ?? fiatAverageWheelSpeed,
    engine_rpm: numeric("Dyn_CMM.P000_Com_nEng") ?? numeric("FIAT_ENGINE.ENGINE_RPM") ?? numeric("OBD01.engine_rpm"),
    engine_load_pct: numeric("OBD01.engine_load"),
    absolute_engine_load_pct: numeric("OBD01.absolute_engine_load"),
    fuel_pressure_kpa: numeric("OBD01.fuel_pressure"),
    manifold_pressure_kpa: numeric("OBD01.intake_manifold_pressure"),
    mass_air_flow_g_s: numeric("OBD01.maf"),
    throttle_position_pct: numeric("OBD01.throttle_position"),
    relative_throttle_position_pct: numeric("OBD01.relative_throttle_position"),
    throttle_position_b_pct: numeric("OBD01.absolute_throttle_position_b"),
    throttle_position_c_pct: numeric("OBD01.absolute_throttle_position_c"),
    commanded_throttle_actuator_pct: numeric("OBD01.commanded_throttle_actuator"),
    fiat_throttle_candidate_pct: numeric("FIAT_ENGINE.THROTTLE_POSITION_CANDIDATE"),
    fiat_air_load_candidate_raw: numeric("FIAT_ENGINE.AIR_LOAD_CANDIDATE_RAW"),
    ignition_advance_deg: numeric("OBD01.timing_advance"),
    fuel_injection_timing_deg: numeric("OBD01.fuel_injection_timing"),
    short_fuel_trim_pct: numeric("OBD01.short_fuel_trim_bank_1"),
    long_fuel_trim_pct: numeric("OBD01.long_fuel_trim_bank_1"),
    oxygen_sensor_b1s1_v: numeric("OBD01.oxygen_sensor_b1s1_voltage"),
    oxygen_sensor_b1s2_v: numeric("OBD01.oxygen_sensor_b1s2_voltage"),
    commanded_equivalence_ratio: numeric("OBD01.commanded_equivalence_ratio"),
    evap_purge_pct: numeric("OBD01.commanded_evap_purge"),
    engine_runtime_s: numeric("OBD01.engine_runtime"),
    fuel_level_pct: numeric("OBD01.fuel_level"),
    fuel_rate_lph: numeric("OBD01.fuel_rate"),
    steering_angle_deg: snapshot.steering.detected ? snapshot.steering.angle_degrees ?? null : null,
    steering_rate_deg_s: snapshot.steering.detected ? snapshot.steering.rate_degrees_s ?? null : null,
    driver_torque: snapshot.steering.detected ? snapshot.steering.driver_torque ?? null : null,
    accelerator_pct: numeric("Dyn_CMM.P002_Com_rAPP") ?? numeric("Dyn5_CMM.P334_ACCPed_Position") ?? numeric("DRIVER.GAS_PEDAL") ?? numeric("OBD01.accelerator_pedal_d") ?? numeric("OBD01.throttle_position"),
    accelerator_secondary_pct: numeric("Dyn5_CMM.P334_ACCPed_Position") ?? numeric("OBD01.accelerator_pedal_e"),
    relative_accelerator_position_pct: numeric("OBD01.relative_accelerator_position"),
    engine_torque_nm: numeric("Dyn_CMM.P003_Com_trqActOut"),
    idle_setpoint_rpm: numeric("Dat_CMM.P022_Com_nSetPLo"),
    fuel_consumption_candidate_mm3: numeric("Dat_CMM.P021_Com_volFlCons"),
    virtual_fuel_consumption_candidate_mm3: numeric("Dat2_CMM.P316_FlSys_volFlConsVirt"),
    current_gear: integer("Dyn2_CMM.P152_Gearbx_stGear"),
    target_gear: integer("Dyn_V2_BVMP.P283_Com_stGearTrgtPos"),
    gear_shift_active: logical("Dyn_V2_BVMP.P009_Com_bGearShftActv"),
    drivetrain_engaged_state: integer("Dyn_V2_BVMP.P030_Gbx_stDrvTrnEgd"),
    longitudinal_accel_ms2: numeric("HS2_DYN_ABR_38D.ACCEL_LONGI_ROUES"),
    lateral_accel_ms2: numeric("Dyn2_FRE.LATERAL_ACCELERATION"),
    yaw_rate_deg_s: numeric("Dyn2_FRE.YAW_RATE"),
    brake_active: logical("Dat_BSI.P013_MainBrake") ?? logical("FIAT_ABS.BRAKE_PEDAL_ACTIVE"),
    brake_system_state: integer("Dyn2_FRE.P226_Com_stBrkActv"),
    brake_pressure_raw: numeric("Dyn2_FRE.BRAKE_PRESSURE") ?? numeric("FIAT_ABS.BRAKE_PEDAL_STATE_RAW"),
    turn_signal: turnSignalValue === null ? null : ({ 0: "off", 1: "right", 2: "left", 3: "hazard" } as const)[turnSignalValue as 0 | 1 | 2 | 3] ?? "off",
    low_beam: logical("HS2_DAT7_BSI_612.ETAT_FEUX_CROIST"),
    high_beam: logical("HS2_DAT7_BSI_612.ETAT_FEUX_ROUTE"),
    reverse: logical("Dat_BSI.P103_Com_bRevGear"),
    parking_brake: logical("Dat_BSI.PARKING_BRAKE") ?? logical("FIAT_BODY.PARKING_BRAKE"),
    driver_door: logical("Dat_BSI.DRIVER_DOOR") ?? logical("FIAT_BODY.DRIVER_DOOR_OPEN"),
    passenger_door: logical("Dat_BSI.PASSENGER_DOOR"),
    front_wiper_status: integer("HS2_DAT_MDD_CMD_452.FRONT_WIPER_STATUS"),
    fuel_liters_raw: numeric("HS2_DAT7_BSI_612.INFO_NIV_CARB"),
    oil_temperature_c: numeric("Dat_CMM.P011_Oil_tSwmp") ?? numeric("OBD01.engine_oil_temperature"),
    coolant_temperature_c: numeric("Dat_CMM.P005_CEngDst_tSens") ?? numeric("OBD01.coolant_temperature"),
    intake_air_temperature_c: numeric("Dat_CMM.P158_Air_tAFS") ?? numeric("OBD01.intake_air_temperature"),
    oil_pressure_switch: logical("Dat2_CMM.P278_Oil_stPSwmp"),
    battery_voltage_v: bounded("Dat6_BSI.P418_Com_uBattRaw", 8, 16.5) ?? bounded("OBD01.control_module_voltage", 8, 16.5),
    battery_temperature_c: bounded("Dat6_BSI.P273_Com_tBatt", -40, 90),
    battery_charge_pct: bounded("Dat6_BSI.P272_Com_rBattCh", 0, 100),
    ambient_temperature_c: numeric("Contexte1_5B2.P146_Com_tEnvT") ?? numeric("OBD01.ambient_temperature"),
    atmospheric_pressure_hpa: numeric("Dat2_CMM.P338_EnvP_p") ?? (() => { const value = numeric("OBD01.barometric_pressure"); return value === null ? null : value * 10; })(),
    obd_error: logical("Dyn2_CMM.P343_Com_bOBDErr"),
    mil_on: logical("Dyn2_CMM.P344_Com_bMILOn"),
    mil_blinking: logical("Dyn2_CMM.P345_Com_bMILBln"),
    esp_fault_state: integer("Dyn2_CMM.P025_Com_stESPErr"),
    esp_intervention: logical("Dyn_CDS.P147_Com_bESPIntvActv"),
    abs_intervention: logical("Dat_ABR.P351_Com_bABSIntvActv"),
    gearbox_fault: logical("Dyn_STT_BV.P444_Com_bGbxSysFaultRaw"),
    generic_warning_requested: logical("HS2_DYN_ABR_38D.REQ_LAMPE_WARNING"),
    brake_fault: logical("Dat_BSI.P040_MainBrakeFault"),
    low_fuel_warning: logical("Dat_BSI.P012_Com_bFlMin"),
    fuel_level_fault_state: integer("Dat_BSI.P086_Com_stFlLvlDia"),
    headlamp_fault: headlampFaults.some((value) => value !== null) ? headlampFaults.some(Boolean) : null,
    driver_seatbelt_state: integer("RESTRAINTS.DRIVER_SEATBELT"),
    passenger_seatbelt_state: integer("RESTRAINTS.PASSENGER_SEATBELT"),
    lane_assist_status: integer("LANE_KEEP_ASSIST.STATUS"),
    lane_departure: integer("LANE_KEEP_ASSIST.LANE_DEPARTURE"),
    lka_active: logical("LANE_KEEP_ASSIST.LXA_ACTIVATION"),
    acc_mode: integer("HS2_DAT_MDD_CMD_452.LONGITUDINAL_REGULATION_TYPE"),
    acc_requested: logical("HS2_DAT_MDD_CMD_452.RVV_ACC_ACTIVATION_REQ"),
    speed_setpoint_kph: numeric("HS2_DAT_MDD_CMD_452.SPEED_SETPOINT"),
    cruise_probable: null,
    cruise_confidence: null,
    cruise_detection_state: null,
    cruise_detection_reason: null,
    cruise_switch_candidate:
      integer("HS2_DAT_MDD_CMD_452.LONGITUDINAL_REGULATION_TYPE") === null
        ? null
        : integer("HS2_DAT_MDD_CMD_452.LONGITUDINAL_REGULATION_TYPE") !== 0,
    cruise_xvv_state: integer("Dyn_CMM.P037_VehV_stXVV"),
    cruise_active_candidate:
      integer("Dyn_CMM.P037_VehV_stXVV") === null
        ? null
        : integer("Dyn_CMM.P037_VehV_stXVV") === 2,
    cruise_setpoint_kph:
      (integer("Dat_CLIM.P219_Com_xPrpReqRaw") ?? 255) >= 255
        ? null
        : integer("Dat_CLIM.P219_Com_xPrpReqRaw"),
    climate_ac_active: logical("Dat_CLIM.P050_Com_stAC"),
    climate_ac_power_kw:
      numeric("Dat_CLIM.P210_Com_pwrACDem") !== null
        ? Math.round(numeric("Dat_CLIM.P210_Com_pwrACDem") ?? 0) / 1000
        : null,
    front_sensor_b0_raw: integer("FRONT_SENSOR_CANDIDATE.BYTE0_RAW"),
    front_sensor_b2_raw: integer("FRONT_SENSOR_CANDIDATE.BYTE2_RAW"),
    front_sensor_b4_raw: integer("FRONT_SENSOR_CANDIDATE.BYTE4_RAW"),
    wheel_front_left_kph: numeric("Dyn4_FRE.P263_VehV_VPsvValWhlFrtL") ?? fiatWheelSpeeds[0],
    wheel_front_right_kph: numeric("Dyn4_FRE.P264_VehV_VPsvValWhlFrtR") ?? fiatWheelSpeeds[1],
    wheel_rear_left_kph: numeric("Dyn4_FRE.P265_VehV_VPsvValWhlBckL") ?? fiatWheelSpeeds[2],
    wheel_rear_right_kph: numeric("Dyn4_FRE.P266_VehV_VPsvValWhlBckR") ?? fiatWheelSpeeds[3],
  };
  const availableFields = Object.entries(point)
    .filter(([key, value]) => !["t_ms", "x_m", "y_m", "heading_deg", "distance_m"].includes(key) && value !== null && value !== undefined)
    .map(([key]) => key);
  return { point, availableFields };
}

function liveGraphGeometry(points: ReplaySample[], definition: ReplayGaugeDefinition, windowSeconds: StudioGraphWindowSeconds): ReplayGraphGeometry {
  const commands: string[] = [];
  let drawing = false;
  const span = Math.max(.001, definition.maximum - definition.minimum);
  const windowMs = windowSeconds * 1000;
  const latestMs = points.at(-1)?.t_ms ?? 0;
  const startMs = latestMs - windowMs;
  points.filter((point) => point.t_ms >= startMs).forEach((point) => {
    const value = point[definition.key];
    if (typeof value !== "number") {
      drawing = false;
      return;
    }
    const x = Math.max(0, Math.min(900, (point.t_ms - startMs) / windowMs * 900));
    const y = 172 - (value - definition.minimum) / span * 164;
    commands.push(`${drawing ? "L" : "M"}${x.toFixed(1)},${Math.max(8, Math.min(172, y)).toFixed(1)}`);
    drawing = true;
  });
  return { path: commands.join(" "), minimum: definition.minimum, maximum: definition.maximum };
}

function replayIndicatorState(
  definition: ReplayIndicatorDefinition,
  point: ReplaySample,
  replay: Pick<ReplayData, "available_fields">,
): ReplayIndicatorState {
  const available = definition.fields.some((field) => replay.available_fields.includes(String(field)));
  if (definition.referenceOnly || !available) {
    return { available: false, active: null, detail: "Signal non enregistré" };
  }
  switch (definition.key) {
    case "turn_left":
      return { available, active: ["left", "hazard"].includes(point.turn_signal ?? "off"), detail: point.turn_signal === "hazard" ? "Feux de détresse" : "Commande gauche" };
    case "turn_right":
      return { available, active: ["right", "hazard"].includes(point.turn_signal ?? "off"), detail: point.turn_signal === "hazard" ? "Feux de détresse" : "Commande droite" };
    case "low_beam":
      return { available, active: Boolean(point.low_beam), detail: point.low_beam ? "Allumés" : "Éteints" };
    case "high_beam":
      return { available, active: Boolean(point.high_beam), detail: point.high_beam ? "Allumés" : "Éteints" };
    case "parking_brake":
      return { available, active: Boolean(point.parking_brake), detail: point.parking_brake ? "Serré" : "Desserré" };
    case "brake_fault":
      return { available, active: Boolean(point.brake_fault), detail: point.brake_fault ? "Défaut demandé" : "Aucun défaut demandé" };
    case "abs":
      return { available, active: Boolean(point.abs_intervention), detail: point.abs_intervention ? "Intervention détectée" : "Pas d'intervention" };
    case "esp": {
      const fault = (point.esp_fault_state ?? 0) !== 0;
      const active = fault || Boolean(point.esp_intervention);
      return { available, active, detail: fault ? `Défaut brut ${point.esp_fault_state}` : point.esp_intervention ? "Intervention détectée" : "Veille" };
    }
    case "oil_pressure":
      return { available, active: Boolean(point.oil_pressure_switch), detail: point.oil_pressure_switch ? "Contacteur actif" : "Contacteur inactif" };
    case "coolant": {
      const temperature = point.coolant_temperature_c;
      return { available, active: typeof temperature === "number" ? temperature >= 115 : null, detail: typeof temperature === "number" ? `${temperature.toFixed(0)} °C · seuil visuel 115 °C` : "Valeur absente", inferred: true };
    }
    case "battery": {
      const voltage = point.battery_voltage_v;
      const running = (point.engine_rpm ?? 0) > 500;
      return { available, active: typeof voltage === "number" ? running && voltage < 12.2 : null, detail: typeof voltage === "number" ? `${voltage.toFixed(2)} V${running ? " moteur tournant" : ""}` : "Valeur absente", inferred: true };
    }
    case "fuel":
      return { available, active: Boolean(point.low_fuel_warning), detail: point.low_fuel_warning ? "Niveau minimal demandé" : "Réserve non demandée" };
    case "engine": {
      const active = Boolean(point.mil_on || point.mil_blinking || point.obd_error);
      return { available, active, detail: point.mil_blinking ? "MIL clignotant" : active ? "MIL / défaut OBD demandé" : "Témoin non demandé" };
    }
    case "door": {
      const labels = [point.driver_door ? "conducteur" : "", point.passenger_door ? "passager" : ""].filter(Boolean);
      return { available, active: labels.length > 0, detail: labels.length ? `Ouverte : ${labels.join(" + ")}` : "Portes avant fermées" };
    }
    case "seatbelt":
      return { available, active: null, detail: `États bruts C ${point.driver_seatbelt_state ?? "—"} · P ${point.passenger_seatbelt_state ?? "—"}` };
    case "lane":
      return { available, active: Boolean(point.lka_active || point.lane_departure || point.lane_assist_status === 4), detail: point.lane_departure ? `Alerte ligne brute ${point.lane_departure}` : laneAssistStatusLabel(point.lane_assist_status) };
    case "lane_fault": {
      const active = point.lane_assist_status === 5 || point.lane_assist_status === 6;
      return { available, active, detail: laneAssistStatusLabel(point.lane_assist_status) };
    }
    case "reverse":
      return { available, active: Boolean(point.reverse || point.current_gear === 9), detail: point.reverse || point.current_gear === 9 ? "Rapport arrière" : "Inactive" };
    case "headlamp_fault":
      return { available, active: Boolean(point.headlamp_fault), detail: point.headlamp_fault ? "Défaut de lampe déclaré" : "Aucun défaut déclaré" };
    case "gearbox":
      return { available, active: Boolean(point.gearbox_fault), detail: point.gearbox_fault ? "Défaut système déclaré" : "Aucun défaut déclaré" };
    case "stop":
      return { available, active: Boolean(point.generic_warning_requested), detail: point.generic_warning_requested ? "Requête d'alerte active" : "Aucune requête" };
    default:
      return { available, active: null, detail: "État brut disponible" };
  }
}

function ReplayWarningIcon({ kind }: { kind: string }) {
  const textIcons: Record<string, string> = {
    parking: "P", brake: "!", abs: "ABS", esp: "ESP", stop: "STOP", airbag: "SRS",
    tpms: "!", service: "🔧", adblue: "UREA", gearbox: "!", reverse: "R",
  };
  let drawing: React.ReactNode;
  switch (kind) {
    case "arrow-left":
      drawing = <path d="M8 32 29 14v11h27v14H29v11Z" fill="currentColor" />;
      break;
    case "arrow-right":
      drawing = <path d="m56 32-21-18v11H8v14h27v11Z" fill="currentColor" />;
      break;
    case "low-beam":
    case "high-beam":
    case "fog":
      drawing = <><path d="M30 17c-12 1-19 7-19 15s7 14 19 15V17Z" /><path d={kind === "low-beam" ? "m37 22 18 5M37 31l18 5M37 40l18 5" : kind === "fog" ? "m37 22 18 0M37 32h12m-12 10h18M48 27c7 2 7 8 0 10" : "m37 22 19-6M37 32h19M37 42l19 6"} /></>;
      break;
    case "oil":
      drawing = <><path d="M10 27h29l8 8-8 13H15L8 39Z" /><path d="m21 27 4-9h13l5 9M47 25l8-7" /><path d="M54 36c5 6 5 9 0 11-5-2-5-5 0-11Z" fill="currentColor" /></>;
      break;
    case "coolant":
      drawing = <><path d="M28 12v27a10 10 0 1 0 8 0V12a4 4 0 0 0-8 0Z" /><path d="M32 22v24M8 53c6-5 10 5 16 0s10 5 16 0 10 5 16 0" /></>;
      break;
    case "battery":
      drawing = <><rect x="8" y="20" width="48" height="31" rx="3" /><path d="M18 20v-6h9v6m10 0v-6h9v6M17 35h11m-5-5v11m16-6h10" /></>;
      break;
    case "fuel":
      drawing = <><rect x="12" y="10" width="27" height="44" rx="3" /><path d="M18 16h15v13H18Zm21 5 9 7v19c0 7 8 7 8 0V25l-6-7" /></>;
      break;
    case "engine":
      drawing = <path d="M9 24h8l6-7h18l6 7h8v23h-9l-5 6H20l-5-6H9Zm12-11v7m21-7v7M4 31h5m46 0h5" />;
      break;
    case "door":
      drawing = <><path d="M22 9h20l7 13v27l-8 7H23l-8-7V22Z" /><path d="M17 26 7 18m40 8 10-8M23 23h18l3 11H20Z" /></>;
      break;
    case "seatbelt":
      drawing = <><circle cx="24" cy="14" r="6" /><path d="M22 21 14 34l10 6 4 15m2-31 13 30M24 40h20" /></>;
      break;
    case "lane":
      drawing = <><path d="M17 56 25 8M47 56 39 8" /><path d="m32 17 8 11h-6v15h-4V28h-6Z" fill="currentColor" /></>;
      break;
    case "bulb":
      drawing = <><path d="M20 29a12 12 0 1 1 24 0c0 7-6 8-7 16H27c-1-8-7-9-7-16Z" /><path d="M27 50h10m-9 5h8M32 5V1M11 12l-4-4m46 4 4-4M9 31H3m58 0h-6" /></>;
      break;
    case "steering":
      drawing = <><circle cx="32" cy="32" r="23" /><circle cx="32" cy="32" r="6" /><path d="M10 28h44M28 37l-9 14m17-14 9 14" /></>;
      break;
    case "washer":
      drawing = <><path d="M10 42h44l-5 12H15Z" /><path d="m18 32 4-8m10 8V20m10 12-4-8" /><circle cx="22" cy="18" r="2" fill="currentColor" /><circle cx="32" cy="14" r="2" fill="currentColor" /><circle cx="42" cy="18" r="2" fill="currentColor" /></>;
      break;
    case "glow":
      drawing = <path d="M6 32c5-13 11-13 16 0s11 13 16 0 11-13 20 0" />;
      break;
    default:
      drawing = <text x="32" y="38" textAnchor="middle" fill="currentColor">{textIcons[kind] ?? kind.slice(0, 4).toUpperCase()}</text>;
  }
  return <svg viewBox="0 0 64 64" aria-hidden="true">{drawing}</svg>;
}

function NavButton({
  active,
  glyph,
  label,
  onClick,
  count,
}: {
  active: boolean;
  glyph: string;
  label: string;
  onClick: () => void;
  count?: number;
}) {
  return (
    <button className={`nav-button ${active ? "active" : ""}`} onClick={onClick}>
      <span className="nav-glyph">{glyph}</span>
      <span>{label}</span>
      {count !== undefined && <span className="nav-count">{count}</span>}
    </button>
  );
}

function EmptyState({ title, text, action }: { title: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-symbol">◇</span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

function App() {
  const [view, setView] = useState<View>(initialView);
  const [openNavModule, setOpenNavModule] = useState<NavModule | null>(() => {
    const initial = initialView();
    if (["ecus", "sensors", "dtcs", "identity"].includes(initial)) return "diagnostic";
    if (["injection", "maintenance", "studio"].includes(initial)) return "atelier";
    if (["discovery", "inventory", "replay"].includes(initial)) return "learn";
    return null;
  });
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState("");
  const [operatingMode, setOperatingMode] = useState<OperatingModeState | null>(null);
  const [modeDialogOpen, setModeDialogOpen] = useState(false);
  const [modeSwitchBusy, setModeSwitchBusy] = useState(false);
  const [modeConfirmation, setModeConfirmation] = useState("");
  const [modeChecks, setModeChecks] = useState({
    vehicle_stationary: false,
    ignition_on_engine_off: false,
    stable_battery_voltage: false,
    workshop_or_private_site: false,
  });
  const [transportCatalog, setTransportCatalog] = useState<TransportCatalog | null>(null);
  const [selectedTransportId, setSelectedTransportId] = useState("");
  const [transportConnectBusy, setTransportConnectBusy] = useState(false);
  const [transportMessage, setTransportMessage] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [selectedEcuKey, setSelectedEcuKey] = useState("");
  const [diagnosticRegression, setDiagnosticRegression] = useState<RegressionResult | null>(null);
  const [diagnosticRegressionBusy, setDiagnosticRegressionBusy] = useState(false);
  const [traceImportResult, setTraceImportResult] = useState<TraceImportResult | null>(null);
  const [traceImportBusy, setTraceImportBusy] = useState(false);
  const [dtcClearEcuKey, setDtcClearEcuKey] = useState("");
  const [dtcClearConfirmation, setDtcClearConfirmation] = useState("");
  const [dtcClearChecks, setDtcClearChecks] = useState({
    vehicle_stationary: false,
    ignition_on_engine_off: false,
    stable_battery_voltage: false,
    report_saved: false,
  });
  const [dtcClearBusy, setDtcClearBusy] = useState(false);
  const [dtcClearResult, setDtcClearResult] = useState<ClearDtcResult | null>(null);
  const [dtcSnapshotBusy, setDtcSnapshotBusy] = useState("");
  const [dtcSnapshotResults, setDtcSnapshotResults] = useState<Record<string, DtcSnapshotResult>>({});
  const [didSweepStart, setDidSweepStart] = useState("F180");
  const [didSweepEnd, setDidSweepEnd] = useState("F1FF");
  const [didSweepBusy, setDidSweepBusy] = useState(false);
  const [didSweepResult, setDidSweepResult] = useState<DidSweepResult | null>(null);
  const [observedDtcs, setObservedDtcs] = useState<ObservedDtc[]>([]);
  const [diagnosticVehicles, setDiagnosticVehicles] = useState<DiagnosticVehicle[]>([]);
  const [selectedDiagnosticVin, setSelectedDiagnosticVin] = useState(
    () => window.localStorage.getItem("opendiag.diagnostic-vin") ?? "",
  );
  const [vehicleSelectionBusy, setVehicleSelectionBusy] = useState(false);
  const [sessionAssignmentBusy, setSessionAssignmentBusy] = useState("");
  const [garageEventFilter, setGarageEventFilter] = useState<"all" | "diagnostic" | "capture" | "identity">("all");
  const [diagnosticReportHistory, setDiagnosticReportHistory] = useState<DiagnosticReportSummary[]>([]);
  const [dtcFilter, setDtcFilter] = useState<DtcValue["state"] | "all">("active");
  const [diagnosticSensorCatalog, setDiagnosticSensorCatalog] = useState<DiagnosticSensorCatalogEntry[]>([]);
  const [injectionSnapshot, setInjectionSnapshot] = useState<DiagnosticSensorSnapshot | null>(null);
  const [injectionBusy, setInjectionBusy] = useState(false);
  const [vehicleProfiles, setVehicleProfiles] = useState<VehicleProfileSummary[]>([]);
  const [identityProfileKey, setIdentityProfileKey] = useState(() =>
    new URLSearchParams(window.location.search).get("profile")
      ?? window.localStorage.getItem("opendiag.identity-profile")
      ?? "peugeot_308_t9_2018"
  );
  const [vehicleIdentity, setVehicleIdentity] = useState<VehicleIdentityResult | null>(null);
  const [identityBusy, setIdentityBusy] = useState(false);
  const [obdDtcResult, setObdDtcResult] = useState<Ecu | null>(null);
  const [obdDtcBusy, setObdDtcBusy] = useState(false);
  const [udsProbeEcuKey, setUdsProbeEcuKey] = useState("body_computer");
  const [udsProbeResult, setUdsProbeResult] = useState<DidValue | null>(null);
  const [udsProbeBusy, setUdsProbeBusy] = useState(false);
  const [psaCatalog, setPsaCatalog] = useState<PsaAdvancedCatalog | null>(null);
  const [maintenanceCatalog, setMaintenanceCatalog] = useState<MaintenanceCatalog | null>(null);
  const [maintenanceCategory, setMaintenanceCategory] = useState("Toutes");
  const [psaEcuKey, setPsaEcuKey] = useState("bsi");
  const [psaDid, setPsaDid] = useState("F190");
  const [psaDidResult, setPsaDidResult] = useState<DidValue | null>(null);
  const [psaSeed, setPsaSeed] = useState("11111111");
  const [psaApplicationKey, setPsaApplicationKey] = useState("D91C");
  const [psaSeedResult, setPsaSeedResult] = useState<PsaSeedKeyResult | null>(null);
  const [psaSelectedActionKey, setPsaSelectedActionKey] = useState("");
  const [psaConfirmation, setPsaConfirmation] = useState("");
  const [psaDurationMs, setPsaDurationMs] = useState(1500);
  const [psaUnlockEcuKey, setPsaUnlockEcuKey] = useState("telematics");
  const [psaUnlockApplicationKey, setPsaUnlockApplicationKey] = useState("D91C");
  const [psaUnlockConfirmation, setPsaUnlockConfirmation] = useState("");
  const [psaLabChecks, setPsaLabChecks] = useState({
    vehicle_stationary: false,
    ignition_on_engine_off: false,
    stable_battery_voltage: false,
    workshop_or_private_site: false,
  });
  const [psaBusy, setPsaBusy] = useState("");
  const [psaFeedback, setPsaFeedback] = useState("");
  const [psaSection, setPsaSection] = useState<"read" | "actions" | "expert">(() => {
    const requested = new URLSearchParams(window.location.search).get("mode");
    return requested === "actions" || requested === "expert" ? requested : "read";
  });
  const [powertrainProfile, setPowertrainProfile] = useState<PowertrainProfile>(() => {
    const saved = window.localStorage.getItem("opendiag.powertrain-profile");
    return saved === "gasoline" || saved === "diesel" ? saved : "unknown";
  });
  const [inventorySearch, setInventorySearch] = useState("");
  const [inventorySystem, setInventorySystem] = useState("Tous");
  const [inventoryStatus, setInventoryStatus] = useState<"all" | "available" | "missing" | "excluded">("all");
  const [inventoryPriorityOnly, setInventoryPriorityOnly] = useState(false);
  const [validationFocusId, setValidationFocusId] = useState("");
  const [passiveSensors, setPassiveSensors] = useState<PassiveSensorSnapshot | null>(null);
  const sensorCursorUs = useRef(0);
  const sensorRefreshBusy = useRef(false);
  const [sensorCategory, setSensorCategory] = useState("Essentiels");
  const [sensorSearch, setSensorSearch] = useState("");
  const [sensorEditor, setSensorEditor] = useState<{
    key: string;
    label: string;
    description: string;
    unit: string;
    factor: string;
    offset: string;
    customized: boolean;
  } | null>(null);
  const [sensorEditorBusy, setSensorEditorBusy] = useState(false);
  const [liveSensorDefinitions, setLiveSensorDefinitions] = useState<LiveSensorDefinition[]>([]);
  const [liveSensorEditor, setLiveSensorEditor] = useState<{
    key?: string;
    sourceKey: string;
    label: string;
    description: string;
    category: string;
    unit: string;
    factor: string;
    offset: string;
  } | null>(null);
  const [liveSensorEditorBusy, setLiveSensorEditorBusy] = useState(false);
  const [detectionEndsAt, setDetectionEndsAt] = useState<number | null>(null);
  const [detectionRemaining, setDetectionRemaining] = useState(0);
  const [detectionBusy, setDetectionBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [extendedProbeEnabled, setExtendedProbeEnabled] = useState(false);
  const [error, setError] = useState("");

  const [capture, setCapture] = useState<CaptureStatus | null>(null);
  const [captureName, setCaptureName] = useState("Nouvelle session véhicule");
  const [captureNote, setCaptureNote] = useState("");
  const [captureGpsEnabled, setCaptureGpsEnabled] = useState(
    () => window.localStorage.getItem("opendiag.capture-gps") !== "false",
  );
  const [gpsTracking, setGpsTracking] = useState<{
    state: "idle" | "requesting" | "active" | "unavailable" | "denied" | "error";
    accuracyM?: number;
    message?: string;
  }>({ state: "idle" });
  const gpsWatchRef = useRef<number | null>(null);
  const gpsLastSentAtRef = useRef(0);
  const [markerName, setMarkerName] = useState("frein_appuye");
  const [markerNote, setMarkerNote] = useState("");
  const [sessions, setSessions] = useState<DiscoverySession[]>([]);
  const [analysis, setAnalysis] = useState<BehavioralAnalysis | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState("");
  const [opendbcCatalog, setOpendbcCatalog] = useState<OpendbcCatalog | null>(null);
  const [replay, setReplay] = useState<ReplayData | null>(null);
  const [replayValidation, setReplayValidation] = useState<ReplayValidation | null>(null);
  const [signalValidationBusy, setSignalValidationBusy] = useState("");
  const [replaySessionId, setReplaySessionId] = useState("");
  const [replayBusy, setReplayBusy] = useState(false);
  const [replayTimeMs, setReplayTimeMs] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replayRate, setReplayRate] = useState(1);
  const [replayGaugeToAdd, setReplayGaugeToAdd] = useState("");
  const [selectedReplayGaugeKeys, setSelectedReplayGaugeKeys] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.replay-gauges") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultReplayGaugeKeys;
    } catch {
      return defaultReplayGaugeKeys;
    }
  });
  const [replayGraphToAdd, setReplayGraphToAdd] = useState("");
  const [selectedReplayGraphKeys, setSelectedReplayGraphKeys] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.replay-graphs") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultReplayGraphKeys;
    } catch {
      return defaultReplayGraphKeys;
    }
  });
  const [replayIndicatorToAdd, setReplayIndicatorToAdd] = useState("");
  const [selectedReplayIndicatorKeys, setSelectedReplayIndicatorKeys] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.replay-indicators") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultReplayIndicatorKeys;
    } catch {
      return defaultReplayIndicatorKeys;
    }
  });
  const [studioWidgets, setStudioWidgets] = useState<StudioWidget[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.studio-layout") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultStudioWidgets;
    } catch {
      return defaultStudioWidgets;
    }
  });
  const [studioWidgetToAdd, setStudioWidgetToAdd] = useState("gauge:oil_temperature_c");
  const [studioEditing, setStudioEditing] = useState(true);
  const studioBoardRef = useRef<HTMLDivElement>(null);
  const studioInteractionCleanup = useRef<(() => void) | null>(null);
  const [studioLiveHistory, setStudioLiveHistory] = useState<ReplaySample[]>([]);
  const studioLiveSessionRef = useRef("");
  const studioLiveStartUs = useRef(0);
  const studioFuelFilterRef = useRef<{ sessionId: string; generatedAtUs: number; value: number | null }>({
    sessionId: "",
    generatedAtUs: 0,
    value: null,
  });

  useEffect(() => {
    api<Status>("/api/system/status")
      .then((payload) => {
        setStatus(payload);
        setStatusError("");
      })
      .catch((err) => setStatusError(err instanceof Error ? err.message : String(err)));
    void refreshOperatingMode();
    refreshCapture();
    refreshTransportCatalog();
    refreshPassiveSensors();
    refreshSessions();
    void refreshDiagnosticHistory();
    api<DiagnosticSensorCatalogEntry[]>("/api/sensors/catalog")
      .then(setDiagnosticSensorCatalog)
      .catch(() => setDiagnosticSensorCatalog([]));
    api<VehicleProfileSummary[]>("/api/database/vehicles")
      .then((profiles) => {
        setVehicleProfiles(profiles);
        setIdentityProfileKey((current) => profiles.some((profile) => profile.key === current)
          ? current
          : profiles[0]?.key ?? current);
      })
      .catch(() => setVehicleProfiles([]));
    api<PsaAdvancedCatalog>("/api/diagnostic/psa/catalog")
      .then(setPsaCatalog)
      .catch(() => setPsaCatalog(null));
    api<OpendbcCatalog>("/api/learn/opendbc/catalog")
      .then(setOpendbcCatalog)
      .catch(() => setOpendbcCatalog(null));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(refreshCapture, capture?.active ? 800 : 2500);
    return () => window.clearInterval(timer);
  }, [capture?.active]);

  useEffect(() => {
    if (view === "security") void refreshOperatingMode();
  }, [view, capture?.active]);

  useEffect(() => {
    if (capture?.active && captureGpsEnabled) startGpsTracking(capture.session_id);
    else stopGpsTracking();
    return stopGpsTracking;
  }, [capture?.active, capture?.session_id, captureGpsEnabled]);

  useEffect(() => {
    if (!["sensors", "inventory", "ecus", "psa", "studio"].includes(view) || !capture?.active) return;
    const timer = window.setInterval(refreshPassiveSensors, 200);
    return () => window.clearInterval(timer);
  }, [view, capture?.active]);

  useEffect(() => {
    if (view === "studio") void refreshPassiveSensors();
  }, [view]);

  useEffect(() => {
    if (!detectionEndsAt) return;
    const update = () => {
      const remaining = Math.max(0, Math.ceil((detectionEndsAt - Date.now()) / 1000));
      setDetectionRemaining(remaining);
      if (remaining === 0) setDetectionEndsAt(null);
    };
    update();
    const timer = window.setInterval(update, 250);
    return () => window.clearInterval(timer);
  }, [detectionEndsAt]);

  useEffect(() => {
    if (view !== "replay" || replaySessionId || replayBusy || sessions.length === 0) return;
    const preferred = sessions.find((session) => session.vin === selectedDiagnosticVin)
      ?? sessions.find((session) => !session.vin)
      ?? sessions[0];
    void loadReplay(preferred.session_id);
  }, [view, sessions, replaySessionId, replayBusy, selectedDiagnosticVin]);

  useEffect(() => {
    if (!replayPlaying || !replay) return;
    let frame = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      const elapsed = now - previous;
      previous = now;
      setReplayTimeMs((current) => {
        const next = current + elapsed * replayRate;
        if (next >= replay.duration_ms) {
          setReplayPlaying(false);
          return replay.duration_ms;
        }
        return next;
      });
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [replayPlaying, replay, replayRate]);

  useEffect(() => {
    if (view !== "replay") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      event.preventDefault();
      setReplayPlaying((playing) => !playing);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [view]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.replay-gauges", JSON.stringify(selectedReplayGaugeKeys));
  }, [selectedReplayGaugeKeys]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.replay-graphs", JSON.stringify(selectedReplayGraphKeys));
  }, [selectedReplayGraphKeys]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.replay-indicators", JSON.stringify(selectedReplayIndicatorKeys));
  }, [selectedReplayIndicatorKeys]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.studio-layout", JSON.stringify(studioWidgets));
  }, [studioWidgets]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.powertrain-profile", powertrainProfile);
  }, [powertrainProfile]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.capture-gps", String(captureGpsEnabled));
  }, [captureGpsEnabled]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.identity-profile", identityProfileKey);
  }, [identityProfileKey]);

  useEffect(() => {
    if (selectedDiagnosticVin) window.localStorage.setItem("opendiag.diagnostic-vin", selectedDiagnosticVin);
    else window.localStorage.removeItem("opendiag.diagnostic-vin");
    void refreshLiveSensorDefinitions();
  }, [selectedDiagnosticVin]);

  useEffect(() => () => studioInteractionCleanup.current?.(), []);

  const detectedEcus = report?.ecus.filter((ecu) => ecu.detected) ?? [];
  const selectedEcu = detectedEcus.find((ecu) => ecu.key === selectedEcuKey)
    ?? detectedEcus[0]
    ?? report?.ecus[0]
    ?? null;
  useEffect(() => {
    if (!report?.ecus.length) {
      if (selectedEcuKey) setSelectedEcuKey("");
      return;
    }
    if (!report.ecus.some((ecu) => ecu.key === selectedEcuKey && ecu.detected)) {
      setSelectedEcuKey(report.ecus.find((ecu) => ecu.detected)?.key ?? report.ecus[0].key);
    }
  }, [report, selectedEcuKey]);
  const dtcs = useMemo(
    () => report?.ecus.flatMap((ecu) => ecu.dtcs.map((dtc) => ({ ecu, dtc }))) ?? [],
    [report],
  );
  const visibleDtcs = useMemo(
    () => dtcFilter === "all" ? dtcs : dtcs.filter(({ dtc }) => dtc.state === dtcFilter),
    [dtcs, dtcFilter],
  );
  const dtcCount = report?.dtc_summary.active ?? 0;
  const selectedDiagnosticVehicle = diagnosticVehicles.find((vehicle) => vehicle.vin === selectedDiagnosticVin) ?? null;
  const selectedIdentityProfile = vehicleProfiles.find((profile) => profile.key === identityProfileKey) ?? null;
  const vehicleManufacturers = useMemo(
    () => Array.from(new Set(vehicleProfiles.map((profile) => profile.manufacturer))).sort((left, right) => left.localeCompare(right, "fr")),
    [vehicleProfiles],
  );
  const profilesForSelectedManufacturer = useMemo(
    () => vehicleProfiles.filter((profile) => profile.manufacturer === selectedIdentityProfile?.manufacturer),
    [selectedIdentityProfile?.manufacturer, vehicleProfiles],
  );
  const activeCommunicationProfileKey = (
    capture?.active && capture.vehicle_profile
      ? capture.vehicle_profile
      : selectedDiagnosticVehicle?.vehicle_profile ?? identityProfileKey
  );
  const activeCommunicationProfile = vehicleProfiles.find((profile) => profile.key === activeCommunicationProfileKey) ?? selectedIdentityProfile;
  const activeIsFiat500 = activeCommunicationProfileKey === "fiat_500_generic";
  const activeVehicleVisual = vehicleVisualForProfile(activeCommunicationProfileKey);
  const effectivePowertrainProfile: PowertrainProfile = activeIsFiat500 ? "gasoline" : powertrainProfile;
  useEffect(() => {
    if (!activeCommunicationProfileKey) return;
    setMaintenanceCatalog(null);
    api<MaintenanceCatalog>(`/api/maintenance/catalog?vehicle_profile=${encodeURIComponent(activeCommunicationProfileKey)}`)
      .then(setMaintenanceCatalog)
      .catch(() => setMaintenanceCatalog(null));
  }, [activeCommunicationProfileKey]);
  const maintenanceCategories = useMemo(
    () => ["Toutes", ...Array.from(new Set(maintenanceCatalog?.services.map((service) => service.category) ?? []))],
    [maintenanceCatalog],
  );
  const visibleMaintenanceServices = useMemo(
    () => (maintenanceCatalog?.services ?? []).filter((service) => maintenanceCategory === "Toutes" || service.category === maintenanceCategory),
    [maintenanceCatalog, maintenanceCategory],
  );
  const vehicleLinkedSessions = useMemo(
    () => sessions.filter((session) => session.vin === selectedDiagnosticVin),
    [sessions, selectedDiagnosticVin],
  );
  const unassignedSessions = useMemo(
    () => sessions.filter((session) => !session.vin),
    [sessions],
  );
  const vehicleTimeline = useMemo<VehicleTimelineEntry[]>(() => {
    if (!selectedDiagnosticVin) return [];
    const entries: VehicleTimelineEntry[] = diagnosticReportHistory.map((item) => ({
      id: item.scan_id,
      kind: "diagnostic",
      timestampMs: new Date(item.scanned_at).getTime(),
      title: "Diagnostic complet ECU + DTC",
      description: `${item.detected_ecus} calculateurs détectés · ${item.dtc_summary.active} actif(s) · ${item.dtc_summary.historical} historique(s)`,
      badge: item.dtc_summary.active ? `${item.dtc_summary.active} défaut(s) actif(s)` : "Aucun défaut actif",
      scanId: item.scan_id,
      severity: item.dtc_summary.active ? "warning" : "good",
    }));
    for (const session of vehicleLinkedSessions) {
      entries.push({
        id: session.session_id,
        kind: "capture",
        timestampMs: (session.started_at_us ?? 0) / 1000,
        title: session.name,
        description: `${formatDuration(session.duration_ms)} · ${session.frame_count.toLocaleString("fr-FR")} trames${session.gps_point_count ? ` · ${session.gps_point_count} positions GPS` : ""}`,
        badge: session.gps_point_count ? "Trajet géolocalisé" : session.marker_count ? `${session.marker_count} marqueur(s)` : "Capture CAN",
        sessionId: session.session_id,
        severity: session.error ? "warning" : "neutral",
      });
    }
    if (selectedDiagnosticVehicle?.first_seen) {
      entries.push({
        id: `identity-${selectedDiagnosticVehicle.vin}`,
        kind: "identity",
        timestampMs: new Date(selectedDiagnosticVehicle.first_seen).getTime(),
        title: "Véhicule ajouté au garage",
        description: `Identité enregistrée sous le profil ${selectedDiagnosticVehicle.vehicle_profile}`,
        badge: "VIN confirmé",
        severity: "good",
      });
    }
    return entries
      .filter((entry) => Number.isFinite(entry.timestampMs) && (garageEventFilter === "all" || entry.kind === garageEventFilter))
      .sort((left, right) => right.timestampMs - left.timestampMs);
  }, [diagnosticReportHistory, garageEventFilter, selectedDiagnosticVehicle, selectedDiagnosticVin, vehicleLinkedSessions]);
  const activeVehicleLabel = selectedDiagnosticVehicle
    ? `${selectedDiagnosticVehicle.manufacturer} ${selectedDiagnosticVehicle.model}`
    : activeCommunicationProfile
      ? `${activeCommunicationProfile.manufacturer} ${activeCommunicationProfile.model}`
      : "Aucun profil chargé";
  const psaVehicleCompatible = Boolean(
    selectedDiagnosticVehicle
    && (
      selectedDiagnosticVehicle.manufacturer.toLocaleLowerCase("fr").includes("peugeot")
      || selectedDiagnosticVehicle.vehicle_profile.startsWith("peugeot_")
      || selectedDiagnosticVehicle.vehicle_profile.startsWith("psa_")
    ),
  );
  const directPsaCompatible = Boolean(
    activeCommunicationProfile
    && (
      activeCommunicationProfile.manufacturer.toLocaleLowerCase("fr").includes("peugeot")
      || activeCommunicationProfile.key.startsWith("peugeot_")
      || activeCommunicationProfile.key.startsWith("psa_")
    )
  );
  const activeTitle = viewTitles[view];
  const dualCanOperational = Boolean(
    capture?.active
    && capture.dual_can
    && capture.live_can_ready
    && capture.diagnostic_can_ready,
  );
  const diagnosticGatewayVerified = status?.transport === "virtual" || Boolean(status?.gateway_verified) || dualCanOperational;
  const liveObdReadOnly = status?.transport === "virtual" || status?.gateway_hello?.live_obd_read_only === true;
  const diagnosticReady = Boolean(
    status?.can_tx_enabled
    && diagnosticGatewayVerified
    && (!capture?.active || dualCanOperational),
  );
  const obdReadReady = Boolean(
    diagnosticReady
    && liveObdReadOnly,
  );
  const identityReadReady = Boolean(
    diagnosticReady
    && (selectedIdentityProfile?.identity_scope !== "identity_only" || obdReadReady),
  );
  const selectedPsaEcu = psaCatalog?.ecus.find((ecu) => ecu.key === psaEcuKey) ?? null;
  const selectedPsaAction = psaCatalog?.actions.find((action) => action.key === psaSelectedActionKey) ?? null;
  const psaUnlockEcu = psaCatalog?.ecus.find((ecu) => ecu.key === psaUnlockEcuKey) ?? null;
  const injectionValues = useMemo(
    () => new Map((injectionSnapshot?.values ?? []).map((value) => [value.key, value])),
    [injectionSnapshot],
  );
  const injectionGroups = useMemo(() => {
    const preferredOrder = ["Carburant", "Air", "Combustion", "Dépollution", "Températures", "Électrique", "Contexte"];
    return preferredOrder
      .map((group) => ({ group, sensors: diagnosticSensorCatalog.filter((sensor) => sensor.group === group) }))
      .filter(({ sensors }) => sensors.length > 0);
  }, [diagnosticSensorCatalog]);
  const engineDtcs = report?.ecus.find((ecu) => ecu.key === "engine")?.dtcs ?? [];
  const sensorCategories = useMemo(
    () => ["Essentiels", "Toutes", ...Array.from(new Set(passiveSensors?.signals.map((signal) => signal.category) ?? []))],
    [passiveSensors],
  );
  const visiblePassiveSignals = useMemo(() => {
    const query = sensorSearch.trim().toLocaleLowerCase("fr");
    return (passiveSensors?.signals ?? []).filter((signal) => {
      if (sensorCategory === "Essentiels" && !signal.essential) return false;
      if (!["Toutes", "Essentiels"].includes(sensorCategory) && signal.category !== sensorCategory) return false;
      if (!query) return true;
      return `${signal.category} ${signal.display_name} ${signal.description} ${signal.message} ${signal.signal}`.toLocaleLowerCase("fr").includes(query);
    });
  }, [passiveSensors, sensorCategory, sensorSearch]);
  const passiveSubsystems = useMemo(() => {
    const definitions = [
      ["Moteur", "Calculateur moteur", "Régime, accélérateur, couple et états moteur"],
      ["Freinage / ABS", "ABS / ESP", "Vitesses des roues, freinage et stabilité"],
      ["Direction", "Direction / capteur volant", "Angle, vitesse et effort au volant"],
      ["Habitacle / BSI", "BSI et commandes habitacle", "Portes, éclairage, essuie-glaces et commandes"],
      ["ADAS / caméra", "Caméra et aides à la conduite", "Maintien dans la voie et régulation"],
      ["Airbag / retenue", "Airbag et retenue", "Ceintures et états du système de retenue"],
      ["Transmission", "Boîte de vitesses", "Rapports, autorisations et états de transmission"],
      ["Climatisation", "Climatisation", "Commande compresseur, ventilation et charge"],
    ] as const;
    return definitions.map(([category, name, description]) => {
      const messages = Array.from(new Set(
        (passiveSensors?.signals ?? [])
          .filter((signal) => signal.category === category)
          .map((signal) => signal.message),
      ));
      return { category, name, description, messages, detected: messages.length > 0 };
    });
  }, [passiveSensors]);
  const currentReplayIndex = useMemo(
    () => replay?.points.length ? replayPointIndex(replay.points, replayTimeMs) : 0,
    [replay, replayTimeMs],
  );
  const currentReplayPoint = replay?.points[currentReplayIndex] ?? null;
  const studioLiveSample = useMemo(() => {
    if (!passiveSensors) return null;
    const sample = passiveSnapshotToReplaySample(passiveSensors);
    const rawFuel = sample.point.fuel_liters_raw;
    if (typeof rawFuel === "number" && Number.isFinite(rawFuel)) {
      const filter = studioFuelFilterRef.current;
      if (filter.sessionId !== passiveSensors.session_id || filter.value === null) {
        filter.sessionId = passiveSensors.session_id;
        filter.generatedAtUs = passiveSensors.generated_at_us;
        filter.value = rawFuel;
      } else if (passiveSensors.generated_at_us > filter.generatedAtUs) {
        const elapsedS = Math.max(0, Math.min(5, (passiveSensors.generated_at_us - filter.generatedAtUs) / 1_000_000));
        const alpha = 1 - Math.exp(-elapsedS / 120);
        filter.value += alpha * (rawFuel - filter.value);
        filter.generatedAtUs = passiveSensors.generated_at_us;
      }
      sample.point.fuel_liters = Number(filter.value.toFixed(2));
      if (!sample.availableFields.includes("fuel_liters")) sample.availableFields.push("fuel_liters");
    }
    return sample;
  }, [passiveSensors]);
  const sensorInventoryRows = useMemo<SensorInventoryRow[]>(() => {
    const statusLabels: Record<SensorInventoryStatus, string> = {
      measured: "Mesuré",
      supported: "Supporté · à relire",
      to_test: "À tester",
      to_observe: "À observer",
      to_decode: "À décoder",
      unsupported: "Non exposé OBD",
      not_applicable: "Non applicable",
    };
    const availableFields = new Set(studioLiveSample?.availableFields ?? []);
    const point = studioLiveSample?.point;
    const formatInventoryValue = (raw: unknown) => {
      if (typeof raw === "boolean") return raw ? "Actif" : "Inactif";
      if (typeof raw === "number") return raw.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
      if (typeof raw === "string") return raw;
      return null;
    };
    const advancedRows: SensorInventoryRow[] = sensorCandidatesForProfile(activeCommunicationProfileKey).map((candidate) => {
      const applicability = candidate.applicability ?? "all";
      const excluded = effectivePowertrainProfile !== "unknown" && applicability !== "all" && applicability !== effectivePowertrainProfile;
      let status: SensorInventoryStatus = excluded ? "not_applicable" : candidate.source === "can" ? "to_observe" : "to_decode";
      let value: string | null = null;
      if (!excluded && candidate.liveFields?.length) {
        const observedField = (candidate.liveFields ?? []).find((field) => availableFields.has(field));
        if (observedField) {
          status = "measured";
          value = formatInventoryValue(point?.[observedField as keyof ReplaySample]);
        }
      }
      return {
        id: candidate.id,
        label: candidate.label,
        system: candidate.system,
        description: candidate.description,
        source: candidate.source === "can" ? "CAN / OBD direct" : candidate.source === "fiat" ? "Fiat spécifique" : "PSA spécifique",
        status,
        statusLabel: statusLabels[status],
        priority: candidate.priority,
        optional: Boolean(candidate.optional),
        value,
        reference: candidate.source === "can"
          ? candidate.liveFields?.join(" · ")
          : candidate.source === "fiat"
            ? "Paramètre IAW/Body CAN Fiat à identifier"
            : "DID ou trame PSA à identifier",
      };
    });
    const criticalObdKeys = new Set([
      "engine_rpm", "coolant_temperature", "fuel_pressure", "intake_manifold_pressure", "maf",
      "fuel_rail_gauge_pressure", "absolute_fuel_rail_pressure", "fuel_rate", "control_module_voltage",
      "engine_load", "throttle_position", "timing_advance", "short_fuel_trim_bank_1",
      "long_fuel_trim_bank_1", "oxygen_sensor_b1s1_voltage", "oxygen_sensor_b1s2_voltage",
    ]);
    const fiatNotApplicableObdKeys = new Set([
      "short_fuel_trim_bank_2", "long_fuel_trim_bank_2",
      "fuel_rail_gauge_pressure", "absolute_fuel_rail_pressure",
      "commanded_egr", "egr_error",
    ]);
    const obdRows: SensorInventoryRow[] = diagnosticSensorCatalog.map((sensor) => {
      const value = injectionValues.get(sensor.key);
      const supported = Boolean(injectionSnapshot?.supported_pids.includes(sensor.pid));
      const excluded = activeIsFiat500 && fiatNotApplicableObdKeys.has(sensor.key) && !supported;
      let status: SensorInventoryStatus = excluded ? "not_applicable" : "to_test";
      if (injectionSnapshot) status = supported ? value?.error ? "supported" : typeof value?.value === "number" ? "measured" : "supported" : excluded ? "not_applicable" : "unsupported";
      return {
        id: `obd-${sensor.key}`,
        label: sensor.name,
        system: sensor.group === "Dépollution" ? "Dépollution" : "Moteur / injection",
        description: sensor.description,
        source: "OBD-II",
        status,
        statusLabel: statusLabels[status],
        priority: criticalObdKeys.has(sensor.key) ? 1 : 2,
        optional: false,
        value: typeof value?.value === "number" ? `${value.value.toLocaleString("fr-FR", { maximumFractionDigits: 3 })} ${value.unit ?? sensor.unit}` : null,
        reference: `Mode 01 · PID 0x${sensor.pid.toString(16).toUpperCase().padStart(2, "0")}`,
      };
    });
    return [...obdRows, ...advancedRows].sort((left, right) =>
      left.priority - right.priority || left.system.localeCompare(right.system, "fr") || left.label.localeCompare(right.label, "fr"),
    );
  }, [activeCommunicationProfileKey, activeIsFiat500, diagnosticSensorCatalog, effectivePowertrainProfile, injectionSnapshot, injectionValues, studioLiveSample]);
  const inventorySystems = useMemo(
    () => ["Tous", ...Array.from(new Set(sensorInventoryRows.map((row) => row.system)))],
    [sensorInventoryRows],
  );
  const visibleInventoryRows = useMemo(() => {
    const query = inventorySearch.trim().toLocaleLowerCase("fr");
    return sensorInventoryRows.filter((row) => {
      if (inventorySystem !== "Tous" && row.system !== inventorySystem) return false;
      if (inventoryPriorityOnly && row.priority !== 1) return false;
      if (inventoryStatus === "available" && !["measured", "supported"].includes(row.status)) return false;
      if (inventoryStatus === "missing" && !["to_test", "to_observe", "to_decode", "unsupported"].includes(row.status)) return false;
      if (inventoryStatus === "excluded" && row.status !== "not_applicable") return false;
      if (!query) return true;
      return `${row.label} ${row.system} ${row.description} ${row.source} ${row.reference ?? ""}`.toLocaleLowerCase("fr").includes(query);
    });
  }, [inventoryPriorityOnly, inventorySearch, inventoryStatus, inventorySystem, sensorInventoryRows]);
  const inventoryCounts = useMemo(() => ({
    measured: sensorInventoryRows.filter((row) => row.status === "measured").length,
    supported: sensorInventoryRows.filter((row) => row.status === "supported").length,
    missing: sensorInventoryRows.filter((row) => ["to_test", "to_observe", "to_decode", "unsupported"].includes(row.status)).length,
    excluded: sensorInventoryRows.filter((row) => row.status === "not_applicable").length,
  }), [sensorInventoryRows]);
  const validationQueue = useMemo(
    () => sensorInventoryRows.filter((row) => ["to_test", "to_observe", "to_decode", "supported"].includes(row.status)),
    [sensorInventoryRows],
  );
  const focusedValidationRow = validationQueue.find((row) => row.id === validationFocusId)
    ?? validationQueue.find((row) => row.priority === 1)
    ?? validationQueue[0]
    ?? null;
  const liveSafetyEvidence = useMemo(() => {
    if (!passiveSensors?.active || studioLiveHistory.length < 2) {
      return { speedKnown: false, stationary: false, rpmKnown: false, engineOff: false, batteryKnown: false, batteryStable: false, batteryValue: null as number | null };
    }
    const latestMs = studioLiveHistory.at(-1)?.t_ms ?? 0;
    const recent = studioLiveHistory.filter((point) => point.t_ms >= latestMs - 5_000);
    const speeds = recent.map((point) => point.speed_kph).filter((value): value is number => typeof value === "number");
    const rpms = recent.map((point) => point.engine_rpm).filter((value): value is number => typeof value === "number");
    const voltages = recent.map((point) => point.battery_voltage_v).filter((value): value is number => typeof value === "number");
    return {
      speedKnown: speeds.length >= 2,
      stationary: speeds.length >= 2 && Math.max(...speeds) <= 0.5,
      rpmKnown: rpms.length >= 2,
      engineOff: rpms.length >= 2 && Math.max(...rpms) < 50,
      batteryKnown: voltages.length >= 5,
      batteryStable: voltages.length >= 5 && Math.min(...voltages) >= 11.7 && Math.max(...voltages) <= 15.2 && Math.max(...voltages) - Math.min(...voltages) <= 0.4,
      batteryValue: voltages.at(-1) ?? null,
    };
  }, [passiveSensors?.active, studioLiveHistory]);
  const effectivePsaLabChecks = {
    vehicle_stationary: liveSafetyEvidence.speedKnown ? liveSafetyEvidence.stationary : psaLabChecks.vehicle_stationary,
    ignition_on_engine_off: liveSafetyEvidence.rpmKnown ? liveSafetyEvidence.engineOff : psaLabChecks.ignition_on_engine_off,
    stable_battery_voltage: liveSafetyEvidence.batteryKnown ? liveSafetyEvidence.batteryStable : psaLabChecks.stable_battery_voltage,
    workshop_or_private_site: psaLabChecks.workshop_or_private_site,
  };
  const psaLabChecksComplete = Object.values(effectivePsaLabChecks).every(Boolean);
  const currentRouteGeometry = useMemo(() => routeGeometry(replay), [replay]);
  const currentReplayGraphGeometries = useMemo(() => {
    const geometries = new Map<string, ReplayGraphGeometry>();
    if (!replay) return geometries;
    selectedReplayGraphKeys.forEach((key) => {
      const definition = replayGaugeCatalog.find((candidate) => candidate.key === key && !candidate.status);
      if (definition && replay.available_fields.includes(String(definition.key))) {
        geometries.set(key, replayGraphGeometry(replay, definition));
      }
    });
    return geometries;
  }, [replay, selectedReplayGraphKeys]);
  const studioGraphGeometries = useMemo(() => {
    const geometries = new Map<string, ReplayGraphGeometry>();
    studioWidgets.filter((widget) => widget.kind === "graph" && widget.key).forEach((widget) => {
      const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key && !candidate.status);
      const windowSeconds = STUDIO_GRAPH_WINDOWS.includes(widget.windowSeconds as StudioGraphWindowSeconds)
        ? widget.windowSeconds as StudioGraphWindowSeconds
        : 60;
      if (definition) geometries.set(widget.id, liveGraphGeometry(studioLiveHistory, definition, windowSeconds));
    });
    return geometries;
  }, [studioLiveHistory, studioWidgets]);

  useEffect(() => {
    if (!passiveSensors?.active || !studioLiveSample) return;
    if (studioLiveSessionRef.current !== passiveSensors.session_id) {
      studioLiveSessionRef.current = passiveSensors.session_id;
      studioLiveStartUs.current = passiveSensors.generated_at_us;
      setStudioLiveHistory([{ ...studioLiveSample.point, t_ms: 0 }]);
      return;
    }
    const tMs = Math.max(0, (passiveSensors.generated_at_us - studioLiveStartUs.current) / 1000);
    const point = { ...studioLiveSample.point, t_ms: tMs };
    setStudioLiveHistory((current) => [...current, point]
      .filter((item) => item.t_ms >= tMs - 300_000)
      .slice(-1800));
  }, [passiveSensors?.active, passiveSensors?.generated_at_us, passiveSensors?.session_id, studioLiveSample]);

  async function refreshTransportCatalog() {
    try {
      const payload = await api<TransportCatalog>("/api/system/transports");
      setTransportCatalog(payload);
      setSelectedTransportId((current) => current || payload.current_id || payload.options.find((option) => option.detected)?.id || payload.options[0]?.id || "");
    } catch {
      // Le statut général du backend rend déjà une indisponibilité explicite.
    }
  }

  async function refreshOperatingMode() {
    try {
      setOperatingMode(await api<OperatingModeState>("/api/system/operating-mode"));
    } catch {
      setOperatingMode(null);
    }
  }

  function openMaintenanceModeDialog() {
    setError("");
    setModeConfirmation("");
    setModeChecks({
      vehicle_stationary: false,
      ignition_on_engine_off: false,
      stable_battery_voltage: false,
      workshop_or_private_site: false,
    });
    setModeDialogOpen(true);
    void refreshOperatingMode();
  }

  async function activateReadOnlyMode() {
    if (operatingMode?.mode === "read_only") return;
    setModeSwitchBusy(true);
    setError("");
    try {
      const payload = await api<OperatingModeState>("/api/system/operating-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "read_only", vin: selectedDiagnosticVin || null }),
      });
      setOperatingMode(payload);
      setStatus(await api<Status>("/api/system/status"));
      setPsaCatalog(await api<PsaAdvancedCatalog>("/api/diagnostic/psa/catalog").catch(() => null));
      setModeDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setModeSwitchBusy(false);
    }
  }

  async function activateMaintenanceMode(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedDiagnosticVin) {
      setError("Charge d’abord le véhicule concerné depuis le Garage.");
      return;
    }
    setModeSwitchBusy(true);
    setError("");
    try {
      const payload = await api<OperatingModeState>("/api/system/operating-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "maintenance",
          confirmation: modeConfirmation,
          vin: selectedDiagnosticVin,
          ...modeChecks,
        }),
      });
      setOperatingMode(payload);
      setStatus(await api<Status>("/api/system/status"));
      setPsaCatalog(await api<PsaAdvancedCatalog>("/api/diagnostic/psa/catalog").catch(() => null));
      setModeDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setModeSwitchBusy(false);
    }
  }

  async function connectSelectedTransport() {
    const option = transportCatalog?.options.find((candidate) => candidate.id === selectedTransportId);
    if (!option || capture?.active) return;
    setTransportConnectBusy(true);
    setTransportMessage("");
    setError("");
    try {
      const connection = await api<TransportConnection>("/api/system/transport/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transport: option.transport, endpoint: option.endpoint, baud: option.baud ?? null }),
      });
      const nextStatus = await api<Status>("/api/system/status");
      setStatus(nextStatus);
      setStatusError("");
      setTransportMessage(connection.verified ? "ESP32 validé" : "Connexion non validée");
      await refreshTransportCatalog();
      await refreshOperatingMode();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setTransportMessage("Échec de connexion");
      setError(message);
      await refreshTransportCatalog();
    } finally {
      setTransportConnectBusy(false);
    }
  }

  async function refreshCapture() {
    try {
      setCapture(await api<CaptureStatus>("/api/learn/capture/status"));
    } catch {
      // Le panneau principal rend déjà l'indisponibilité du backend explicite.
    }
  }

  async function refreshSessions() {
    try {
      setSessions(await api<DiscoverySession[]>("/api/learn/sessions"));
    } catch {
      // Même principe : pas de deuxième alerte pour une unique panne réseau.
    }
  }

  async function setSignalManualValidation(key: string, validated: boolean) {
    if (!replaySessionId) return;
    setSignalValidationBusy(key);
    setError("");
    try {
      await api(`/api/learn/signals/${encodeURIComponent(key)}/validation`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ validated, session_id: replaySessionId }),
      });
      const updated = await api<ReplayValidation>(`/api/learn/replay/${encodeURIComponent(replaySessionId)}/validation`);
      setReplayValidation(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSignalValidationBusy("");
    }
  }

  async function clearSignalManualValidation(key: string) {
    if (!replaySessionId) return;
    setSignalValidationBusy(key);
    setError("");
    try {
      await api(`/api/learn/signals/${encodeURIComponent(key)}/validation`, { method: "DELETE" });
      const updated = await api<ReplayValidation>(`/api/learn/replay/${encodeURIComponent(replaySessionId)}/validation`);
      setReplayValidation(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSignalValidationBusy("");
    }
  }

  async function loadReplay(sessionId: string, force = false) {
    if (!sessionId) return;
    setReplayBusy(true);
    setReplayPlaying(false);
    setReplaySessionId(sessionId);
    setReplayTimeMs(0);
    setReplayValidation(null);
    setError("");
    try {
      const payload = await api<ReplayData>(`/api/learn/replay/${encodeURIComponent(sessionId)}${force ? "?force=true" : ""}`);
      setReplay(payload);
      const validation = await api<ReplayValidation>(`/api/learn/replay/${encodeURIComponent(sessionId)}/validation${force ? "?force=true" : ""}`);
      setReplayValidation(validation);
    } catch (err) {
      setReplay(null);
      setReplayValidation(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReplayBusy(false);
    }
  }

  function stopGpsTracking() {
    if (gpsWatchRef.current !== null && "geolocation" in navigator) {
      navigator.geolocation.clearWatch(gpsWatchRef.current);
    }
    gpsWatchRef.current = null;
    gpsLastSentAtRef.current = 0;
    setGpsTracking((current) => current.state === "idle" ? current : { state: "idle" });
  }

  function startGpsTracking(sessionId: string) {
    if (gpsWatchRef.current !== null) return;
    if (!("geolocation" in navigator)) {
      setGpsTracking({ state: "unavailable", message: "Géolocalisation absente de ce navigateur." });
      return;
    }
    if (!window.isSecureContext) {
      setGpsTracking({
        state: "unavailable",
        message: "Le GPS navigateur exige HTTPS ou une ouverture sur localhost.",
      });
      return;
    }

    setGpsTracking({ state: "requesting", message: "Autorisation GPS en attente…" });
    gpsWatchRef.current = navigator.geolocation.watchPosition(
      (position) => {
        const now = Date.now();
        if (now - gpsLastSentAtRef.current < 250) return;
        gpsLastSentAtRef.current = now;
        const finiteOrNull = (value: number | null) => value !== null && Number.isFinite(value) ? value : null;
        setGpsTracking({
          state: "active",
          accuracyM: position.coords.accuracy,
          message: `Position reçue à ±${Math.round(position.coords.accuracy)} m`,
        });
        void api<CaptureStatus>("/api/learn/capture/gps", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy_m: position.coords.accuracy,
            altitude_m: finiteOrNull(position.coords.altitude),
            altitude_accuracy_m: finiteOrNull(position.coords.altitudeAccuracy),
            heading_deg: finiteOrNull(position.coords.heading),
            speed_m_s: finiteOrNull(position.coords.speed),
            source_timestamp_us: Math.round(position.timestamp * 1000),
          }),
        }).then((payload) => {
          if (payload.session_id === sessionId) setCapture(payload);
        }).catch((err) => {
          setGpsTracking({
            state: "error",
            accuracyM: position.coords.accuracy,
            message: err instanceof Error ? err.message : String(err),
          });
        });
      },
      (positionError) => {
        const denied = positionError.code === positionError.PERMISSION_DENIED;
        setGpsTracking({
          state: denied ? "denied" : "error",
          message: denied
            ? "Autorisation GPS refusée; la capture CAN continue sans coordonnées."
            : positionError.code === positionError.POSITION_UNAVAILABLE
              ? "Position GPS indisponible."
              : "Délai GPS dépassé; nouvelle tentative en cours.",
        });
      },
      { enableHighAccuracy: true, maximumAge: 1_000, timeout: 15_000 },
    );
  }

  function seekReplay(timeMs: number) {
    setReplayTimeMs(Math.max(0, Math.min(replay?.duration_ms ?? 0, timeMs)));
  }

  function addReplayGauge() {
    if (!replayGaugeToAdd || selectedReplayGaugeKeys.includes(replayGaugeToAdd)) return;
    setSelectedReplayGaugeKeys((current) => [...current, replayGaugeToAdd]);
    setReplayGaugeToAdd("");
  }

  function removeReplayGauge(key: string) {
    setSelectedReplayGaugeKeys((current) => current.filter((item) => item !== key));
  }

  function addReplayGraph() {
    if (!replayGraphToAdd || selectedReplayGraphKeys.includes(replayGraphToAdd)) return;
    setSelectedReplayGraphKeys((current) => [...current, replayGraphToAdd]);
    setReplayGraphToAdd("");
  }

  function removeReplayGraph(key: string) {
    setSelectedReplayGraphKeys((current) => current.filter((item) => item !== key));
  }

  function addReplayIndicator() {
    if (!replayIndicatorToAdd || selectedReplayIndicatorKeys.includes(replayIndicatorToAdd)) return;
    setSelectedReplayIndicatorKeys((current) => [...current, replayIndicatorToAdd]);
    setReplayIndicatorToAdd("");
  }

  function removeReplayIndicator(key: string) {
    setSelectedReplayIndicatorKeys((current) => current.filter((item) => item !== key));
  }

  function addStudioWidget() {
    if (!studioWidgetToAdd) return;
    const [rawKind, key] = studioWidgetToAdd.split(":", 2);
    const kind = rawKind as StudioWidgetKind;
    const dimensions: Record<StudioWidgetKind, { w: number; h: number }> = {
      speed: { w: 3, h: 4 },
      steering: { w: 3, h: 4 },
      gear: { w: 2, h: 4 },
      vehicle: { w: 4, h: 6 },
      capture: { w: 6, h: 2 },
      gauge: { w: 2, h: 3 },
      graph: { w: 4, h: 3 },
      numeric: { w: 2, h: 2 },
      lamp: { w: 2, h: 2 },
      indicator: { w: 2, h: 2 },
    };
    const size = dimensions[kind] ?? dimensions.gauge;
    let position = { x: 0, y: 0 };
    let found = false;
    for (let y = 0; y < 16 && !found; y += 1) {
      for (let x = 0; x <= STUDIO_COLUMNS - size.w; x += 1) {
        const overlaps = studioWidgets.some((widget) =>
          x < widget.x + widget.w && x + size.w > widget.x && y < widget.y + widget.h && y + size.h > widget.y,
        );
        if (!overlaps) {
          position = { x, y };
          found = true;
          break;
        }
      }
    }
    if (!found) position = { x: 0, y: Math.max(0, ...studioWidgets.map((widget) => widget.y + widget.h)) };
    const id = `studio-${kind}-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`;
    setStudioWidgets((current) => [...current, {
      id,
      kind,
      key: key || undefined,
      ...position,
      ...size,
      ...(kind === "graph" ? { windowSeconds: 60 as StudioGraphWindowSeconds } : {}),
    }]);
  }

  function removeStudioWidget(id: string) {
    setStudioWidgets((current) => current.filter((widget) => widget.id !== id));
  }

  function setStudioGraphWindow(id: string, windowSeconds: StudioGraphWindowSeconds) {
    setStudioWidgets((current) => current.map((widget) => widget.id === id ? { ...widget, windowSeconds } : widget));
  }

  function setStudioSensorStyle(id: string, kind: StudioSensorStyle) {
    setStudioWidgets((current) => current.map((widget) => {
      if (widget.id !== id) return widget;
      if (kind === "lamp" && !replayGaugeCatalog.find((definition) => definition.key === widget.key)?.status) return widget;
      const minimum = kind === "graph" ? { w: 3, h: 3 } : { w: 2, h: 2 };
      return {
        ...widget,
        kind,
        w: Math.max(widget.w, minimum.w),
        h: Math.max(widget.h, minimum.h),
        ...(kind === "graph" && !widget.windowSeconds ? { windowSeconds: 60 as StudioGraphWindowSeconds } : {}),
      };
    }));
  }

  function resizeStudioWidget(id: string, delta: -1 | 1) {
    const boardHeight = studioBoardRef.current?.getBoundingClientRect().height ?? STUDIO_ROW_HEIGHT * 10;
    const maximumRows = Math.max(10, Math.floor(boardHeight / STUDIO_ROW_HEIGHT));
    setStudioWidgets((current) => current.map((widget) => {
      if (widget.id !== id) return widget;
      const minimum = widget.kind === "capture"
        ? { w: 4, h: 2 }
        : widget.kind === "graph" || widget.kind === "vehicle"
          ? { w: 3, h: 3 }
          : { w: 2, h: 2 };
      return {
        ...widget,
        w: Math.max(minimum.w, Math.min(STUDIO_COLUMNS - widget.x, widget.w + delta)),
        h: Math.max(minimum.h, Math.min(maximumRows - widget.y, widget.h + delta)),
      };
    }));
  }

  function beginStudioInteraction(event: React.PointerEvent, widget: StudioWidget, mode: "move" | "resize") {
    if (!studioEditing || !studioBoardRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    studioInteractionCleanup.current?.();
    setStudioWidgets((current) => [...current.filter((item) => item.id !== widget.id), widget]);
    const boardBounds = studioBoardRef.current.getBoundingClientRect();
    const startX = event.clientX;
    const startY = event.clientY;
    const columnWidth = boardBounds.width / STUDIO_COLUMNS;
    const maximumRows = Math.max(10, Math.floor(boardBounds.height / STUDIO_ROW_HEIGHT));
    const minimum = widget.kind === "capture"
      ? { w: 4, h: 2 }
      : widget.kind === "graph" || widget.kind === "vehicle"
        ? { w: 3, h: 3 }
        : { w: 2, h: 2 };
    const onPointerMove = (moveEvent: PointerEvent) => {
      const deltaColumns = Math.round((moveEvent.clientX - startX) / columnWidth);
      const deltaRows = Math.round((moveEvent.clientY - startY) / STUDIO_ROW_HEIGHT);
      setStudioWidgets((current) => current.map((item) => {
        if (item.id !== widget.id) return item;
        if (mode === "move") {
          return {
            ...item,
            x: Math.max(0, Math.min(STUDIO_COLUMNS - item.w, widget.x + deltaColumns)),
            y: Math.max(0, Math.min(maximumRows - item.h, widget.y + deltaRows)),
          };
        }
        return {
          ...item,
          w: Math.max(minimum.w, Math.min(STUDIO_COLUMNS - item.x, widget.w + deltaColumns)),
          h: Math.max(minimum.h, Math.min(maximumRows - item.y, widget.h + deltaRows)),
        };
      }));
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
      document.body.style.userSelect = "";
      studioInteractionCleanup.current = null;
    };
    studioInteractionCleanup.current = cleanup;
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
  }

  async function toggleStudioFullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function refreshPassiveSensors(openView = false) {
    if (sensorRefreshBusy.current) return;
    sensorRefreshBusy.current = true;
    try {
      const cursor = sensorCursorUs.current;
      const query = new URLSearchParams();
      if (cursor > 0) query.set("since_us", String(cursor));
      if (selectedDiagnosticVin) query.set("vin", selectedDiagnosticVin);
      const path = `/api/live-data/snapshot${query.toString() ? `?${query.toString()}` : ""}`;
      const payload = await api<PassiveSensorSnapshot>(path);
      setPassiveSensors((current) => {
        if (!current || current.session_id !== payload.session_id || cursor === 0) return payload;
        const merged = new Map(current.signals.map((signal) => [signal.key, signal]));
        payload.signals.forEach((signal) => merged.set(signal.key, signal));
        return {
          ...payload,
          signals: Array.from(merged.values()).sort((left, right) =>
            `${left.category}.${left.display_name}`.localeCompare(`${right.category}.${right.display_name}`, "fr"),
          ),
        };
      });
      sensorCursorUs.current = Math.max(cursor, payload.cursor_us);
      setError((current) => current.includes("CAN_TX_ENABLED=true") ? "" : current);
      if (openView) {
        setError("");
        setView("sensors");
      }
    } catch (err) {
      if (openView) setError(err instanceof Error ? err.message : String(err));
    } finally {
      sensorRefreshBusy.current = false;
    }
  }

  async function openPassiveSensors() {
    setError("");
    setView("sensors");
    await Promise.all([refreshPassiveSensors(), refreshLiveSensorDefinitions()]);
  }

  async function refreshLiveSensorDefinitions() {
    try {
      const query = new URLSearchParams();
      if (selectedDiagnosticVin) query.set("vin", selectedDiagnosticVin);
      const definitions = await api<LiveSensorDefinition[]>(
        `/api/live-data/sensors${query.toString() ? `?${query.toString()}` : ""}`,
      );
      setLiveSensorDefinitions(definitions);
    } catch {
      setLiveSensorDefinitions([]);
    }
  }

  async function startFullSensorDetection(openSensors = true, liveDataReads = true) {
    setDetectionBusy(true);
    setError("");
    setSensorCategory("Essentiels");
    setSensorSearch("");
    try {
      const query = selectedDiagnosticVin ? `?vin=${encodeURIComponent(selectedDiagnosticVin)}` : "";
      const endpoint = liveDataReads ? "/api/live-data/detect" : "/api/learn/sensors/passive/detect";
      const payload = await api<PassiveSensorSnapshot>(`${endpoint}${query}`, {
        method: "POST",
      });
      sensorCursorUs.current = payload.cursor_us;
      setPassiveSensors(payload);
      if (openSensors) setView("sensors");
      setDetectionEndsAt(Date.now() + 30_000);
      setDetectionRemaining(30);
      await refreshCapture();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetectionBusy(false);
    }
  }

  function editPassiveSensor(signal: PassiveCanSignal) {
    setSensorEditor({
      key: signal.key,
      label: signal.display_name,
      description: signal.description,
      unit: signal.unit ?? "",
      factor: String(signal.factor),
      offset: String(signal.offset),
      customized: signal.customized,
    });
  }

  async function savePassiveSensorOverride(event: React.FormEvent) {
    event.preventDefault();
    if (!sensorEditor) return;
    setSensorEditorBusy(true);
    setError("");
    try {
      await api("/api/learn/sensors/passive/override", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key: sensorEditor.key,
          label: sensorEditor.label.trim() || null,
          description: sensorEditor.description.trim() || null,
          unit: sensorEditor.unit.trim(),
          factor: Number(sensorEditor.factor),
          offset: Number(sensorEditor.offset),
        }),
      });
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSensorEditorBusy(false);
    }
  }

  async function resetPassiveSensorOverride() {
    if (!sensorEditor) return;
    setSensorEditorBusy(true);
    setError("");
    try {
      await api(`/api/learn/sensors/passive/override/${encodeURIComponent(sensorEditor.key)}`, {
        method: "DELETE",
      });
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSensorEditorBusy(false);
    }
  }

  function createLiveSensor() {
    if (!selectedDiagnosticVin) {
      setError("Charge d’abord un véhicule dans le Garage pour rattacher ce capteur à son VIN.");
      return;
    }
    const source = passiveSensors?.signals.find((signal) => !signal.user_defined);
    if (!source) {
      setError("Aucune source CAN ou OBD décodée n’est disponible pour créer un capteur.");
      return;
    }
    setLiveSensorEditor({
      sourceKey: source.key,
      label: "",
      description: "",
      category: source.category || "Personnalisés",
      unit: source.unit ?? "",
      factor: "1",
      offset: "0",
    });
  }

  function editLiveSensor(signal: PassiveCanSignal) {
    const definition = liveSensorDefinitions.find((item) => item.key === signal.definition_key);
    if (!definition) {
      setError("Définition locale de ce capteur introuvable.");
      return;
    }
    setLiveSensorEditor({
      key: definition.key,
      sourceKey: definition.source_key,
      label: definition.label,
      description: definition.description,
      category: definition.category,
      unit: definition.unit ?? "",
      factor: String(definition.factor),
      offset: String(definition.offset),
    });
  }

  async function saveLiveSensor(event: React.FormEvent) {
    event.preventDefault();
    if (!liveSensorEditor) return;
    setLiveSensorEditorBusy(true);
    setError("");
    const editing = Boolean(liveSensorEditor.key);
    try {
      const common = {
        label: liveSensorEditor.label.trim(),
        description: liveSensorEditor.description.trim(),
        category: liveSensorEditor.category.trim() || "Personnalisés",
        unit: liveSensorEditor.unit.trim() || null,
        factor: Number(liveSensorEditor.factor),
        offset: Number(liveSensorEditor.offset),
      };
      await api(
        editing
          ? `/api/live-data/sensors/${encodeURIComponent(liveSensorEditor.key!)}`
          : "/api/live-data/sensors",
        {
          method: editing ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(editing
            ? { ...common, archived: false }
            : {
                ...common,
                source_key: liveSensorEditor.sourceKey,
                vin: selectedDiagnosticVin || null,
              }),
        },
      );
      await refreshLiveSensorDefinitions();
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setLiveSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLiveSensorEditorBusy(false);
    }
  }

  async function archiveLiveSensor() {
    if (!liveSensorEditor?.key) return;
    if (!window.confirm("Supprimer ce capteur des vues Live Data ? Son historique restera conservé.")) return;
    setLiveSensorEditorBusy(true);
    setError("");
    try {
      await api(`/api/live-data/sensors/${encodeURIComponent(liveSensorEditor.key)}`, {
        method: "DELETE",
      });
      await refreshLiveSensorDefinitions();
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setLiveSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLiveSensorEditorBusy(false);
    }
  }

  async function refreshDiagnosticHistory(preferredVin?: string, preferredProfile?: string) {
    try {
      const [vehicles, activeVehicle] = await Promise.all([
        api<DiagnosticVehicle[]>("/api/diagnostic/vehicles"),
        api<DiagnosticVehicle>("/api/diagnostic/vehicles/active").catch(() => null),
      ]);
      setDiagnosticVehicles(vehicles);
      const rememberedVin = preferredVin ?? activeVehicle?.vin ?? selectedDiagnosticVin;
      const selected = vehicles.some((vehicle) => vehicle.vin === rememberedVin)
        ? rememberedVin
        : vehicles[0]?.vin ?? "";
      const profile = preferredProfile
        ?? vehicles.find((vehicle) => vehicle.vin === selected)?.vehicle_profile
        ?? status?.vehicle_profile
        ?? identityProfileKey;
      setSelectedDiagnosticVin(selected);

      const query = new URLSearchParams();
      if (selected) query.set("vin", selected);
      else if (profile) query.set("vehicle_profile", profile);
      const suffix = query.toString() ? `?${query.toString()}` : "";
      const [latest, history, observations] = await Promise.all([
        api<Report>(`/api/diagnostic/reports/latest${suffix}`).catch(() => null),
        api<DiagnosticReportSummary[]>(`/api/diagnostic/reports${suffix}`).catch(() => []),
        api<ObservedDtc[]>(`/api/diagnostic/dtcs/observed${suffix}`).catch(() => []),
      ]);
      setReport(latest);
      setDiagnosticReportHistory(history);
      setObservedDtcs(observations);
    } catch {
      setDiagnosticVehicles([]);
      setDiagnosticReportHistory([]);
      setObservedDtcs([]);
    }
  }

  async function selectDiagnosticVehicle(vin: string) {
    if (!vin || vin === selectedDiagnosticVin) return;
    if (capture?.active) {
      setError("Arrête et sauvegarde la capture avant de changer de véhicule : elle est déjà rattachée au VIN actif.");
      return;
    }
    setVehicleSelectionBusy(true);
    setError("");
    const previousVin = selectedDiagnosticVin;
    setSelectedDiagnosticVin(vin);
    setReport(null);
    setDiagnosticReportHistory([]);
    setObservedDtcs([]);
    setInjectionSnapshot(null);
    setVehicleIdentity(null);
    setReplay(null);
    setReplayValidation(null);
    setReplaySessionId("");
    const profile = diagnosticVehicles.find((vehicle) => vehicle.vin === vin)?.vehicle_profile;
    if (profile) setIdentityProfileKey(profile);
    try {
      await api<DiagnosticVehicle>("/api/diagnostic/vehicles/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vin }),
      });
      await refreshDiagnosticHistory(vin, profile);
    } catch (err) {
      setSelectedDiagnosticVin(previousVin);
      await refreshDiagnosticHistory(previousVin || undefined);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setVehicleSelectionBusy(false);
    }
  }

  async function assignSessionsToActiveVehicle(sessionIds: string[]) {
    if (!selectedDiagnosticVehicle || !sessionIds.length) return;
    setSessionAssignmentBusy(sessionIds.length === 1 ? sessionIds[0] : "bulk");
    setError("");
    try {
      await Promise.all(sessionIds.map((sessionId) => api(`/api/learn/sessions/${encodeURIComponent(sessionId)}/vehicle`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vin: selectedDiagnosticVehicle.vin,
          vehicle_profile: selectedDiagnosticVehicle.vehicle_profile,
          vehicle_label: `${selectedDiagnosticVehicle.manufacturer} ${selectedDiagnosticVehicle.model}`,
        }),
      })));
      await refreshSessions();
      if (replaySessionId && sessionIds.includes(replaySessionId)) await loadReplay(replaySessionId, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSessionAssignmentBusy("");
    }
  }

  async function selectDiagnosticReport(scanId: string) {
    if (!scanId) return;
    setError("");
    try {
      const selected = await api<Report>(`/api/diagnostic/reports/${encodeURIComponent(scanId)}`);
      setReport(selected);
      setDiagnosticRegression(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function verifyDiagnosticRegression(scanId = report?.scan_id) {
    if (!scanId) return;
    setDiagnosticRegressionBusy(true);
    setError("");
    try {
      const result = await api<RegressionResult>(
        `/api/diagnostic/reports/${encodeURIComponent(scanId)}/regression`,
      );
      setDiagnosticRegression(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiagnosticRegressionBusy(false);
    }
  }

  async function importDiagnosticTrace(file: File | undefined) {
    if (!file) return;
    setTraceImportBusy(true);
    setTraceImportResult(null);
    setError("");
    try {
      const content = await file.text();
      const result = await api<TraceImportResult>("/api/diagnostic/traces/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: file.name,
          content,
          vehicle_profile: report?.vehicle_profile ?? identityProfileKey,
          source_format: "auto",
        }),
      });
      setTraceImportResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTraceImportBusy(false);
    }
  }

  async function clearSelectedEcuDtcs() {
    if (!dtcClearEcuKey) return;
    setDtcClearBusy(true);
    setDtcClearResult(null);
    setError("");
    try {
      const result = await api<ClearDtcResult>(
        `/api/diagnostic/ecus/${encodeURIComponent(dtcClearEcuKey)}/dtcs/clear`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation: dtcClearConfirmation,
            ...dtcClearChecks,
          }),
        },
      );
      setDtcClearResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDtcClearBusy(false);
    }
  }

  async function readDtcSnapshot(ecuKey: string, dtc: DtcValue) {
    const resultKey = `${ecuKey}-${dtc.raw_hex}`;
    setDtcSnapshotBusy(resultKey);
    setError("");
    try {
      const result = await api<DtcSnapshotResult>(
        `/api/diagnostic/ecus/${encodeURIComponent(ecuKey)}/dtcs/snapshot`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dtc_raw_hex: dtc.raw_hex }),
        },
      );
      setDtcSnapshotResults((current) => ({ ...current, [resultKey]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDtcSnapshotBusy("");
    }
  }

  async function sweepSelectedEcuDids() {
    if (!selectedEcu) return;
    const start = parseInt(didSweepStart.trim().replace(/^0x/i, ""), 16);
    const end = parseInt(didSweepEnd.trim().replace(/^0x/i, ""), 16);
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      setError("Les bornes du balayage DID doivent être des valeurs hexadécimales valides.");
      return;
    }
    setDidSweepBusy(true);
    setDidSweepResult(null);
    setError("");
    try {
      const result = await api<DidSweepResult>(
        `/api/diagnostic/ecus/${encodeURIComponent(selectedEcu.key)}/dids/sweep`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ did_start: start, did_end: end }),
        },
      );
      setDidSweepResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDidSweepBusy(false);
    }
  }

  async function scan() {
    if (capture?.active && !dualCanOperational) {
      setError("Arrête et sauvegarde la capture CAN avant de lancer l’inventaire UDS.");
      return;
    }
    if (!status?.can_tx_enabled) {
      setError("Les requêtes de lecture CAN sont verrouillées dans la configuration actuelle.");
      return;
    }
    if (!diagnosticGatewayVerified) {
      setError("Connecte et valide d’abord l’ESP32 diagnostic depuis le Dashboard direct.");
      setView("studio");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const vehicle = diagnosticVehicles.find((candidate) => candidate.vin === selectedDiagnosticVin);
      const payload = await api<Report>("/api/diagnostic/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vehicle_profile: vehicle?.vehicle_profile ?? identityProfileKey ?? status?.vehicle_profile,
          vin: selectedDiagnosticVin || null,
          extended_probe: extendedProbeEnabled,
        }),
      });
      setReport(payload);
      setDiagnosticRegression(null);
      if (payload.vin) setSelectedDiagnosticVin(payload.vin);
      await refreshDiagnosticHistory(payload.vin ?? undefined, payload.vehicle_profile);
      if (payload.scan_id) await verifyDiagnosticRegression(payload.scan_id);
      setView("ecus");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function readInjectionParameters(destination: View = "injection") {
    if (capture?.active && !dualCanOperational) {
      setError("Arrête et sauvegarde la capture CAN avant de lire les paramètres d’injection.");
      return;
    }
    if (!status?.can_tx_enabled) {
      setError("Les lectures OBD-II sont verrouillées dans la configuration actuelle.");
      return;
    }
    if (!diagnosticGatewayVerified) {
      setError("Connecte et valide d’abord l’ESP32 diagnostic depuis le Dashboard direct.");
      setView("studio");
      return;
    }
    if (!liveObdReadOnly) {
      setError("Le firmware principal doit annoncer live_obd_read_only=true pour autoriser les lectures OBD normalisées sur 6/14.");
      setView("studio");
      return;
    }
    setInjectionBusy(true);
    setError("");
    try {
      const profile = selectedDiagnosticVehicle?.vehicle_profile ?? identityProfileKey ?? status?.vehicle_profile;
      const query = profile ? `?vehicle_profile=${encodeURIComponent(profile)}` : "";
      const payload = await api<DiagnosticSensorSnapshot>(`/api/sensors/snapshot${query}`, { method: "POST" });
      setInjectionSnapshot(payload);
      setView(destination);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInjectionBusy(false);
    }
  }

  async function readVehicleIdentity() {
    if (capture?.active && !dualCanOperational) {
      setError("Arrête et sauvegarde la capture CAN avant de lire l’identité du véhicule.");
      return;
    }
    if (!identityReadReady) {
      setError(status?.can_tx_enabled
        ? selectedIdentityProfile?.identity_scope === "identity_only" && !liveObdReadOnly
          ? "Le firmware principal doit autoriser les lectures OBD 01/09 filtrées sur 6/14 pour identifier ce véhicule."
          : "Connecte et valide d’abord l’ESP32 avec le firmware diagnostic en lecture seule."
        : "La lecture VIN nécessite des requêtes OBD/UDS de lecture (CAN_TX_ENABLED=true)."
      );
      return;
    }
    setIdentityBusy(true);
    setError("");
    try {
      const result = await api<VehicleIdentityResult>("/api/diagnostic/identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vehicle_profile: identityProfileKey }),
      });
      setVehicleIdentity(result);
      if (result.vin) {
        setSelectedDiagnosticVin(result.vin);
        await refreshDiagnosticHistory(result.vin, result.vehicle_profile);
      }
      setView("identity");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIdentityBusy(false);
    }
  }

  async function readEngineObdDtcs() {
    setObdDtcBusy(true);
    setError("");
    try {
      const result = await api<Ecu>(
        `/api/diagnostic/obd/dtcs?ecu_key=engine&vehicle_profile=${encodeURIComponent(identityProfileKey)}`,
        { method: "POST" },
      );
      setObdDtcResult(result);
    } catch (err) {
      setObdDtcResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setObdDtcBusy(false);
    }
  }

  async function testUdsPresence() {
    setUdsProbeBusy(true);
    setUdsProbeResult(null);
    setError("");
    try {
      const result = await api<DidValue>(
        `/api/diagnostic/ecus/${encodeURIComponent(udsProbeEcuKey)}/dids/0xF186?vehicle_profile=${encodeURIComponent(identityProfileKey)}`,
        { method: "POST" },
      );
      setUdsProbeResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUdsProbeBusy(false);
    }
  }

  async function readPsaDid() {
    if (!psaVehicleCompatible) {
      setError("Le véhicule actif n’est pas un profil PSA compatible. Charge la Peugeot depuis le Garage avant toute lecture constructeur.");
      setView("garage");
      return;
    }
    if (!diagnosticReady) {
      setError(capture?.active && !dualCanOperational
        ? "Arrête et sauvegarde la capture avant une lecture UDS PSA."
        : "Connecte un firmware diagnostic compatible et active les requêtes CAN en lecture.");
      return;
    }
    const normalizedDid = psaDid.trim().replace(/^0x/i, "");
    if (!/^[0-9a-fA-F]{1,4}$/.test(normalizedDid)) {
      setError("Le DID PSA doit contenir de 1 à 4 chiffres hexadécimaux.");
      return;
    }
    setPsaBusy("did");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<DidValue>(`/api/diagnostic/psa/ecus/${encodeURIComponent(psaEcuKey)}/dids/0x${normalizedDid}`, { method: "POST" });
      setPsaDidResult(result);
      setPsaFeedback(`Zone 0x${normalizedDid.toUpperCase().padStart(4, "0")} reçue depuis ${selectedPsaEcu?.name ?? psaEcuKey}.`);
    } catch (err) {
      setPsaDidResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function calculatePsaSeedKey() {
    setPsaBusy("seed");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<PsaSeedKeyResult>("/api/diagnostic/psa/seed-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed_hex: psaSeed.trim(), application_key_hex: psaApplicationKey.trim() }),
      });
      setPsaSeedResult(result);
      setPsaFeedback("Clé calculée localement : aucune trame n'a été envoyée au véhicule.");
    } catch (err) {
      setPsaSeedResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function unlockPsaConfiguration() {
    if (!psaVehicleCompatible) {
      setError("SecurityAccess PSA refusé : le véhicule actif n’est pas un profil PSA compatible.");
      setView("garage");
      return;
    }
    setPsaBusy("unlock");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<PsaUnlockResult>(`/api/diagnostic/psa/ecus/${encodeURIComponent(psaUnlockEcuKey)}/unlock`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          application_key_hex: psaUnlockApplicationKey.trim(),
          confirmation: psaUnlockConfirmation,
          ...effectivePsaLabChecks,
        }),
      });
      setPsaFeedback(`${result.message} Seed ${result.seed_hex} · key ${result.response_key_hex}.`);
      setPsaUnlockConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function executePsaAction() {
    if (!psaVehicleCompatible) {
      setError("Commande PSA refusée : charge d’abord un véhicule PSA compatible depuis le Garage.");
      setView("garage");
      return;
    }
    if (!selectedPsaAction) return;
    setPsaBusy("action");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<PsaActionResult>(`/api/diagnostic/psa/actions/${encodeURIComponent(selectedPsaAction.key)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmation: psaConfirmation,
          duration_ms: psaDurationMs,
          ...effectivePsaLabChecks,
        }),
      });
      setPsaFeedback(`${result.message}${result.session_id ? ` Trace ${result.session_id}.` : ""}`);
      setPsaConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function startCapture(enableLiveDataReads = true) {
    if (transportConnectBusy) return;
    setError("");
    try {
      const endpoint = enableLiveDataReads ? "/api/live-data/start" : "/api/learn/capture/start";
      const payload = await api<CaptureStatus>(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: captureName,
          note: captureNote || null,
          vin: selectedDiagnosticVehicle?.vin ?? null,
          vehicle_profile: activeCommunicationProfileKey || status?.vehicle_profile || null,
          vehicle_label: activeCommunicationProfile
            ? `${activeCommunicationProfile.manufacturer} ${activeCommunicationProfile.model}`
            : null,
        }),
      });
      setCapture(payload);
      setAnalysis(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function stopCapture() {
    setError("");
    try {
      const payload = await api<CaptureStatus>("/api/learn/capture/stop", { method: "POST" });
      setCapture(payload);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function addMarker(name = markerName) {
    if (!name.trim()) return;
    setError("");
    try {
      const payload = await api<CaptureStatus>("/api/learn/capture/marker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), note: markerNote || null }),
      });
      setCapture(payload);
      setMarkerName(name.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function analyzeSession(sessionId: string, saved = false) {
    setAnalysisBusy(sessionId);
    setError("");
    try {
      const path = saved
        ? `/api/learn/correlations/${sessionId}`
        : `/api/learn/correlate/${sessionId}`;
      const payload = await api<BehavioralAnalysis>(path, saved ? undefined : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          before_ms: 1200,
          after_ms: 1200,
          min_samples: 3,
          max_candidates_per_marker: 40,
        }),
      });
      setAnalysis(payload);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalysisBusy("");
    }
  }

  function renderReplay() {
    const playableSessions = sessions.filter((session) => session.frame_count > 0 && (
      !selectedDiagnosticVin || !session.vin || session.vin === selectedDiagnosticVin
    ));
    const activeVehicleReplays = playableSessions.filter((session) => session.vin === selectedDiagnosticVin);
    const unassignedReplays = playableSessions.filter((session) => !session.vin);
    const selector = (
      <section className="panel replay-selector">
        <div>
          <span className="eyebrow">Source du replay</span>
          <strong>{replay?.name ?? "Choisir un enregistrement CAN"}</strong>
          <small>{replay
            ? `${replay.frame_count.toLocaleString("fr-FR")} trames · ${formatDuration(replay.duration_ms)} · ${(replay.source_size_bytes / 1024 / 1024).toFixed(1)} Mio`
            : "Le premier chargement prépare un cache de post-traitement sur le PC."}</small>
        </div>
        <select
          aria-label="Session à rejouer"
          value={replaySessionId}
          disabled={replayBusy || playableSessions.length === 0}
          onChange={(event) => void loadReplay(event.target.value)}
        >
          {!replaySessionId && <option value="">Sélectionner une session</option>}
          {activeVehicleReplays.length > 0 && <optgroup label={activeVehicleLabel}>{activeVehicleReplays.map((session) => (
            <option key={session.session_id} value={session.session_id}>{formatDate(session.started_at_us)} · {session.name}</option>
          ))}</optgroup>}
          {unassignedReplays.length > 0 && <optgroup label="Anciennes captures sans VIN">{unassignedReplays.map((session) => (
            <option key={session.session_id} value={session.session_id}>{formatDate(session.started_at_us)} · {session.name}</option>
          ))}</optgroup>}
        </select>
        <button
          className="ghost-button"
          disabled={!replaySessionId || replayBusy}
          onClick={() => void loadReplay(replaySessionId, true)}
        >
          Recalculer
        </button>
      </section>
    );

    if (playableSessions.length === 0 && !replayBusy) {
      return <>{selector}<section className="panel"><EmptyState title="Aucun trajet enregistré" text="Enregistre d'abord une session CAN, puis reviens ici pour la rejouer." action={<button className="primary-button" onClick={() => setView("discovery")}>Ouvrir l'enregistrement</button>} /></section></>;
    }
    if (replayBusy || !replay || !currentReplayPoint) {
      return <>{selector}<section className="panel replay-loading"><EmptyState title="Préparation du trajet…" text="Décodage CAN, échantillonnage temporel et reconstruction locale de la trajectoire. La capture originale reste intacte." /></section></>;
    }
    const replayIsFiat500 = replay.vehicle_profile === "fiat_500_generic";
    const replayVisual = vehicleVisualForProfile(replay.vehicle_profile);
    const replayProfileCompatible = !replay.vehicle_profile || replayIsFiat500 || replay.vehicle_profile.startsWith("peugeot_") || replay.vehicle_profile.startsWith("psa_");
    if (!replayProfileCompatible) {
      return <>{selector}<section className="panel"><EmptyState title={`Replay visuel indisponible pour ${replay.vehicle}`} text="La capture est correctement classée sous ce VIN, mais le décodeur dynamique Fiat n’est pas encore validé. Le fichier CAN brut reste conservé et analysable sans afficher de fausses valeurs Peugeot." action={<button className="secondary-button" onClick={() => setView("discovery")}>Ouvrir l’analyse brute</button>} /></section></>;
    }

    const point = currentReplayPoint;
    const coordinate = currentRouteGeometry.coordinates[currentReplayIndex] ?? { x: 380, y: 235 };
    const progress = replay.duration_ms ? replayTimeMs / replay.duration_ms : 0;
    const speed = Math.max(0, point.speed_kph ?? 0);
    const rpm = Math.max(0, point.engine_rpm ?? 0);
    const currentGearLabel = point.reverse || point.current_gear === 9 ? "R" : typeof point.current_gear === "number" ? point.current_gear > 0 ? String(point.current_gear) : "N" : "—";
    const targetGearLabel = point.reverse || point.target_gear === 9 ? "R" : (point.target_gear ?? 0) > 0 ? String(point.target_gear) : "—";
    const steeringAvailable = typeof point.steering_angle_deg === "number";
    const steering = point.steering_angle_deg ?? 0;
    const acceleratorAvailable = typeof point.accelerator_pct === "number";
    const accelerator = Math.max(0, Math.min(100, point.accelerator_pct ?? 0));
    const brakeAvailable = typeof point.brake_active === "boolean";
    const blinkOn = Math.floor(replayTimeMs / 430) % 2 === 0;
    const leftIndicator = blinkOn && ["left", "hazard"].includes(point.turn_signal ?? "off");
    const rightIndicator = blinkOn && ["right", "hazard"].includes(point.turn_signal ?? "off");
    const indicatorLabel = point.turn_signal === "left"
      ? "Gauche"
      : point.turn_signal === "right"
        ? "Droite"
        : point.turn_signal === "hazard" ? "Détresse" : "Arrêt";
    const laneDeparture = point.lane_departure === 1 ? "right" : point.lane_departure === 2 ? "left" : "none";
    const speedGaugeAngle = Math.min(270, speed / Math.max(140, replay.max_speed_kph) * 270);
    const replayDate = new Date(replay.start_timestamp_us / 1000);
    const roadConfirmed = replay.route_method === "driver_confirmed_osrm";
    const yawReconstructed = replay.route_method === "dead_reckoning_speed_yaw";
    const gpsFused = replay.route_method === "gps_can_fusion";
    const gpsMeasured = replay.route_method === "browser_gps" || gpsFused || roadConfirmed;
    const gpsAnchored = replay.route_method === "dead_reckoning_gps_anchor";
    const openStreetMapUrl = point.latitude !== null && point.latitude !== undefined && point.longitude !== null && point.longitude !== undefined
      ? `https://www.openstreetmap.org/?mlat=${point.latitude}&mlon=${point.longitude}#map=16/${point.latitude}/${point.longitude}`
      : "";
    const steeringDirection = Math.abs(steering) < 1 ? "centré" : steering < 0 ? "droite" : "gauche";
    const availableGaugeDefinitions = replayGaugeCatalog.filter((definition) =>
      replay.available_fields.includes(definition.key)
      && !definition.rejected
      && replay.field_quality[String(definition.key)] !== "rejected_on_vehicle"
    );
    const selectedGaugeDefinitions = selectedReplayGaugeKeys
      .map((key) => availableGaugeDefinitions.find((definition) => definition.key === key))
      .filter((definition): definition is ReplayGaugeDefinition => definition !== undefined);
    const addableGaugeDefinitions = availableGaugeDefinitions.filter((definition) => !selectedReplayGaugeKeys.includes(definition.key));
    const availableGraphDefinitions = availableGaugeDefinitions.filter((definition) => !definition.status);
    const selectedGraphDefinitions = selectedReplayGraphKeys
      .map((key) => availableGraphDefinitions.find((definition) => definition.key === key))
      .filter((definition): definition is ReplayGaugeDefinition => definition !== undefined);
    const addableGraphDefinitions = availableGraphDefinitions.filter((definition) => !selectedReplayGraphKeys.includes(definition.key));
    const selectedIndicatorDefinitions = selectedReplayIndicatorKeys
      .map((key) => replayIndicatorCatalog.find((definition) => definition.key === key))
      .filter((definition): definition is ReplayIndicatorDefinition => definition !== undefined);
    const addableIndicatorDefinitions = replayIndicatorCatalog.filter((definition) => !selectedReplayIndicatorKeys.includes(definition.key));
    const validationByKey = new Map((replayValidation?.signals ?? []).map((item) => [item.key, item]));
    const unavailableValidationCount = (replayValidation?.signals ?? []).filter((item) => item.status === "unavailable").length;
    const candidateValidationCount = replayValidation
      ? replayValidation.signal_count - replayValidation.validated_count - replayValidation.plausible_count - replayValidation.suspicious_count - unavailableValidationCount
      : 0;

    return (
      <div className="replay-page">
        {selector}
        {replay.vin && replay.vin !== selectedDiagnosticVin && <p className="inline-alert danger-alert">Ce replay appartient au VIN {replay.vin}, différent du véhicule actif. Recharge le bon véhicule depuis le Garage.</p>}
        {!replay.vin && selectedDiagnosticVehicle && <div className="replay-assignment-strip"><div><strong>Capture non classée</strong><span>Associe-la à {activeVehicleLabel} pour l’intégrer à sa chronologie.</span></div><button className="secondary-button" disabled={Boolean(sessionAssignmentBusy)} onClick={() => void assignSessionsToActiveVehicle([replay.session_id])}>{sessionAssignmentBusy === replay.session_id ? "Association…" : "Associer au véhicule actif"}</button></div>}

        <section className="replay-summary-grid">
          <article><span>{roadConfirmed ? "Distance routière" : gpsMeasured ? "Distance GPS" : "Distance reconstruite"}</span><strong>{replay.distance_km.toFixed(2)} <small>km</small></strong></article>
          <article><span>Vitesse maximale</span><strong>{replay.max_speed_kph.toFixed(1)} <small>km/h</small></strong></article>
          <article><span>Vitesse moyenne roulante</span><strong>{replay.average_moving_speed_kph.toFixed(1)} <small>km/h</small></strong></article>
          <article><span>Début des données</span><strong>{replayDate.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</strong></article>
        </section>

        <section className="panel fuel-consumption-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Estimation trajet</span>
              <h2>Consommation</h2>
              <p>Calculée à partir du niveau de carburant filtré (flotteur), sur ce trajet uniquement — pas un débitmètre instantané.</p>
            </div>
          </div>
          {typeof replay.estimated_fuel_consumption_l_100km === "number" ? (
            <div className="fuel-consumption-value">
              <strong>{replay.estimated_fuel_consumption_l_100km.toFixed(1)}</strong>
              <span>L/100km · estimation</span>
            </div>
          ) : (
            <p className="inline-alert">{replay.fuel_consumption_note ?? "Estimation non calculable sur cette capture."}</p>
          )}
          {typeof replay.estimated_fuel_consumption_l_100km === "number" && replay.fuel_consumption_note && (
            <p className="fuel-consumption-note">{replay.fuel_consumption_note}</p>
          )}
        </section>

        <ExperimentalSignalsPanel
          point={point}
          validation={replayValidation}
          onValidate={(key, validated) => void setSignalManualValidation(key, validated)}
          onClear={(key) => void clearSignalManualValidation(key)}
          busyKey={signalValidationBusy}
        />

        {replayValidation && (
          <section className="panel replay-validation-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Contrôle de cohérence de la capture</span>
                <h2>Validation des capteurs, jauges et rapports</h2>
                <p>Preuves croisées moteur, injection, freinage, roues, direction et détection des mesures absentes ou invalides.</p>
              </div>
              <span className={`source-badge ${replayValidation.suspicious_count ? "suspicious" : "measured"}`}>{replayValidation.suspicious_count ? `${replayValidation.suspicious_count} à vérifier` : "Aucune incohérence forte"}</span>
            </div>
            <div className="validation-summary-grid">
              <article><span>Validés</span><strong>{replayValidation.validated_count}</strong><small>Preuve croisée ou test véhicule</small></article>
              <article><span>Plausibles</span><strong>{replayValidation.plausible_count}</strong><small>Plage cohérente, étalon absent</small></article>
              <article><span>À confirmer</span><strong>{candidateValidationCount}</strong><small>Candidat sans preuve suffisante</small></article>
              <article><span>Suspects</span><strong>{replayValidation.suspicious_count}</strong><small>Incohérence ou hors plage</small></article>
              <article><span>Indisponibles</span><strong>{unavailableValidationCount}</strong><small>Non mesuré sur le CAN passif</small></article>
            </div>
            <details className="validation-details">
              <summary>Voir le détail des {replayValidation.signal_count} signaux</summary>
              <div className="validation-signal-list">
                {replayValidation.signals.map((signal) => (
                  <article className={signal.status} key={signal.key}>
                    <span className={`validation-badge ${signal.status}`}>{signal.status === "validated" ? "Validé" : signal.status === "plausible" ? "Plausible" : signal.status === "suspicious" ? "Suspect" : signal.status === "unavailable" ? "Indisponible" : "À confirmer"}</span>
                    <div><strong>{signal.label}</strong><code>{signal.key}</code>{signal.evidence.map((line) => <p key={line}>{line}</p>)}</div>
                    <small>{signal.sample_count.toLocaleString("fr-FR")} valeurs · {signal.transitions} transitions{signal.minimum !== null && signal.minimum !== undefined ? ` · ${signal.minimum}…${signal.maximum}` : ""}</small>
                    {signal.status !== "unavailable" && (
                      <div className="validation-manual-actions">
                        {signal.manual_validation === true ? (
                          <>
                            <span className="manual-validation-tag confirmed">Confirmé manuellement</span>
                            <button className="ghost-button" disabled={signalValidationBusy === signal.key} onClick={() => void clearSignalManualValidation(signal.key)}>Retirer</button>
                          </>
                        ) : signal.manual_validation === false ? (
                          <>
                            <span className="manual-validation-tag rejected">Invalidé manuellement</span>
                            <button className="ghost-button" disabled={signalValidationBusy === signal.key} onClick={() => void clearSignalManualValidation(signal.key)}>Retirer</button>
                          </>
                        ) : (
                          <>
                            <button className="secondary-button" disabled={signalValidationBusy === signal.key} onClick={() => void setSignalManualValidation(signal.key, true)}>{signalValidationBusy === signal.key ? "…" : "Confirmer ce signal"}</button>
                            <button className="ghost-button" disabled={signalValidationBusy === signal.key} onClick={() => void setSignalManualValidation(signal.key, false)}>Marquer invalide</button>
                          </>
                        )}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </details>
          </section>
        )}

        <section className="replay-hero-grid">
          <article className="panel replay-map-panel">
            <div className="section-heading replay-map-heading">
              <div>
                <span className="eyebrow">Carte de mouvement</span>
                <h2>{roadConfirmed ? "Parcours routier confirmé" : gpsFused ? "Parcours réel avec virages CAN" : gpsMeasured ? "Trajet GPS enregistré" : gpsAnchored ? "Trajectoire ancrée par GPS" : yawReconstructed ? "Trajectoire CAN par lacet ESP" : "Trajectoire locale reconstruite"}</h2>
                <p>{roadConfirmed
                  ? "Francazal → Portet → A64 → périphérique extérieur A620 → Rangueil · progression synchronisée par la vitesse CAN"
                  : gpsFused
                  ? `${replay.gps_point_count.toLocaleString("fr-FR")} positions GPS · virages reconstruits par vitesse et volant puis recalés sur le GPS`
                  : gpsMeasured ? `${replay.gps_point_count.toLocaleString("fr-FR")} positions synchronisées avec les trames CAN`
                  : gpsAnchored ? "Une position absolue + déplacement estimé par vitesse et volant" : "Vitesse ABS + angle du volant · origine et orientation arbitraires"}</p>
              </div>
              <div className="replay-map-actions">
                <span className={`source-badge ${gpsMeasured ? "measured" : "estimated"}`}>{roadConfirmed ? "Route confirmée" : gpsFused ? "GPS + CAN" : gpsMeasured ? "GPS réel" : gpsAnchored ? "GPS ancré" : yawReconstructed ? "Lacet ESP" : "GPS absent"}</span>
                {replay.gps_available && <a className="ghost-button" href={`${API_BASE}/api/learn/replay/${encodeURIComponent(replay.session_id)}/route.geojson`} download={`${replay.session_id}.geojson`}>Exporter GeoJSON</a>}
                {openStreetMapUrl && <a className="ghost-button" href={openStreetMapUrl} target="_blank" rel="noreferrer">Voir sur OSM</a>}
              </div>
            </div>
            <div className="route-map">
              <svg viewBox="0 0 760 470" role="img" aria-label={roadConfirmed ? "Trajet routier confirmé par le conducteur" : gpsMeasured ? "Trajet mesuré par GPS" : "Trajectoire reconstruite sans trace GPS complète"}>
                <defs>
                  <pattern id="map-grid" width="30" height="30" patternUnits="userSpaceOnUse">
                    <path d="M 30 0 L 0 0 0 30" className="map-grid-line" fill="none" />
                  </pattern>
                  <filter id="route-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                  </filter>
                </defs>
                {currentRouteGeometry.mapTiles.length
                  ? currentRouteGeometry.mapTiles.map((tile) => (
                    <image key={tile.key} href={tile.href} x={tile.x} y={tile.y} width="256" height="256" className="osm-tile" />
                  ))
                  : <rect width="760" height="470" fill="url(#map-grid)" />}
                {!currentRouteGeometry.mapTiles.length && !replay.gps_available && <>
                  <path className="france-silhouette" d="M333 36 L409 54 466 91 489 139 527 174 506 221 521 262 478 295 456 352 404 405 357 438 314 405 264 386 231 342 196 319 207 266 184 218 215 174 221 121 273 96 292 55 Z" />
                  <path className="france-corsica" d="M529 350 C544 358 548 382 536 401 C525 388 520 367 529 350 Z" />
                  <text x="380" y="240" className="map-watermark">FRANCE · POSITION ABSOLUE INDISPONIBLE</text>
                </>}
                <path d={currentRouteGeometry.path} className="route-shadow" />
                <path d={currentRouteGeometry.path} className="route-trace" pathLength={100} />
                <path
                  d={currentRouteGeometry.path}
                  className="route-progress"
                  pathLength={100}
                  strokeDasharray="100"
                  strokeDashoffset={100 - progress * 100}
                  filter="url(#route-glow)"
                />
                {currentRouteGeometry.gpsCoordinates.map((gpsPoint, index) => <g key={`gps-${index}`} className="gps-fix">
                  <circle cx={gpsPoint.x} cy={gpsPoint.y} r={gpsPoint.accuracyPx} className="gps-accuracy" />
                  <circle cx={gpsPoint.x} cy={gpsPoint.y} r="3.5" className="gps-fix-center" />
                </g>)}
                <circle cx={currentRouteGeometry.coordinates[0]?.x} cy={currentRouteGeometry.coordinates[0]?.y} r="5" className="route-start" />
                <image
                  href={replayVisual.topImage}
                  x={coordinate.x - 26}
                  y={coordinate.y - 26}
                  width="52"
                  height="52"
                  transform={`rotate(${point.heading_deg + (replayVisual.frontAtTop ? 0 : 180)} ${coordinate.x} ${coordinate.y})`}
                  className="map-car"
                />
                <circle cx={coordinate.x} cy={coordinate.y} r="3" className="map-car-center" />
              </svg>
              {currentRouteGeometry.mapTiles.length > 0 && <div className="osm-attribution">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors</div>}
              <div className="map-readout">
                <span><i className="measured-dot" />Vitesse mesurée <strong>{speed.toFixed(1)} km/h</strong></span>
                <span><i className={gpsMeasured ? "measured-dot" : "estimated-dot"} />Cap {roadConfirmed ? "routier" : gpsFused ? "CAN recalé" : gpsMeasured ? "GPS" : "estimé"} <strong>{point.heading_deg.toFixed(0)}°</strong></span>
                <span>Distance <strong>{(point.distance_m / 1000).toFixed(2)} km</strong></span>
                {point.latitude !== null && point.latitude !== undefined && point.longitude !== null && point.longitude !== undefined && (
                  <span>Coordonnées <strong>{point.latitude.toFixed(6)}, {point.longitude.toFixed(6)}</strong></span>
                )}
                {point.gps_accuracy_m !== null && point.gps_accuracy_m !== undefined && <span>Précision <strong>±{Math.round(point.gps_accuracy_m)} m</strong></span>}
              </div>
            </div>
          </article>

          <article className="panel vehicle-panel">
            <div className="section-heading">
              <div><span className="eyebrow">État carrosserie</span><h2>{replayVisual.label} vue du dessus</h2></div>
              <span className="source-badge candidate">{replayIsFiat500 ? "EOBD + CAN Fiat" : "CAN décodé"}</span>
            </div>
            <div className="vehicle-stage">
              <div className={`headlight-cone left ${point.low_beam || point.high_beam ? "on" : ""} ${point.high_beam ? "high" : ""}`} />
              <div className={`headlight-cone right ${point.low_beam || point.high_beam ? "on" : ""} ${point.high_beam ? "high" : ""}`} />
              <img src={replayVisual.topImage} alt={replayVisual.topAlt} className="vehicle-image" style={{ transform: replayVisual.frontAtTop ? "none" : "rotate(180deg)" }} />
              <span className="vehicle-mirror left" aria-label="Rétroviseur gauche visible"><i /></span>
              <span className="vehicle-mirror right" aria-label="Rétroviseur droit visible"><i /></span>
              <i className={`vehicle-lamp front left indicator ${leftIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp front right indicator ${rightIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp rear left indicator ${leftIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp rear right indicator ${rightIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp rear left brake ${point.brake_active ? "on" : ""}`} />
              <i className={`vehicle-lamp rear right brake ${point.brake_active ? "on" : ""}`} />
            </div>
            <div className="vehicle-state-strip">
              <span className={point.low_beam ? "active" : ""}>Croisement</span>
              <span className={point.high_beam ? "blue-active" : ""}>Route</span>
              <span className={point.turn_signal !== "off" ? "amber-active" : ""}>Cligno {indicatorLabel}</span>
              <span className={point.brake_active ? "red-active" : ""}>Frein</span>
            </div>
            <div className="mirror-status-strip">
              <div><span className="mirror-preview left"><i /></span><p><strong>Rétroviseur gauche</strong><small>Visible · rabattement CAN indisponible</small></p></div>
              <div><span className="mirror-preview right"><i /></span><p><strong>Rétroviseur droit</strong><small>Visible · rabattement CAN indisponible</small></p></div>
            </div>
          </article>
        </section>

        <section className="cockpit-grid">
          <article className="panel instrument-panel">
            <div className="section-heading"><div><span className="eyebrow">Combiné</span><h2>Instruments conducteur</h2></div><span className="source-badge candidate">{replayIsFiat500 ? "EOBD normalisé" : "OpenDBC candidat"}</span></div>
            <div className="instrument-layout">
              <div className="speed-gauge-wrap">
                <div
                  className="speed-gauge"
                  style={{ background: `conic-gradient(from 225deg, #62e39a 0deg ${speedGaugeAngle}deg, #263039 ${speedGaugeAngle}deg 270deg, transparent 270deg)` }}
                >
                  <div><strong>{Math.round(speed)}</strong><span>km/h</span><small>{replayIsFiat500 ? "EOBD 01/0D" : "ABS roues"}</small></div>
                </div>
              </div>
              <div className="engine-readouts">
                <div><span>Régime moteur</span><strong>{Math.round(rpm).toLocaleString("fr-FR")} <small>tr/min</small></strong><i><b style={{ width: `${Math.min(100, rpm / 6000 * 100)}%` }} /></i></div>
                  {replayIsFiat500 ? <>
                    <div><span>Charge moteur</span><strong>{typeof point.engine_load_pct === "number" ? point.engine_load_pct.toFixed(1) : "—"} <small>%</small></strong></div>
                    <div><span>Pression collecteur</span><strong>{typeof point.manifold_pressure_kpa === "number" ? point.manifold_pressure_kpa.toFixed(0) : "—"} <small>kPa</small></strong></div>
                    <div><span>Position papillon</span><strong>{typeof point.throttle_position_pct === "number" ? point.throttle_position_pct.toFixed(1) : typeof point.fiat_throttle_candidate_pct === "number" ? point.fiat_throttle_candidate_pct.toFixed(1) : "—"} <small>%</small></strong></div>
                    <div><span>Air d'admission</span><strong>{typeof point.intake_air_temperature_c === "number" ? point.intake_air_temperature_c.toFixed(0) : "—"} <small>°C</small></strong></div>
                    <div><span>Débit d'air</span><strong>{typeof point.mass_air_flow_g_s === "number" ? point.mass_air_flow_g_s.toFixed(2) : "—"} <small>g/s</small></strong></div>
                    <div><span>Pédale accélérateur</span><strong>{typeof point.accelerator_pct === "number" ? point.accelerator_pct.toFixed(1) : "—"} <small>%</small></strong></div>
                    <div><span>Tension batterie</span><strong>{typeof point.battery_voltage_v === "number" ? point.battery_voltage_v.toFixed(2) : "—"} <small>V</small></strong></div>
                    <div><span>Température moteur</span><strong>{typeof point.coolant_temperature_c === "number" ? point.coolant_temperature_c.toFixed(0) : "—"} <small>°C</small></strong></div>
                  </> : <>
                    <div><span>Couple moteur</span><strong>{typeof point.engine_torque_nm === "number" ? point.engine_torque_nm.toFixed(0) : "—"} <small>Nm</small></strong></div>
                    <div><span>Accélération long.</span><strong>{typeof point.longitudinal_accel_ms2 === "number" ? point.longitudinal_accel_ms2.toFixed(2) : "—"} <small>m/s²</small></strong></div>
                    <div><span>Accélération lat.</span><strong>{typeof point.lateral_accel_ms2 === "number" ? point.lateral_accel_ms2.toFixed(2) : "—"} <small>m/s²</small></strong></div>
                    <div><span>Vitesse de lacet</span><strong>{typeof point.yaw_rate_deg_s === "number" ? point.yaw_rate_deg_s.toFixed(1) : "—"} <small>°/s</small></strong></div>
                  </>}
                <div className={`gear-readout ${point.gear_shift_active ? "shifting" : ""}`}>
                  <span>Rapport engagé</span>
                  <strong>{currentGearLabel}</strong>
                  <div className="gear-scale">
                    {[1, 2, 3, 4, 5, 6].map((gear) => <b key={gear} className={point.current_gear === gear ? "active" : point.target_gear === gear ? "target" : ""}>{gear}</b>)}
                  </div>
                  <small>{typeof point.current_gear === "number" || point.reverse ? `Cible ${targetGearLabel} · ${point.gear_shift_active ? "changement en cours" : "rapport stabilisé"}` : "Rapport non exposé pour cette session"}</small>
                </div>
              </div>
              <div className="driver-inputs">
                <div className="steering-wheel-block">
                  <img src={replayVisual.steeringImage} style={{ transform: `rotate(${steeringAvailable ? Math.max(-540, Math.min(540, -steering)) : 0}deg)` }} alt={replayVisual.steeringAlt} />
                  <strong>{steeringAvailable ? `${Math.abs(steering).toFixed(1)}°` : "—"}</strong><span>{steeringAvailable ? `angle volant · ${steeringDirection}` : "angle volant non décodé"}</span>
                </div>
                <div className="pedal-stack">
                  <div><span>Accélérateur</span><i><b style={{ height: `${acceleratorAvailable ? accelerator : 0}%` }} /></i><strong>{acceleratorAvailable ? `${accelerator.toFixed(0)}%` : "—"}</strong></div>
                  <div className={point.brake_active ? "pressed" : ""}><span>Frein</span><i><b style={{ height: point.brake_active ? "100%" : "0%" }} /></i><strong>{brakeAvailable ? point.brake_active ? "ON" : "OFF" : "—"}</strong></div>
                </div>
              </div>
            </div>
          </article>

          <article className="panel adas-panel">
            {replayIsFiat500 ? <>
              <div className="section-heading"><div><span className="eyebrow">Reconstruction Fiat</span><h2>Qualité du trajet</h2></div><span className="source-badge candidate">Pas de valeur inventée</span></div>
              <div className="route-capability-card">
                <strong>{replay.gps_available ? "Trajectoire GPS disponible" : steeringAvailable || typeof point.yaw_rate_deg_s === "number" ? "Trajectoire CAN estimable" : "Cap non observable sans GPS"}</strong>
                <p>La vitesse et le régime viennent de l’EOBD/du CAN Fiat. Les virages utilisent le GPS du navigateur tant que l’angle volant ou le lacet Fiat ne sont pas décodés.</p>
              </div>
              <div className="adas-state-grid">
                <div><span>Vitesse EOBD</span><strong>{typeof point.speed_kph === "number" ? "Mesurée" : "Absente"}</strong><small>Mode 01 · PID 0D</small></div>
                <div><span>Angle volant</span><strong>{steeringAvailable ? `${steering.toFixed(1)}°` : "À décoder"}</strong><small>Capteur ESP optionnel selon équipement</small></div>
                <div><span>Vitesse de lacet</span><strong>{typeof point.yaw_rate_deg_s === "number" ? `${point.yaw_rate_deg_s.toFixed(1)}°/s` : "À décoder"}</strong><small>Disponible seulement avec le bloc ESP/capteur combiné</small></div>
                <div><span>GPS navigateur</span><strong>{replay.gps_available ? `${replay.gps_point_count} points` : "Absent"}</strong><small>Source privilégiée pour cette première version Fiat</small></div>
              </div>
            </> : <>
              <div className="section-heading"><div><span className="eyebrow">Aides à la conduite</span><h2>Lecture ADAS</h2></div><span className="source-badge candidate">À confirmer</span></div>
              <div className={`lane-visual departure-${laneDeparture}`}>
                <i className="lane-line left" /><i className="lane-line right" />
                <span className="lane-car">▲</span>
                <b>{point.lane_departure ? "Alerte de ligne" : "Voie stable"}</b>
              </div>
              <div className="adas-state-grid">
                <div><span>Maintien dans la voie</span><strong className={point.lane_assist_status === 5 || point.lane_assist_status === 6 ? "warning-text" : ""}>{laneAssistStatusLabel(point.lane_assist_status)}</strong><small>État brut {point.lane_assist_status ?? "—"} · {point.lka_active ? "activation demandée" : "aucune activation LXA"}</small></div>
                <div className="cruise-validation-card">
                  <div className="cruise-validation-heading">
                    <span>Régulateur — candidats 0x208 / 0x50E</span>
                    <strong className={point.cruise_active_candidate ? "success-text" : ""}>
                      {cruiseXvvStateLabel(point.cruise_xvv_state)}
                    </strong>
                  </div>
                  <div className="cruise-candidate-grid">
                    <div className={`cruise-candidate-indicator${point.cruise_active_candidate ? " active" : ""}`}>
                      <span>État XVV</span>
                      <strong>{point.cruise_xvv_state ?? "—"}</strong>
                      <small>0x208 Dyn_CMM · octet 4 · bits 2-3</small>
                    </div>
                    <div className={`cruise-candidate-indicator${point.cruise_active_candidate ? " active" : ""}`}>
                      <span>Consigne</span>
                      <strong>{typeof point.cruise_setpoint_kph === "number" ? `${point.cruise_setpoint_kph.toFixed(0)} km/h` : "—"}</strong>
                      <small>0x50E Dat_CLIM · octet 6</small>
                    </div>
                  </div>
                  <div className="cruise-validation-footer">
                    <span>Détection comportementale <strong>{point.cruise_probable ? `oui · ${Math.round((point.cruise_confidence ?? 0) * 100)} %` : "non"}</strong></span>
                  </div>
                </div>
                <div><span>Frein conducteur</span><strong className={point.brake_active ? "danger-text" : ""}>{point.brake_active ? "Appuyé" : "Relâché"}</strong><small>État système {point.brake_system_state ?? "—"} · pression brute {point.brake_pressure_raw?.toFixed(0) ?? "—"}</small></div>
                <div><span>Effort au volant</span><strong>{point.driver_torque?.toFixed(0) ?? "—"}</strong><small>Valeur colonne non calibrée en N·m</small></div>
              </div>
            </>}
          </article>
        </section>

        <section className="panel replay-indicator-panel">
          <div className="section-heading custom-gauge-heading">
            <div>
              <span className="eyebrow">Combiné personnalisable</span>
              <h2>Mes témoins de bord</h2>
              <p>Les témoins disponibles suivent le CAN; les autres restent gris comme références, sans fausse alerte.</p>
            </div>
            <div className="indicator-actions">
              <div className="gauge-picker">
                <select value={replayIndicatorToAdd} onChange={(event) => setReplayIndicatorToAdd(event.target.value)} aria-label="Témoin à ajouter">
                  <option value="">Ajouter un témoin…</option>
                  {addableIndicatorDefinitions.map((definition) => (
                    <option key={definition.key} value={definition.key}>{definition.label}{definition.referenceOnly ? " · référence" : ""}</option>
                  ))}
                </select>
                <button className="secondary-button" disabled={!replayIndicatorToAdd} onClick={addReplayIndicator}>Ajouter</button>
              </div>
              <button className="ghost-button" onClick={() => setSelectedReplayIndicatorKeys(replayIndicatorCatalog.map((definition) => definition.key))}>Tout afficher</button>
            </div>
          </div>
          {selectedIndicatorDefinitions.length === 0 ? (
            <div className="custom-gauge-empty">Aucun témoin sélectionné. Utilise la galerie ci-dessus.</div>
          ) : (
            <div className="replay-indicator-grid">
              {selectedIndicatorDefinitions.map((definition) => {
                const state = replayIndicatorState(definition, point, replay);
                const blinkSignal = ["turn_left", "turn_right"].includes(definition.key) || (definition.key === "engine" && point.mil_blinking);
                const visualActive = state.active === true && (!blinkSignal || blinkOn);
                const cardState = !state.available ? "unavailable" : state.active === null ? "observed" : visualActive ? "active" : "inactive";
                return (
                  <article className={`replay-indicator-card ${definition.color} ${cardState}`} key={definition.key} title={definition.note}>
                    <button className="indicator-remove" onClick={() => removeReplayIndicator(definition.key)} aria-label={`Retirer ${definition.label}`}>×</button>
                    <div className="warning-lamp"><ReplayWarningIcon kind={definition.icon} /></div>
                    <h3>{definition.label}</h3>
                    <strong>{!state.available ? "Référence" : state.active === null ? "État brut" : state.active ? "Allumé" : "Éteint"}</strong>
                    <small>{state.detail}</small>
                    {state.inferred && <em>seuil estimé</em>}
                  </article>
                );
              })}
            </div>
          )}
          <p className="indicator-reference-note">
            Référentiel visuel basé sur les catégories du <a href={replayIsFiat500 ? FIAT_500_HANDBOOK_URL : PEUGEOT_308_HANDBOOK_URL} target="_blank" rel="noreferrer">manuel officiel {replayIsFiat500 ? "Fiat 500" : "Peugeot 308"}</a>. Un pictogramme gris signifie uniquement que son signal n'est pas présent dans la capture.
          </p>
        </section>

        <section className="panel custom-gauge-panel">
          <div className="section-heading custom-gauge-heading">
            <div>
              <span className="eyebrow">Instrumentation personnalisable</span>
              <h2>Mes jauges de replay</h2>
              <p>Ajoute ou retire les capteurs réellement présents dans cet enregistrement.</p>
            </div>
            <div className="gauge-picker">
              <select value={replayGaugeToAdd} onChange={(event) => setReplayGaugeToAdd(event.target.value)} aria-label="Capteur à ajouter">
                <option value="">Ajouter un capteur…</option>
                {addableGaugeDefinitions.map((definition) => <option key={definition.key} value={definition.key}>{definition.label}{replay.field_quality[String(definition.key)]?.includes("validated") ? "" : " · à confirmer"}</option>)}
                <option value="__fuel_consumption_unavailable" disabled>Consommation — diagnostic OBD requis</option>
              </select>
              <button className="secondary-button" disabled={!replayGaugeToAdd} onClick={addReplayGauge}>Ajouter</button>
              <button className="ghost-button" disabled={!availableGaugeDefinitions.length} onClick={() => setSelectedReplayGaugeKeys(availableGaugeDefinitions.map((definition) => String(definition.key)))}>Tout afficher</button>
            </div>
          </div>
          {selectedGaugeDefinitions.length === 0 ? (
            <div className="custom-gauge-empty">Aucune jauge sélectionnée. Choisis un capteur dans la liste ci-dessus.</div>
          ) : (
            <div className="custom-gauge-grid">
              {selectedGaugeDefinitions.map((definition) => {
                const rawValue = point[definition.key];
                const numericValue = typeof rawValue === "number" ? rawValue : null;
                const statusValue = typeof rawValue === "boolean" ? rawValue : null;
                const ratio = definition.status
                  ? statusValue ? 1 : 0
                  : numericValue === null ? 0 : Math.max(0, Math.min(1, (numericValue - definition.minimum) / (definition.maximum - definition.minimum)));
                const displayValue = definition.status
                  ? statusValue === null ? "—" : statusValue ? "Actif" : "Inactif"
                  : numericValue === null ? "—" : ["current_gear", "target_gear"].includes(String(definition.key)) && numericValue === 9 ? "R" : numericValue.toFixed(definition.precision ?? 0);
                const quality = replay.field_quality[definition.key] ?? "opendbc_candidate";
                const validation = validationByKey.get(String(definition.key));
                return (
                  <article className="custom-gauge-card" key={definition.key}>
                    <button className="gauge-remove" onClick={() => removeReplayGauge(definition.key)} aria-label={`Retirer ${definition.label}`}>×</button>
                    <div
                      className="custom-gauge-ring"
                      style={{ background: `conic-gradient(${definition.color} 0deg ${ratio * 300}deg, #263039 ${ratio * 300}deg 300deg, transparent 300deg)` }}
                    >
                      <div><strong>{displayValue}</strong><small>{definition.unit}</small></div>
                    </div>
                    <h3>{definition.label}</h3>
                    <p>{definition.note}</p>
                    <footer>
                      <span className={`validation-badge ${validation?.status ?? "candidate"}`}>{validation?.status === "validated" ? "Validé" : validation?.status === "plausible" ? "Plausible" : validation?.status === "suspicious" ? "Suspect" : quality.includes("state_only") ? "Contacteur logique" : "À confirmer"}</span>
                      <code>{definition.key}</code>
                    </footer>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel replay-graph-panel">
          <div className="section-heading custom-gauge-heading">
            <div>
              <span className="eyebrow">Analyse temporelle</span>
              <h2>Mes graphes synchronisés</h2>
              <p>Chaque courbe utilise l'échelle observée du capteur et le curseur suit exactement le replay.</p>
            </div>
            <div className="gauge-picker">
              <select value={replayGraphToAdd} onChange={(event) => setReplayGraphToAdd(event.target.value)} aria-label="Graphe à ajouter">
                <option value="">Ajouter un graphe…</option>
                {addableGraphDefinitions.map((definition) => <option key={definition.key} value={definition.key}>{definition.label}{replay.field_quality[String(definition.key)]?.includes("validated") ? "" : " · à confirmer"}</option>)}
              </select>
              <button className="secondary-button" disabled={!replayGraphToAdd} onClick={addReplayGraph}>Ajouter</button>
              <button className="ghost-button" disabled={!availableGraphDefinitions.length} onClick={() => setSelectedReplayGraphKeys(availableGraphDefinitions.map((definition) => String(definition.key)))}>Tout afficher</button>
            </div>
          </div>
          {selectedGraphDefinitions.length === 0 ? (
            <div className="custom-gauge-empty">Aucun graphe sélectionné. Choisis un signal numérique dans la liste.</div>
          ) : (
            <div className="replay-graph-grid">
              {selectedGraphDefinitions.map((definition) => {
                const geometry = currentReplayGraphGeometries.get(String(definition.key));
                const rawValue = point[definition.key];
                const numericValue = typeof rawValue === "number" ? rawValue : null;
                const span = Math.max(0.001, (geometry?.maximum ?? definition.maximum) - (geometry?.minimum ?? definition.minimum));
                const markerY = numericValue === null ? null : 172 - (numericValue - (geometry?.minimum ?? definition.minimum)) / span * 164;
                return (
                  <article className="replay-graph-card" key={definition.key}>
                    <header>
                      <div><span>{definition.label}</span><strong>{numericValue?.toFixed(definition.precision ?? 0) ?? "—"} <small>{definition.unit}</small></strong></div>
                      <button className="gauge-remove" onClick={() => removeReplayGraph(String(definition.key))} aria-label={`Retirer le graphe ${definition.label}`}>×</button>
                    </header>
                    <div className="replay-chart-wrap">
                      <svg
                        viewBox="0 0 900 180"
                        preserveAspectRatio="none"
                        role="img"
                        aria-label={`Courbe ${definition.label}`}
                        onClick={(event) => {
                          const bounds = event.currentTarget.getBoundingClientRect();
                          seekReplay((event.clientX - bounds.left) / bounds.width * replay.duration_ms);
                        }}
                      >
                        <path className="chart-grid-line" d="M0 45H900M0 90H900M0 135H900" />
                        <path className="chart-series-shadow" d={geometry?.path ?? ""} style={{ stroke: definition.color }} />
                        <path className="chart-series" d={geometry?.path ?? ""} style={{ stroke: definition.color }} />
                        <line className="chart-cursor" x1={progress * 900} x2={progress * 900} y1="0" y2="180" />
                        {markerY !== null && <circle className="chart-marker" cx={progress * 900} cy={Math.max(8, Math.min(172, markerY))} r="6" style={{ fill: definition.color }} />}
                      </svg>
                      <span className="chart-maximum">{(geometry?.maximum ?? definition.maximum).toFixed(definition.precision ?? 0)} {definition.unit}</span>
                      <span className="chart-minimum">{(geometry?.minimum ?? definition.minimum).toFixed(definition.precision ?? 0)} {definition.unit}</span>
                    </div>
                    <footer><span>00:00</span><span>{formatReplayTime(replayTimeMs)}</span><span>{formatReplayTime(replay.duration_ms)}</span></footer>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel replay-controls">
          <div className="transport-controls">
            <button onClick={() => seekReplay(replayTimeMs - 10_000)} aria-label="Reculer de dix secondes">−10</button>
            <button className="play-button" onClick={() => setReplayPlaying((playing) => !playing)}>{replayPlaying ? "Ⅱ" : "▶"}</button>
            <button onClick={() => seekReplay(replayTimeMs + 10_000)} aria-label="Avancer de dix secondes">+10</button>
            <strong>{formatReplayTime(replayTimeMs)}</strong><span>/ {formatReplayTime(replay.duration_ms)}</span>
          </div>
          <div className="rate-controls" aria-label="Vitesse de lecture">
            {[0.5, 1, 2, 5, 10].map((rate) => <button key={rate} className={replayRate === rate ? "active" : ""} onClick={() => setReplayRate(rate)}>×{rate}</button>)}
          </div>
          <div className="timeline-wrap">
            <input type="range" min="0" max={replay.duration_ms} step={replay.sample_period_ms} value={Math.round(replayTimeMs)} onChange={(event) => seekReplay(Number(event.target.value))} />
            <div className="event-track">
              {replay.events.map((event, index) => (
                <button
                  key={`${event.t_ms}-${event.kind}-${index}`}
                  className={`event-pin ${event.kind}`}
                  style={{ left: `${event.t_ms / replay.duration_ms * 100}%` }}
                  title={`${formatReplayTime(event.t_ms)} · ${event.label}`}
                  onClick={() => seekReplay(event.t_ms)}
                />
              ))}
            </div>
          </div>
          <div className="event-list">
            {replay.events.map((event, index) => (
              <button key={`${event.t_ms}-${index}`} className={event.kind} onClick={() => seekReplay(event.t_ms)}>
                <time>{formatReplayTime(event.t_ms)}</time><span>{event.label}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="replay-method-note">
          <span className="source-badge measured">Validé véhicule</span><p>Vitesse, roues, volant, lacet, pédales, régime, couple, rapports, freinage, tension et contacteur d’huile.</p>
          <span className="source-badge candidate">Plausible</span><p>Températures, états non provoqués et niveau carburant filtré : cohérents, mais sans mesure étalon indépendante.</p>
          <span className="source-badge suspicious">Indisponible</span><p>La consommation passive est invalide ou nulle sur cette capture; elle nécessite une lecture OBD moteur.</p>
          <span className={`source-badge ${gpsMeasured ? "measured" : "estimated"}`}>{gpsMeasured ? "GPS navigateur" : "Estimé"}</span><p>{gpsMeasured ? "Position, précision, cap et trace synchronisés avec le CAN." : gpsAnchored ? "Position initiale GPS; trajet ensuite estimé." : "Position, cap et distance sans GPS."}</p>
        </section>
      </div>
    );
  }

  function renderStudio() {
    const point = studioLiveSample?.point ?? null;
    const liveAvailableFields = studioLiveSample?.availableFields ?? [];
    const gaugeDefinitions = replayGaugeCatalog.filter((definition) => !definition.rejected);
    const graphDefinitions = gaugeDefinitions.filter((definition) => !definition.status);
    const widgetTitle = (widget: StudioWidget) => {
      if (widget.kind === "gauge" || widget.kind === "graph" || widget.kind === "numeric" || widget.kind === "lamp") {
        return replayGaugeCatalog.find((definition) => definition.key === widget.key)?.label ?? "Capteur";
      }
      if (widget.kind === "indicator") {
        return replayIndicatorCatalog.find((definition) => definition.key === widget.key)?.label ?? "Témoin";
      }
      return { speed: "Vitesse", steering: "Volant", gear: "Rapport engagé", vehicle: "Véhicule", capture: "Enregistrement CAN" }[widget.kind];
    };

    const widgetContent = (widget: StudioWidget) => {
      if (widget.kind === "capture") {
        return (
          <div className={`studio-capture-widget ${capture?.active ? "recording" : ""}`}>
            <div className="studio-record-state"><i /><div><strong>{capture?.active ? "Direct + enregistrement en cours" : "Direct en attente"}</strong><small>{capture?.active ? capture.session_id : "Démarre la capture pour recevoir les trames en direct"}</small></div></div>
            <label>Nom de la session<input value={captureName} disabled={capture?.active} onChange={(event) => setCaptureName(event.target.value)} /></label>
            <button className={capture?.active ? "danger-button" : "primary-button"} disabled={transportConnectBusy} onClick={() => void (capture?.active ? stopCapture() : startCapture())}>{capture?.active ? "Arrêter et sauvegarder" : "Démarrer le direct"}</button>
            <div className="studio-capture-stats"><span>Direct 6/14 <strong>{(capture?.live_frame_count ?? capture?.frame_count ?? 0).toLocaleString("fr-FR")}</strong></span><span>Diag 3/8 <strong>{(capture?.diagnostic_frame_count ?? 0).toLocaleString("fr-FR")}</strong></span><span>Source <strong>{capture?.dual_can ? "Double CAN" : capture?.source ?? "—"}</strong></span></div>
          </div>
        );
      }
      if (!point) return <div className="studio-widget-empty">{!directPsaCompatible ? `Profil ${activeVehicleLabel} actif. Démarre le direct Live Data pour recevoir le CAN Fiat et les PID EOBD autorisés.` : "Démarre le direct pour recevoir les capteurs CAN."}</div>;
      if (widget.kind === "speed") {
        const speed = Math.max(0, point.speed_kph ?? 0);
        const ratio = Math.min(1, speed / 150);
        return (
          <div className="studio-speed-widget">
            <div className="studio-speed-dial" style={{ background: `conic-gradient(from 225deg, #62e39a 0deg ${ratio * 270}deg, #263039 ${ratio * 270}deg 270deg, transparent 270deg)` }}>
              <div><strong>{Math.round(speed)}</strong><span>km/h</span><small>{activeIsFiat500 ? "EOBD 01/0D" : "ABS roues"}</small></div>
            </div>
          </div>
        );
      }
      if (widget.kind === "steering") {
        const available = typeof point.steering_angle_deg === "number";
        const steering = point.steering_angle_deg ?? 0;
        const direction = Math.abs(steering) < 1 ? "centré" : steering < 0 ? "droite" : "gauche";
        return (
          <div className="studio-steering-widget">
            <img src={activeVehicleVisual.steeringImage} style={{ transform: `rotate(${available ? Math.max(-540, Math.min(540, -steering)) : 0}deg)` }} alt={activeVehicleVisual.steeringAlt} />
            <strong>{available ? `${Math.abs(steering).toFixed(1)}°` : "—"}</strong><span>{available ? direction : "à décoder"}</span>
          </div>
        );
      }
      if (widget.kind === "gear") {
        const available = typeof point.current_gear === "number" || Boolean(point.reverse);
        const label = point.reverse || point.current_gear === 9 ? "R" : typeof point.current_gear === "number" ? point.current_gear > 0 ? String(point.current_gear) : "N" : "—";
        const targetLabel = point.reverse || point.target_gear === 9 ? "R" : point.target_gear ?? "—";
        return (
          <div className={`studio-gear-widget ${point.gear_shift_active ? "shifting" : ""}`}>
            <strong>{label}</strong>
            <div>{[1, 2, 3, 4, 5, 6].map((gear) => <b key={gear} className={point.current_gear === gear ? "active" : point.target_gear === gear ? "target" : ""}>{gear}</b>)}</div>
            <span>{available ? `Cible ${targetLabel}` : "Boîte manuelle"}</span><small>{available ? point.gear_shift_active ? "Changement en cours" : "Rapport stabilisé" : "Rapport non exposé"}</small>
          </div>
        );
      }
      if (widget.kind === "vehicle") {
        const blinkOn = Math.floor((passiveSensors?.generated_at_us ?? 0) / 430_000) % 2 === 0;
        const left = blinkOn && ["left", "hazard"].includes(point.turn_signal ?? "off");
        const right = blinkOn && ["right", "hazard"].includes(point.turn_signal ?? "off");
        return (
          <div className="studio-vehicle-widget">
            <div className={`studio-light-beam left ${point.low_beam || point.high_beam ? "on" : ""}`} /><div className={`studio-light-beam right ${point.low_beam || point.high_beam ? "on" : ""}`} />
            <img src={activeVehicleVisual.topImage} alt={activeVehicleVisual.topAlt} />
            <i className={`studio-car-lamp front left ${left ? "on" : ""}`} /><i className={`studio-car-lamp front right ${right ? "on" : ""}`} />
            <i className={`studio-car-lamp rear left ${left ? "on" : ""}`} /><i className={`studio-car-lamp rear right ${right ? "on" : ""}`} />
            <span>{typeof point.low_beam === "boolean" ? point.low_beam ? "Feux ON" : "Feux OFF" : "Feux à décoder"} · {point.turn_signal ?? "clignotants à décoder"}</span>
          </div>
        );
      }
      if (widget.kind === "gauge") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key);
        if (!definition) return <div className="studio-widget-empty">Capteur inconnu.</div>;
        if (definition.rejected) return <div className="studio-widget-empty">Décodage rejeté pour ce véhicule. Consulte le rapport de validation.</div>;
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const logical = typeof raw === "boolean" ? raw : null;
        const ratio = definition.status ? logical ? 1 : 0 : numeric === null ? 0 : Math.max(0, Math.min(1, (numeric - definition.minimum) / (definition.maximum - definition.minimum)));
        const value = definition.status ? logical === null ? "—" : logical ? "Actif" : "Inactif" : numeric === 9 && ["current_gear", "target_gear"].includes(String(definition.key)) ? "R" : numeric?.toFixed(definition.precision ?? 0) ?? "—";
        return (
          <div className="studio-gauge-widget">
            <div style={{ background: `conic-gradient(${definition.color} 0deg ${ratio * 300}deg, #263039 ${ratio * 300}deg 300deg, transparent 300deg)` }}><div><strong>{value}</strong><span>{definition.unit}</span></div></div>
            <small>{definition.note}</small>
          </div>
        );
      }
      if (widget.kind === "numeric") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key);
        if (!definition) return <div className="studio-widget-empty">Capteur inconnu.</div>;
        if (definition.rejected) return <div className="studio-widget-empty">Décodage rejeté pour ce véhicule. Consulte le rapport de validation.</div>;
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const logical = typeof raw === "boolean" ? raw : null;
        const value = definition.status
          ? logical === null ? "—" : logical ? "ACTIF" : "INACTIF"
          : numeric === 9 && ["current_gear", "target_gear"].includes(String(definition.key)) ? "R" : numeric?.toFixed(definition.precision ?? 0) ?? "—";
        return (
          <div className="studio-numeric-widget" style={{ "--sensor-color": definition.color } as React.CSSProperties}>
            <i /><div><strong>{value}</strong><span>{definition.unit}</span></div><small>{definition.note}</small>
          </div>
        );
      }
      if (widget.kind === "lamp") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key && candidate.status);
        if (!definition) return <div className="studio-widget-empty">Ce capteur ne possède pas de mode voyant.</div>;
        const raw = point[definition.key];
        const active = typeof raw === "boolean" ? raw : typeof raw === "number" ? raw !== 0 : false;
        const available = liveAvailableFields.includes(String(definition.key));
        const icon = definition.key === "oil_pressure_switch" ? "oil" : "bulb";
        return (
          <div className={`studio-indicator-widget red ${active ? "active" : ""} ${!available ? "unavailable" : ""}`}>
            <div><ReplayWarningIcon kind={icon} /></div><strong>{available ? active ? "Allumé" : "Éteint" : "Signal absent"}</strong><small>{definition.note}</small>
          </div>
        );
      }
      if (widget.kind === "graph") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key);
        const geometry = studioGraphGeometries.get(widget.id);
        if (!definition || !geometry) return <div className="studio-widget-empty">Courbe indisponible.</div>;
        if (definition.rejected) return <div className="studio-widget-empty">Décodage rejeté sur cette Peugeot. Consulte le rapport de validation.</div>;
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const span = Math.max(.001, geometry.maximum - geometry.minimum);
        const markerY = numeric === null ? null : 172 - (numeric - geometry.minimum) / span * 164;
        return (
          <div className="studio-graph-widget">
            <div className="studio-graph-heading">
              <div><strong>{numeric?.toFixed(definition.precision ?? 0) ?? "—"}</strong><span>{definition.unit}</span></div>
              <label><span>Fenêtre</span><select value={widget.windowSeconds ?? 60} onChange={(event) => setStudioGraphWindow(widget.id, Number(event.target.value) as StudioGraphWindowSeconds)}>
                <option value="10">10 s</option><option value="30">30 s</option><option value="60">1 min</option><option value="300">5 min</option>
              </select></label>
            </div>
            <svg viewBox="0 0 900 180" preserveAspectRatio="none">
              <path className="chart-grid-line" d="M0 45H900M0 90H900M0 135H900" /><path className="chart-series-shadow" d={geometry.path} style={{ stroke: definition.color }} /><path className="chart-series" d={geometry.path} style={{ stroke: definition.color }} />
              {markerY !== null && <circle className="chart-marker" cx="900" cy={Math.max(8, Math.min(172, markerY))} r="6" style={{ fill: definition.color }} />}
            </svg>
          </div>
        );
      }
      if (widget.kind === "indicator") {
        const definition = replayIndicatorCatalog.find((candidate) => candidate.key === widget.key);
        if (!definition) return <div className="studio-widget-empty">Témoin inconnu.</div>;
        const state = replayIndicatorState(definition, point, { available_fields: liveAvailableFields });
        return (
          <div className={`studio-indicator-widget ${definition.color} ${state.active ? "active" : ""} ${!state.available ? "unavailable" : ""}`}>
            <div><ReplayWarningIcon kind={definition.icon} /></div><strong>{state.available ? state.active === null ? "État brut" : state.active ? "Allumé" : "Éteint" : "Signal absent"}</strong><small>{state.detail}</small>
          </div>
        );
      }
      return null;
    };

    return (
      <div className="studio-screen">
        <header className="studio-toolbar">
          <button className="studio-exit" onClick={() => setView("dashboard")}>← Menu</button>
          <div className="studio-brand"><span>OD</span><div><strong>Dashboard direct</strong><small>Disposition sauvegardée automatiquement</small></div></div>
          <button className={`studio-active-vehicle ${activeCommunicationProfile ? "loaded" : ""}`} disabled={capture?.active} onClick={() => setView(selectedDiagnosticVehicle ? "garage" : "identity")}><span>{selectedDiagnosticVehicle ? "VÉHICULE CHARGÉ" : "PROFIL COMMUNICATION"}</span><strong>{activeVehicleLabel}</strong><small>{selectedDiagnosticVehicle?.vin ?? activeCommunicationProfileKey ?? "Choisir une marque"}</small></button>
          <div className={`studio-live-source ${capture?.active ? "active" : ""}`}>
            <i /><div><strong>{capture?.active ? (capture.hybrid_obd_ready ? "CAN + OBD DIRECT" : capture.dual_can ? "DOUBLE CAN DIRECT" : "CAN DIRECT") : "DIRECT EN ATTENTE"}</strong><small>{capture?.active ? `${(capture.live_frame_count ?? capture.frame_count ?? 0).toLocaleString("fr-FR")} live · ${(capture.diagnostic_frame_count ?? 0).toLocaleString("fr-FR")} diag${typeof point?.engine_rpm === "number" ? ` · ${Math.round(point.engine_rpm)} tr/min` : ""}${typeof point?.battery_voltage_v === "number" ? ` · ${point.battery_voltage_v.toFixed(2)} V` : ""}` : "Clique sur Enregistrer pour démarrer"}</small></div>
          </div>
          <div className={`studio-esp-selector ${status?.gateway_verified || capture?.active ? "connected" : ""}`} title={capture?.active ? "Arrête la capture avant de changer d’ESP32" : undefined}>
            <i />
            <select aria-label="ESP32 à connecter" value={selectedTransportId} disabled={transportConnectBusy || capture?.active} onChange={(event) => { setSelectedTransportId(event.target.value); setTransportMessage(""); }}>
              <option value="">Choisir un ESP32…</option>
              <optgroup label="USB / Série">{(transportCatalog?.options ?? []).filter((option) => option.transport === "esp32_serial").map((option) => <option value={option.id} key={option.id}>{option.detected === false ? "○ " : "● "}{option.label}</option>)}</optgroup>
              <optgroup label="Wi-Fi">{(transportCatalog?.options ?? []).filter((option) => option.transport === "esp32_wifi").map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</optgroup>
            </select>
            <button disabled={!selectedTransportId || transportConnectBusy || capture?.active} onClick={() => void connectSelectedTransport()}>{transportConnectBusy ? "Connexion…" : "Connecter"}</button>
            {(transportMessage || status?.gateway_verified) && <small>{transportMessage || "ESP32 validé"}</small>}
          </div>
          <div className="studio-add-control">
            <select value={studioWidgetToAdd} onChange={(event) => setStudioWidgetToAdd(event.target.value)} aria-label="Widget à ajouter">
              <optgroup label="Instruments"><option value="speed">Vitesse</option><option value="steering">Volant</option><option value="gear">Rapport engagé</option><option value="vehicle">Véhicule</option><option value="capture">Enregistrement CAN</option></optgroup>
              <optgroup label="Jauges">{gaugeDefinitions.map((definition) => <option key={`g-${definition.key}`} value={`gauge:${definition.key}`}>{definition.label}</option>)}<option disabled>Consommation — diagnostic OBD requis</option></optgroup>
              <optgroup label="Graphes">{graphDefinitions.map((definition) => <option key={`c-${definition.key}`} value={`graph:${definition.key}`}>{definition.label}</option>)}</optgroup>
              <optgroup label="Valeurs numériques">{gaugeDefinitions.map((definition) => <option key={`n-${definition.key}`} value={`numeric:${definition.key}`}>{definition.label}</option>)}</optgroup>
              <optgroup label="Voyants capteur">{gaugeDefinitions.filter((definition) => definition.status).map((definition) => <option key={`l-${definition.key}`} value={`lamp:${definition.key}`}>{definition.label}</option>)}</optgroup>
              <optgroup label="Témoins">{replayIndicatorCatalog.map((definition) => <option key={`i-${definition.key}`} value={`indicator:${definition.key}`}>{definition.label}</option>)}</optgroup>
            </select>
            <button onClick={addStudioWidget}>+ Ajouter</button>
          </div>
          <button className={`studio-diagnostic ${diagnosticReady ? "ready" : ""}`} onClick={() => { setError(""); setView("ecus"); }}>ECU / Défauts</button>
          <button className={`studio-diagnostic studio-injection ${diagnosticReady ? "ready" : ""}`} onClick={() => { setError(""); setView("injection"); }}>Injection</button>
          <button className="studio-diagnostic studio-inventory" onClick={() => { setError(""); setView("inventory"); }}>Inventaire</button>
          <button className={capture?.active ? "studio-record active" : "studio-record"} disabled={transportConnectBusy} onClick={() => void (capture?.active ? stopCapture() : startCapture())}><i />{capture?.active ? `${capture.frame_count.toLocaleString("fr-FR")} · Sauvegarder` : "Enregistrer"}</button>
          <button className={studioEditing ? "studio-tool active" : "studio-tool"} onClick={() => setStudioEditing((editing) => !editing)}>{studioEditing ? "Verrouiller" : "Modifier"}</button>
          <button className="studio-tool" onClick={() => { if (window.confirm("Réinitialiser toute la disposition du dashboard ?")) setStudioWidgets(defaultStudioWidgets); }}>Réinitialiser</button>
          <button className="studio-tool" onClick={() => void toggleStudioFullscreen()}>Plein écran</button>
        </header>
        {error && <div className="studio-error"><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
        <div className="studio-live-area">
        <ExperimentalSignalsPanel point={point} />
        <div className={`studio-board ${studioEditing ? "editing" : "locked"}`} ref={studioBoardRef}>
          {studioWidgets.map((widget) => (
            <article
              className={`studio-widget studio-widget-${widget.kind}`}
              key={widget.id}
              style={{ left: `calc(${widget.x / STUDIO_COLUMNS * 100}% + 4px)`, top: widget.y * STUDIO_ROW_HEIGHT + 4, width: `calc(${widget.w / STUDIO_COLUMNS * 100}% - 8px)`, height: widget.h * STUDIO_ROW_HEIGHT - 8 }}
            >
              <header className="studio-widget-drag" onPointerDown={(event) => beginStudioInteraction(event, widget, "move")}>
                <strong>{widgetTitle(widget)}</strong>
                <div className="studio-widget-header-tools">
                  {["gauge", "graph", "numeric", "lamp"].includes(widget.kind) && <select
                    className="studio-widget-style-select"
                    aria-label={`Style d'affichage de ${widgetTitle(widget)}`}
                    value={widget.kind}
                    onPointerDown={(event) => event.stopPropagation()}
                    onChange={(event) => setStudioSensorStyle(widget.id, event.target.value as StudioSensorStyle)}
                  ><option value="gauge">Jauge</option>
                    {!replayGaugeCatalog.find((definition) => definition.key === widget.key)?.status && <option value="graph">Graphe</option>}
                    <option value="numeric">Numérique</option>
                    {replayGaugeCatalog.find((definition) => definition.key === widget.key)?.status && <option value="lamp">Voyant</option>}
                  </select>}
                  {studioEditing && <div className="studio-widget-actions">
                    <button title="Diminuer" aria-label={`Diminuer ${widgetTitle(widget)}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => resizeStudioWidget(widget.id, -1)}>−</button>
                    <button title="Agrandir" aria-label={`Agrandir ${widgetTitle(widget)}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => resizeStudioWidget(widget.id, 1)}>+</button>
                    <button title="Supprimer" aria-label={`Supprimer ${widgetTitle(widget)}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => removeStudioWidget(widget.id)}>×</button>
                  </div>}
                </div>
              </header>
              <div className="studio-widget-content">{widgetContent(widget)}</div>
              {studioEditing && <button className="studio-resize-handle" aria-label={`Redimensionner ${widgetTitle(widget)}`} onPointerDown={(event) => beginStudioInteraction(event, widget, "resize")}>⌟</button>}
            </article>
          ))}
          {studioWidgets.length === 0 && <div className="studio-empty-board"><strong>Dashboard vide</strong><span>Ajoute un instrument depuis la barre supérieure.</span></div>}
        </div>
        </div>
      </div>
    );
  }

  function renderGarage() {
    const totalCaptureMs = vehicleLinkedSessions.reduce((total, session) => total + session.duration_ms, 0);
    const lastActivity = vehicleTimeline[0];
    const currentHealth = report
      ? report.dtc_summary.active > 0
        ? { label: `${report.dtc_summary.active} défaut(s) actif(s)`, tone: "warning" }
        : { label: "Aucun défaut actif", tone: "good" }
      : { label: "Diagnostic à réaliser", tone: "neutral" };
    const filterOptions: Array<{ key: typeof garageEventFilter; label: string }> = [
      { key: "all", label: "Tout" },
      { key: "diagnostic", label: "Diagnostics" },
      { key: "capture", label: "Trajets & captures" },
      { key: "identity", label: "Identité" },
    ];
    const openTimelineEntry = async (entry: VehicleTimelineEntry) => {
      if (entry.scanId) {
        await selectDiagnosticReport(entry.scanId);
        setView("dtcs");
      } else if (entry.sessionId) {
        await loadReplay(entry.sessionId);
        setView("replay");
      } else {
        if (selectedDiagnosticVehicle) setIdentityProfileKey(selectedDiagnosticVehicle.vehicle_profile);
        setView("identity");
      }
    };

    return (
      <div className="garage-page">
        {selectedDiagnosticVehicle ? (
          <section className="panel garage-vehicle-hero">
            <div className="garage-vehicle-identity">
              <div className="garage-marque">{selectedDiagnosticVehicle.manufacturer.slice(0, 2).toUpperCase()}</div>
              <div>
                <span className="eyebrow">Véhicule actuellement chargé</span>
                <h2>{selectedDiagnosticVehicle.manufacturer} {selectedDiagnosticVehicle.model}</h2>
                <code>{selectedDiagnosticVehicle.vin}</code>
              </div>
              <span className="status-pill good"><i /> Dossier actif</span>
            </div>
            <div className="garage-health-grid">
              <article><span>État connu</span><strong className={currentHealth.tone}>{currentHealth.label}</strong><small>{report?.scanned_at ? `Scan du ${formatIsoDate(report.scanned_at)}` : "Aucun rapport chargé"}</small></article>
              <article><span>Suivi diagnostic</span><strong>{selectedDiagnosticVehicle.scan_count} rapport(s)</strong><small>Comparaison automatique avant / après</small></article>
              <article><span>Données routières</span><strong>{vehicleLinkedSessions.length} session(s)</strong><small>{formatDuration(totalCaptureMs)} enregistrées</small></article>
              <article><span>Dernière activité</span><strong>{lastActivity ? formatDate(lastActivity.timestampMs * 1000) : "—"}</strong><small>{lastActivity?.title ?? "Dossier récemment créé"}</small></article>
            </div>
            <div className="garage-quick-actions">
              <button className="primary-button" onClick={() => setView("studio")}>Ouvrir le direct</button>
              <button className="secondary-button" onClick={() => setView("ecus")}>Lancer un diagnostic</button>
              <button className="ghost-button" onClick={() => { setIdentityProfileKey(selectedDiagnosticVehicle.vehicle_profile); setView("identity"); }}>Relire l’identité</button>
            </div>
          </section>
        ) : (
          <section className="panel"><EmptyState title="Aucun véhicule chargé" text="Lis le VIN pour créer un dossier véhicule fiable avant une capture ou un diagnostic." action={<button className="primary-button" onClick={() => setView("identity")}>Identifier le véhicule</button>} /></section>
        )}

        <section className="garage-workspace">
          <aside className="panel garage-fleet-panel">
            <div className="section-heading">
              <div><span className="eyebrow">Garage local</span><h2>{diagnosticVehicles.length} véhicule(s)</h2><p>Un seul dossier est chargé à la fois.</p></div>
            </div>
            <div className="garage-fleet-list">
              {diagnosticVehicles.map((vehicle) => {
                const linked = sessions.filter((session) => session.vin === vehicle.vin).length;
                const active = vehicle.vin === selectedDiagnosticVin;
                return <button className={active ? "active" : ""} disabled={vehicleSelectionBusy || capture?.active} onClick={() => void selectDiagnosticVehicle(vehicle.vin)} key={vehicle.vin}>
                  <span>{vehicle.manufacturer.slice(0, 2).toUpperCase()}</span>
                  <div><strong>{vehicle.manufacturer} {vehicle.model}</strong><code>{vehicle.vin}</code><small>{vehicle.scan_count} diagnostic(s) · {linked} capture(s)</small></div>
                  <b>{active ? "CHARGÉ" : "Charger"}</b>
                </button>;
              })}
            </div>
            <button className="garage-add-vehicle" onClick={() => setView("identity")}>＋ Ajouter par lecture VIN</button>
            {capture?.active && <p className="garage-lock-note">Le changement de véhicule est bloqué pendant l’enregistrement en cours.</p>}
          </aside>

          <section className="panel garage-timeline-panel">
            <div className="section-heading garage-timeline-heading">
              <div><span className="eyebrow">Historique consolidé</span><h2>Chronologie du véhicule</h2><p>Diagnostics, captures et identité restent séparés des autres VIN.</p></div>
              <div className="garage-filter-tabs">{filterOptions.map((option) => <button className={garageEventFilter === option.key ? "active" : ""} onClick={() => setGarageEventFilter(option.key)} key={option.key}>{option.label}</button>)}</div>
            </div>
            <div className="vehicle-timeline">
              {vehicleTimeline.map((entry) => <button className={`timeline-entry ${entry.kind} ${entry.severity ?? "neutral"}`} onClick={() => void openTimelineEntry(entry)} key={entry.id}>
                <time>{formatDate(entry.timestampMs * 1000)}</time>
                <i><span>{entry.kind === "diagnostic" ? "DTC" : entry.kind === "capture" ? "CAN" : "VIN"}</span></i>
                <div><strong>{entry.title}</strong><p>{entry.description}</p></div>
                <span>{entry.badge}</span>
                <b>→</b>
              </button>)}
              {!vehicleTimeline.length && <EmptyState title="Aucun événement dans cette vue" text="Change le filtre ou réalise une première opération sur le véhicule chargé." />}
            </div>
          </section>
        </section>

        {unassignedSessions.length > 0 && selectedDiagnosticVehicle && <section className="panel unassigned-sessions-panel">
          <div className="section-heading">
            <div><span className="eyebrow">À classer</span><h2>{unassignedSessions.length} ancienne(s) capture(s) sans VIN</h2><p>Les données ne sont jamais attribuées silencieusement. Confirme celles qui appartiennent à {activeVehicleLabel}.</p></div>
            <button className="secondary-button" disabled={Boolean(sessionAssignmentBusy)} onClick={() => {
              if (window.confirm(`Associer les ${unassignedSessions.length} captures sans VIN à ${activeVehicleLabel} ?`)) void assignSessionsToActiveVehicle(unassignedSessions.map((session) => session.session_id));
            }}>{sessionAssignmentBusy === "bulk" ? "Classement…" : "Tout associer au véhicule actif"}</button>
          </div>
          <div className="unassigned-session-list">
            {unassignedSessions.slice(0, 8).map((session) => <article key={session.session_id}>
              <div><strong>{session.name}</strong><small>{formatDate(session.started_at_us)} · {session.frame_count.toLocaleString("fr-FR")} trames</small></div>
              <button className="ghost-button" disabled={Boolean(sessionAssignmentBusy)} onClick={() => void assignSessionsToActiveVehicle([session.session_id])}>{sessionAssignmentBusy === session.session_id ? "Association…" : "Associer"}</button>
            </article>)}
            {unassignedSessions.length > 8 && <small>+ {unassignedSessions.length - 8} autres captures disponibles pour le classement global.</small>}
          </div>
        </section>}
      </div>
    );
  }

  function renderDashboard() {
    const applicableSensors = Math.max(1, sensorInventoryRows.length - inventoryCounts.excluded);
    const sensorCoverage = Math.round((inventoryCounts.measured + inventoryCounts.supported) / applicableSensors * 100);
    return (
      <>
        <section className="metric-grid">
          <article className="metric-card accent-card">
            <span className="metric-label">Connexion</span>
            <strong>{status ? "Backend en ligne" : "Indisponible"}</strong>
            <small>{status
              ? `${status.transport}${status.gateway_endpoint ? ` · ${status.gateway_endpoint}` : ""}`
              : (statusError || "En attente du backend")}</small>
          </article>
          <article className="metric-card">
            <span className="metric-label">Profil véhicule</span>
            <strong>{activeVehicleLabel}</strong>
            <small>{selectedDiagnosticVehicle?.vin ?? "Lis le VIN pour créer le dossier"}</small>
          </article>
          <article className="metric-card">
            <span className="metric-label">Calculateurs</span>
            <strong>{report ? `${detectedEcus.length} / ${report.ecus.length}` : "—"}</strong>
            <small>{report ? "détectés au dernier scan" : "aucun scan effectué"}</small>
          </article>
          <article className="metric-card">
            <span className="metric-label">Défauts actifs</span>
            <strong>{report ? dtcCount : "—"}</strong>
            <small>{report ? `${report.dtc_summary.historical} historique(s) · ${observedDtcs.length} relevé(s) à confirmer` : "aucun scan enregistré"}</small>
          </article>
        </section>

        <section className="dashboard-grid">
          <article className="panel journey-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Parcours atelier</span>
                <h2>Que souhaites-tu faire ?</h2>
                <p>Chaque parcours ne montre que les outils nécessaires à l’étape en cours.</p>
              </div>
            </div>
            <div className="journey-grid">
              <button className="journey-card observe" onClick={() => setView("studio")}>
                <span className="journey-step">01</span>
                <div><small>Sans émission</small><h3>Observer en direct</h3><p>Compose ton cockpit, affiche les capteurs et enregistre un trajet.</p></div>
                <footer><span className={capture?.active ? "live" : ""}>{capture?.active ? "Enregistrement actif" : "Prêt à observer"}</span><b>→</b></footer>
              </button>
              <button className="journey-card validate" onClick={() => setView("inventory")}>
                <span className="journey-step">02</span>
                <div><small>Preuves guidées</small><h3>Valider les capteurs</h3><p>Traite une information à la fois avec la bonne méthode de test.</p></div>
                <footer><span>{sensorCoverage}% couverts · {validationQueue.length} à traiter</span><b>→</b></footer>
              </button>
              <button className="journey-card diagnose" onClick={() => setView("ecus")}>
                <span className="journey-step">03</span>
                <div><small>Lecture seule</small><h3>Diagnostiquer le véhicule</h3><p>Identifie les ECU, lis les défauts et exporte un rapport par VIN.</p></div>
                <footer><span className={diagnosticReady ? "ready" : ""}>{diagnosticReady ? "Liaison diagnostic prête" : "Connexion à vérifier"}</span><b>→</b></footer>
              </button>
            </div>
            <div className="dashboard-personalize">
              <div><strong>Un affichage adapté à ton usage</strong><span>Le dashboard direct reste entièrement déplaçable, redimensionnable et mémorisé.</span></div>
              <button className="secondary-button" onClick={() => setView("studio")}>Personnaliser le direct</button>
            </div>
          </article>

          <article className="panel safety-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Garde-fous</span>
                <h2>État de sécurité</h2>
              </div>
              <span className={`status-pill ${status?.read_only ? "good" : status ? "bad" : "neutral"}`}>
                {status ? (status.read_only ? "Lecture seule" : "Maintenance contrôlée") : "État inconnu"}
              </span>
            </div>
            <div className="safety-list">
              <div><span>Émission CAN</span><strong>{status?.can_tx_enabled ? "Autorisée" : "Bloquée"}</strong></div>
              <div><span>Effacement DTC</span><strong>{status?.dtc_clear_enabled ? "Armé" : "Verrouillé"}</strong></div>
              <div><span>ECU de sécurité</span><strong>{status?.safety_ecu_clear_enabled ? "Déverrouillés" : "Protégés"}</strong></div>
              <div><span>Traces CAN</span><strong>{status?.trace_can_frames ? "Actives" : "Inactives"}</strong></div>
              <div><span>Liaison ESP32</span><strong>{status?.transport === "esp32_wifi" ? "Wi-Fi privé" : status?.transport ?? "Inconnue"}</strong></div>
            </div>
            <div className="safety-action">
              <div><strong>Commandes actives</strong><span>{status?.psa_actuator_enabled && !status?.read_only ? "Configurées · armement requis" : "Verrouillées par défaut"}</span></div>
              <button className="ghost-button" onClick={() => setView("security")}>Voir le moteur de sécurité</button>
            </div>
            {!status && (
              <p className="inline-alert danger-alert">
                Le backend n'est pas joignable. Aucune conclusion de sécurité ne doit être déduite.
              </p>
            )}
          </article>
        </section>

        {report?.debug.session_id && (
          <section className="panel trace-strip">
            <div>
              <span className="eyebrow">Dernière trace</span>
              <strong>{report.debug.session_id}</strong>
            </div>
            <div><span>Durée</span><b>{formatDuration(report.debug.duration_ms)}</b></div>
            <div><span>Événements</span><b>{report.debug.event_count}</b></div>
            <div><span>Ignorés</span><b>{report.debug.dropped_events}</b></div>
          </section>
        )}
      </>
    );
  }

  function renderSensors() {
    return (
      <div className="sensor-page">
        <section className="panel sensor-detection-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Inventaire automatique · réception uniquement</span>
              <h2>Détection complète des capteurs</h2>
              <p>Écoute 30 secondes, recense tous les identifiants CAN visibles et décode ceux connus par OpenDBC.</p>
            </div>
            <button className="primary-button" onClick={() => startFullSensorDetection()} disabled={detectionBusy || detectionRemaining > 0}>
              {detectionBusy ? "Démarrage…" : detectionRemaining > 0 ? `Détection · ${detectionRemaining} s` : "Lancer la détection complète"}
            </button>
          </div>
          <div className="sensor-detection-metrics">
            <div><span>Identifiants CAN</span><strong>{passiveSensors?.observed_can_id_count ?? 0}</strong></div>
            <div><span>Messages reconnus</span><strong>{passiveSensors?.observed_message_count ?? 0}</strong></div>
            <div><span>Signaux décodés</span><strong>{passiveSensors?.decoded_signal_count ?? 0}</strong></div>
            <div><span>ID à cartographier</span><strong>{passiveSensors?.unknown_can_id_count ?? 0}</strong></div>
          </div>
          {detectionRemaining > 0 && (
            <div className="detection-progress">
              <i style={{ width: `${((30 - detectionRemaining) / 30) * 100}%` }} />
            </div>
          )}
          <div className="detection-state-row">
            <span className={`status-pill ${passiveSensors?.strict_passive || liveObdReadOnly ? "good" : "bad"}`}>
              <i /> {passiveSensors?.strict_passive
                ? "Passif strict · émission impossible"
                : liveObdReadOnly
                  ? "Capture passive · OBD 01/09 filtré"
                  : "Sécurité à vérifier"}
            </span>
            <span>Mises à jour différentielles toutes les 200 ms</span>
            {passiveSensors?.unknown_can_ids.length ? (
              <code title={passiveSensors.unknown_can_ids.map(hexadecimal).join(", ")}>
                Inconnus : {passiveSensors.unknown_can_ids.slice(0, 10).map(hexadecimal).join(", ")}
                {passiveSensors.unknown_can_ids.length > 10 ? "…" : ""}
              </code>
            ) : null}
          </div>
          <p className="inline-alert">
            Cette détection trouve tous les signaux diffusés sur le réseau CAN actuellement branché. Un capteur silencieux, sur un autre réseau ou accessible uniquement par requête UDS ne peut pas apparaître en mode passif.
          </p>
          <p className="inline-alert">
            <strong>Consommation :</strong> aucun débit fiable n'est diffusé passivement sur la capture actuelle. Utilise « Injection » pour tenter la lecture OBD moteur du débit carburant (PID 01-5E).
          </p>
        </section>

        <section className="panel steering-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Direction · validation véhicule</span>
              <h2>Capteur du volant</h2>
            </div>
            <span className={`status-pill ${passiveSensors?.steering.detected ? "good" : "neutral"}`}>
              <i /> {passiveSensors?.steering.detected ? "Détecté" : "En attente"}
            </span>
          </div>
          {passiveSensors?.steering.detected ? (
            <>
              <div className="steering-readout">
                <div className="steering-angle">
                  <span>Angle volant</span>
                  <strong>{passiveSensors.steering.angle_degrees?.toFixed(1) ?? "—"}<small>°</small></strong>
                  <em style={{ transform: `rotate(${Math.max(-135, Math.min(135, -(passiveSensors.steering.angle_degrees ?? 0) / 4))}deg)` }}>↑</em>
                </div>
                <div><span>Vitesse rotation</span><strong>{passiveSensors.steering.rate_degrees_s?.toFixed(0) ?? "—"}</strong><small>°/s</small></div>
                <div><span>Couple conducteur</span><strong>{passiveSensors.steering.driver_torque?.toFixed(0) ?? "—"}</strong><small>valeur CAN</small></div>
              </div>
              {LAB_MODE && <div className="steering-sources">
                <code>{passiveSensors.steering.angle_source ?? "Angle indisponible"}</code>
                <code>{passiveSensors.steering.torque_source ?? "Couple indisponible"}</code>
              </div>}
              {passiveSensors.steering.warning && <p className="inline-alert">{passiveSensors.steering.warning}</p>}
            </>
          ) : (
            <EmptyState title="Volant non observé" text="Démarre une capture passive puis tourne doucement le volant à l'arrêt." />
          )}
        </section>

        <section className="panel passive-sensors-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Direct hybride · CAN passif + OBD normalisé</span>
              <h2>Tous les signaux décodés</h2>
              <p>{passiveSensors
                ? `${passiveSensors.decoded_signal_count} signaux live · ${passiveSensors.observed_message_count} messages OpenDBC · ${passiveSensors.frame_count.toLocaleString("fr-FR")} trames`
                : "En attente de la capture"}</p>
            </div>
            <div className="section-actions">
              <button className="ghost-button" onClick={createLiveSensor} disabled={!selectedDiagnosticVin || !passiveSensors?.signals.some((signal) => !signal.user_defined)}>Ajouter un capteur</button>
              <button className="secondary-button" onClick={() => refreshPassiveSensors()}>Actualiser</button>
            </div>
          </div>

          <div className="sensor-toolbar">
            <div className="sensor-category-tabs">
              {sensorCategories.map((category) => (
                <button
                  className={sensorCategory === category ? "active" : ""}
                  key={category}
                  onClick={() => setSensorCategory(category)}
                >{category}</button>
              ))}
            </div>
            <input
              aria-label="Rechercher un capteur"
              value={sensorSearch}
              onChange={(event) => setSensorSearch(event.target.value)}
              placeholder="Rechercher angle, vitesse, frein…"
            />
          </div>

          {!passiveSensors || passiveSensors.signals.length === 0 ? (
            <EmptyState
              title="Aucun signal passif"
              text="Le décodage se remplit automatiquement pendant une capture OpenDiag Learn."
              action={<button className="primary-button" onClick={() => setView("discovery")}>Ouvrir la découverte</button>}
            />
          ) : (
            <>
              <div className="sensor-live-table">
                {visiblePassiveSignals.map((signal) => (
                  <article className={`sensor-live-row ${signal.confidence} ${signal.customized ? "customized" : ""}`} key={signal.key}>
                    <div className="sensor-live-name">
                      <span>{signal.category}{signal.essential ? " · essentiel" : ""}{signal.user_defined ? " · local au véhicule" : ""}</span>
                      <strong>{signal.display_name}</strong>
                      <p>{signal.description}</p>
                    </div>
                    <div className="sensor-live-value">
                      <strong>{String(signal.value ?? "—")}</strong>
                      <span>{signal.unit || "sans unité"}</span>
                  {LAB_MODE && signal.customized && <small>Source : {String(signal.raw_value ?? "—")} {signal.source_unit ?? ""}</small>}
                    </div>
                    <div className="sensor-live-source">
                      <code>{signal.user_defined ? "Capteur local dérivé" : signal.source === "obd" ? "Lecture OBD-II normalisée" : "CAN constructeur décodé"}</code>
                      <span>{signal.user_defined ? "Définition utilisateur observée" : signal.confidence === "standardized" ? "OBD-II normalisé" : signal.confidence === "validated" ? "Validé sur le véhicule" : signal.confidence === "vehicle_observed_candidate" ? "Trame Fiat observée · décodage à confirmer" : "Définition OpenDBC à confirmer"}</span>
                    </div>
                    {signal.user_defined ? <button className="ghost-button" onClick={() => editLiveSensor(signal)}>Modifier</button> : signal.source === "can" ? <button className="ghost-button" onClick={() => editPassiveSensor(signal)}>
                      {signal.customized ? "Modifier" : "Corriger"}
                    </button> : <span className="source-badge measured">OBD</span>}
                  </article>
                ))}
              </div>
              {visiblePassiveSignals.length === 0 && (
                <p className="inline-alert">Aucun signal ne correspond aux filtres.</p>
              )}
              <div className="footer-meta">
                <span>{visiblePassiveSignals.length} affichés</span>
                <span>{passiveSensors.strict_passive ? "Passif strict" : liveObdReadOnly ? "OBD 01/09 filtré" : "Mode à vérifier"}</span>
                <span>Session {passiveSensors.session_id || "—"}</span>
              </div>
            </>
          )}
          {passiveSensors?.warnings.map((warning) => <p className="inline-alert" key={warning}>{warning}</p>)}
        </section>

        {sensorEditor && (
          <div className="sensor-editor-backdrop" role="presentation" onMouseDown={() => setSensorEditor(null)}>
            <form className="sensor-editor" onSubmit={savePassiveSensorOverride} onMouseDown={(event) => event.stopPropagation()}>
              <div className="section-heading">
                <div><span className="eyebrow">Correction locale persistante</span><h2>Corriger un capteur</h2>{LAB_MODE && <code>{sensorEditor.key}</code>}</div>
                <button type="button" className="ghost-button" onClick={() => setSensorEditor(null)}>Fermer</button>
              </div>
              <label>Nom lisible<input value={sensorEditor.label} onChange={(event) => setSensorEditor({ ...sensorEditor, label: event.target.value })} /></label>
              <label>Explication<textarea value={sensorEditor.description} onChange={(event) => setSensorEditor({ ...sensorEditor, description: event.target.value })} /></label>
              <div className="sensor-editor-grid">
                <label>Unité affichée<input value={sensorEditor.unit} onChange={(event) => setSensorEditor({ ...sensorEditor, unit: event.target.value })} placeholder="km/h, °C, %, N·m…" /></label>
                <label>Facteur<input type="number" step="any" value={sensorEditor.factor} onChange={(event) => setSensorEditor({ ...sensorEditor, factor: event.target.value })} /></label>
                <label>Offset<input type="number" step="any" value={sensorEditor.offset} onChange={(event) => setSensorEditor({ ...sensorEditor, offset: event.target.value })} /></label>
              </div>
              <p className="inline-alert">Valeur affichée = valeur OpenDBC × facteur + offset. La trame brute n'est jamais modifiée.</p>
              <div className="sensor-editor-actions">
                {sensorEditor.customized && <button type="button" className="stop-button" onClick={resetPassiveSensorOverride} disabled={sensorEditorBusy}>Réinitialiser</button>}
                <button type="submit" className="primary-button" disabled={sensorEditorBusy}>{sensorEditorBusy ? "Enregistrement…" : "Enregistrer la correction"}</button>
              </div>
            </form>
          </div>
        )}

        {liveSensorEditor && (
          <div className="sensor-editor-backdrop" role="presentation" onMouseDown={() => setLiveSensorEditor(null)}>
            <form className="sensor-editor" onSubmit={saveLiveSensor} onMouseDown={(event) => event.stopPropagation()}>
              <div className="section-heading">
                <div><span className="eyebrow">Registre Live Data · portée VIN</span><h2>{liveSensorEditor.key ? "Modifier le capteur" : "Ajouter un capteur"}</h2></div>
                <button type="button" className="ghost-button" onClick={() => setLiveSensorEditor(null)}>Fermer</button>
              </div>
              <label>Source physique<select value={liveSensorEditor.sourceKey} disabled={Boolean(liveSensorEditor.key)} onChange={(event) => {
                const source = passiveSensors?.signals.find((signal) => signal.key === event.target.value);
                setLiveSensorEditor({
                  ...liveSensorEditor,
                  sourceKey: event.target.value,
                  category: source?.category ?? liveSensorEditor.category,
                  unit: source?.unit ?? liveSensorEditor.unit,
                });
              }}>{passiveSensors?.signals.filter((signal) => !signal.user_defined).map((signal) => <option value={signal.key} key={signal.key}>{signal.display_name} · {signal.category}</option>)}</select></label>
              <label>Nom lisible<input required value={liveSensorEditor.label} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, label: event.target.value })} /></label>
              <label>Explication<textarea value={liveSensorEditor.description} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, description: event.target.value })} /></label>
              <div className="sensor-editor-grid">
                <label>Catégorie<input value={liveSensorEditor.category} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, category: event.target.value })} /></label>
                <label>Unité<input value={liveSensorEditor.unit} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, unit: event.target.value })} /></label>
                <label>Facteur<input type="number" step="any" value={liveSensorEditor.factor} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, factor: event.target.value })} /></label>
                <label>Offset<input type="number" step="any" value={liveSensorEditor.offset} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, offset: event.target.value })} /></label>
              </div>
              <p className="inline-alert">Ce capteur est rattaché au VIN {selectedDiagnosticVin}. La suppression l’archive pour préserver les anciennes captures.</p>
              <div className="sensor-editor-actions">
                {liveSensorEditor.key && <button type="button" className="stop-button" onClick={() => void archiveLiveSensor()} disabled={liveSensorEditorBusy}>Supprimer</button>}
                <button type="submit" className="primary-button" disabled={liveSensorEditorBusy || !liveSensorEditor.label.trim()}>{liveSensorEditorBusy ? "Enregistrement…" : liveSensorEditor.key ? "Enregistrer" : "Ajouter au Live Data"}</button>
              </div>
            </form>
          </div>
        )}
      </div>
    );
  }

  function renderSensorInventory() {
    const applicableTotal = Math.max(1, sensorInventoryRows.length - inventoryCounts.excluded);
    const coveredCount = inventoryCounts.measured + inventoryCounts.supported;
    const coverage = Math.round(coveredCount / applicableTotal * 100);
    const actionFor = (row: SensorInventoryRow, emphasized = false) => {
      const className = emphasized ? "primary-button" : "ghost-button";
      if (["to_test", "supported"].includes(row.status)) {
        return <button className={className} disabled={injectionBusy || !obdReadReady} onClick={() => { setValidationFocusId(row.id); void readInjectionParameters("inventory"); }}>{injectionBusy ? "Lecture…" : "Tester maintenant en OBD"}</button>;
      }
      if (row.status === "to_observe") {
        return <button className={className} disabled={detectionBusy || detectionRemaining > 0} onClick={() => { setValidationFocusId(row.id); void startFullSensorDetection(false, false); }}>{detectionRemaining > 0 ? `${detectionRemaining} s` : "Observer le CAN 30 s"}</button>;
      }
      if (row.status === "to_decode") {
        return <button className={className} onClick={() => { setValidationFocusId(row.id); setView("discovery"); }}>Créer une capture annotée</button>;
      }
      if (row.status === "measured") {
        return <button className={className} onClick={() => setView(row.source === "OBD-II" ? "injection" : "studio")}>Voir la preuve</button>;
      }
      return null;
    };
    const focusIndex = focusedValidationRow ? validationQueue.findIndex((row) => row.id === focusedValidationRow.id) : -1;
    const nextValidationRow = validationQueue.length
      ? validationQueue[(Math.max(0, focusIndex) + 1) % validationQueue.length]
      : null;
    const validationMethod = focusedValidationRow?.status === "to_observe"
      ? { code: "CAN", title: "Observation passive", text: "Provoque uniquement la grandeur ciblée pendant la fenêtre de 30 secondes. La valeur doit évoluer dans le bon sens et revenir au repos." }
      : focusedValidationRow?.status === "to_decode"
        ? { code: activeIsFiat500 ? "FIAT" : "PSA", title: "Découverte annotée", text: "Répète trois fois la même action avec le même marqueur. Le post-traitement comparera automatiquement les fenêtres avant et après." }
        : { code: "OBD", title: "Lecture moteur normalisée", text: "Le calculateur indique d’abord les PID supportés, puis la valeur est lue et contrôlée avant d’être classée mesurée." };

    return (
      <div className="sensor-inventory-page">
        <section className="panel inventory-hero">
          <div className="inventory-hero-copy">
            <span className="eyebrow">Couverture diagnostic de {activeVehicleLabel}</span>
            <h2>{coverage}% des informations applicables couvertes</h2>
            <p>Le classement est recalculé à partir du dernier direct CAN et du dernier relevé OBD-II. Une ligne « à décoder » correspond à une donnée {activeIsFiat500 ? "Fiat documentée ou plausible" : "PSA plausible"}, pas à la preuve que le véhicule expose déjà sa valeur.</p>
            <div className="inventory-progress"><i style={{ width: `${coverage}%` }} /></div>
          </div>
          <label className="powertrain-selector">
            <span>Motorisation</span>
            <select value={effectivePowertrainProfile} disabled={activeIsFiat500} onChange={(event) => setPowertrainProfile(event.target.value as PowertrainProfile)}>
              <option value="unknown">Encore inconnue</option>
              <option value="gasoline">{activeIsFiat500 ? "Essence 1.2 8V" : "Essence THP / PureTech"}</option>
              <option value="diesel">Diesel BlueHDi</option>
            </select>
            <small>{activeIsFiat500 ? "Profil confirmé pour la Fiat 500 2010." : powertrainProfile === "unknown" ? "FAP, SCR et paramètres essence restent tous visibles." : "Les éléments incompatibles sont classés non applicables."}</small>
          </label>
        </section>

        <section className="inventory-summary-grid">
          <button className={inventoryStatus === "available" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "available" ? "all" : "available")}><i className="measured" /><span>Mesurés</span><strong>{inventoryCounts.measured}</strong><small>Valeur reçue</small></button>
          <button className={inventoryStatus === "missing" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "missing" ? "all" : "missing")}><i className="missing" /><span>À compléter</span><strong>{inventoryCounts.missing}</strong><small>Test ou décodage requis</small></button>
          <button className={inventoryStatus === "excluded" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "excluded" ? "all" : "excluded")}><i className="excluded" /><span>Non applicables</span><strong>{inventoryCounts.excluded}</strong><small>Selon la motorisation</small></button>
          <div><span>Total catalogué</span><strong>{sensorInventoryRows.length}</strong><small>{inventorySystems.length - 1} systèmes</small></div>
        </section>

        <section className="panel validation-assistant">
          <div className="section-heading">
            <div><span className="eyebrow">Assistant de validation</span><h2>Une preuve à la fois</h2><p>L’outil choisit la méthode adaptée à la source et ne classe jamais un signal « validé » sur une simple supposition.</p></div>
            <span className={`status-pill ${validationQueue.length ? "neutral" : "good"}`}><i /> {validationQueue.length ? `${validationQueue.length} tests dans la file` : "File terminée"}</span>
          </div>
          {focusedValidationRow ? (
            <>
              <div className="validation-steps" aria-label="Étapes de validation">
                <div className="done"><span>1</span><strong>Cible choisie</strong><small>{focusedValidationRow.system}</small></div>
                <div className="active"><span>2</span><strong>Acquérir</strong><small>{validationMethod.title}</small></div>
                <div><span>3</span><strong>Contrôler</strong><small>Plage, réaction, cohérence</small></div>
                <div><span>4</span><strong>Classer</strong><small>Mesuré, plausible ou rejeté</small></div>
              </div>
              <div className="validation-focus-card">
                <div className="validation-method-code">{validationMethod.code}</div>
                <div className="validation-focus-copy">
                  <span>{focusedValidationRow.statusLabel} · priorité {focusedValidationRow.priority}</span>
                  <h3>{focusedValidationRow.label}</h3>
                  <p>{validationMethod.text}</p>
                  <code>{focusedValidationRow.reference ?? focusedValidationRow.source}</code>
                </div>
                <div className="validation-focus-actions">
                  {actionFor(focusedValidationRow, true)}
                  {nextValidationRow && <button className="ghost-button" onClick={() => setValidationFocusId(nextValidationRow.id)}>Passer au suivant</button>}
                </div>
              </div>
            </>
          ) : (
            <EmptyState title="Aucun test prioritaire" text="Toutes les informations testables de cette configuration disposent déjà d’une preuve." />
          )}
        </section>

        <section className="panel inventory-actions-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Actualiser les preuves</span><h2>Tester la couverture réelle</h2><p>Les deux lectures sont séparées : le CAN passif n'émet rien; l'OBD-II envoie des requêtes de lecture au calculateur moteur.</p></div>
          </div>
          <div className="inventory-actions">
            <button className="inventory-action" onClick={() => void startFullSensorDetection(false, false)} disabled={detectionBusy || detectionRemaining > 0}>
              <span>CAN</span><div><strong>{detectionRemaining > 0 ? `Observation · ${detectionRemaining} s` : "Observer le CAN pendant 30 s"}</strong><small>Recherche les signaux diffusés spontanément</small></div>
            </button>
            <button className="inventory-action" onClick={() => void readInjectionParameters("inventory")} disabled={injectionBusy || !obdReadReady}>
              <span>OBD</span><div><strong>{injectionBusy ? "Lecture moteur en cours…" : "Tester les PID moteur"}</strong><small>{obdReadReady ? "6/14 validé · OBD 01/09 uniquement" : "Firmware principal compatible requis"}</small></div>
            </button>
            <button className="inventory-action" onClick={() => setView("discovery")}>
              <span>{activeIsFiat500 ? "FIAT" : "PSA"}</span><div><strong>Découvrir un paramètre constructeur</strong><small>Capture annotée et corrélation hors ligne</small></div>
            </button>
          </div>
          {!activeIsFiat500 && powertrainProfile === "unknown" && <p className="inline-alert">Sélectionne la motorisation exacte dès qu'elle est confirmée : cela évitera de compter l'AdBlue, le FAP diesel ou le cliquetis essence comme des manques.</p>}
        </section>

        <section className="panel inventory-list-panel">
          <div className="section-heading inventory-list-heading">
            <div><span className="eyebrow">{visibleInventoryRows.length} informations affichées</span><h2>Catalogue et état de découverte</h2></div>
            <label className="inventory-priority-toggle"><input type="checkbox" checked={inventoryPriorityOnly} onChange={(event) => setInventoryPriorityOnly(event.target.checked)} /><span>Priorité atelier uniquement</span></label>
          </div>
          <div className="inventory-toolbar">
            <div className="inventory-system-tabs">
              {inventorySystems.map((system) => <button className={inventorySystem === system ? "active" : ""} key={system} onClick={() => setInventorySystem(system)}>{system}</button>)}
            </div>
            <input value={inventorySearch} onChange={(event) => setInventorySearch(event.target.value)} placeholder="Rechercher injecteur, FAP, rétro, pneu…" aria-label="Rechercher dans l'inventaire" />
          </div>
          <div className="inventory-status-legend">
            <span><i className="measured" />Mesuré</span><span><i className="supported" />Supporté</span><span><i className="test" />À tester/observer</span><span><i className="decode" />À décoder</span><span><i className="unsupported" />Non exposé</span><span><i className="excluded" />Non applicable</span>
          </div>
          <div className="inventory-table">
            {visibleInventoryRows.map((row) => (
              <article className={`sensor-inventory-row status-${row.status}`} key={row.id}>
                <div className="inventory-row-state"><i /><span>{row.statusLabel}</span></div>
                <div className="inventory-row-main"><span>{row.system} · priorité {row.priority}{row.optional ? " · équipement optionnel" : ""}</span><strong>{row.label}</strong><p>{row.description}</p></div>
                <div className="inventory-row-source"><strong>{row.value ?? row.source}</strong><code>{row.reference ?? "—"}</code></div>
                <div className="inventory-row-action">{actionFor(row)}</div>
              </article>
            ))}
            {visibleInventoryRows.length === 0 && <EmptyState title="Aucun résultat" text="Modifie les filtres ou la recherche pour retrouver les paramètres masqués." />}
          </div>
        </section>
      </div>
    );
  }

  function renderVehicleIdentity() {
    const displayedIdentity = vehicleIdentity?.vehicle_profile === identityProfileKey ? vehicleIdentity : null;
    const successfulFields = displayedIdentity?.fields.filter((field) => field.value && !field.error) ?? [];
    return (
      <div className="identity-page">
        <section className="panel identity-hero">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Identification multi-source enregistrée sur le PC</span>
              <h2>Lire le VIN sans modifier le véhicule</h2>
              <p>OpenDiag essaie les méthodes documentées dans l'ordre, valide le format du VIN et conserve les échanges OBD/UDS dans une trace JSONL.</p>
            </div>
            <span className={`status-pill ${identityReadReady ? "good" : "neutral"}`}><i /> {identityReadReady ? "Lecture prête" : capture?.active ? "Capture active" : "ESP32 à valider"}</span>
          </div>

          <div className="identity-launcher">
            <label>Marque
              <select
                value={selectedIdentityProfile?.manufacturer ?? ""}
                disabled={capture?.active}
                onChange={(event) => {
                  const next = vehicleProfiles.find((profile) => profile.manufacturer === event.target.value);
                  if (!next) return;
                  setIdentityProfileKey(next.key);
                  setSelectedDiagnosticVin("");
                  setVehicleIdentity(null);
                  setInjectionSnapshot(null);
                  setReport(null);
                  setError("");
                }}
              >
                {vehicleManufacturers.map((manufacturer) => <option value={manufacturer} key={manufacturer}>{manufacturer}</option>)}
              </select>
            </label>
            <label>Véhicule à identifier
              <select value={identityProfileKey} disabled={capture?.active} onChange={(event) => { setIdentityProfileKey(event.target.value); setSelectedDiagnosticVin(""); setVehicleIdentity(null); setInjectionSnapshot(null); setReport(null); setError(""); }}>
                {profilesForSelectedManufacturer.map((profile) => <option value={profile.key} key={profile.key}>{profile.model} · {profile.year ?? "année inconnue"}</option>)}
              </select>
            </label>
            <div className="identity-profile-summary">
              <span>{selectedIdentityProfile?.architecture ?? "Architecture à confirmer"}</span>
              <strong>{selectedIdentityProfile?.platform ?? "Plateforme inconnue"}</strong>
              <small>{selectedIdentityProfile?.identity_scope === "identity_only" ? "Identification seulement" : "Profil diagnostic complet"}</small>
            </div>
            <button className="primary-button" onClick={() => void readVehicleIdentity()} disabled={identityBusy || !identityReadReady || !selectedIdentityProfile}>
              {identityBusy ? "Lecture du véhicule…" : "Lire VIN + identité"}
            </button>
          </div>

          {!identityReadReady && <p className="inline-alert">{capture?.active && !dualCanOperational
            ? "Arrête et sauvegarde la capture avant cette lecture active."
            : status?.can_tx_enabled
              ? selectedIdentityProfile?.identity_scope === "identity_only" && !liveObdReadOnly
                ? "Ce profil utilise l’OBD normalisé : flashe le firmware principal qui annonce live_obd_read_only=true."
                : "Connecte l’ESP32 et vérifie la poignée de main du firmware diagnostic en lecture seule."
              : "CAN_TX_ENABLED doit autoriser les requêtes de lecture; les écritures restent bloquées."}</p>}
          {selectedIdentityProfile?.identity_scope === "identity_only" && <p className="inline-alert fiat-profile-note">Le profil Fiat est volontairement limité au VIN et aux informations OBD normalisées. Donne-moi ensuite l’année, la motorisation et si c’est une 500, 500X ou 500e pour construire le bon inventaire ECU.</p>}
        </section>

        {selectedIdentityProfile?.identity_scope === "identity_only" && <section className="panel">
          <div className="section-heading">
            <div><span className="eyebrow">Diagnostic hors inventaire complet</span><h2>Lecture DTC OBD générique</h2><p>Modes EOBD standards 03 (mémorisés) et 07 (en attente) sur le calculateur moteur — adresse et protocole confirmés, indépendant du verrou d’identification.</p></div>
            <button className="secondary-button" onClick={() => void readEngineObdDtcs()} disabled={obdDtcBusy || !identityReadReady}>{obdDtcBusy ? "Lecture…" : "Lire les DTC OBD (moteur)"}</button>
          </div>
          {obdDtcResult && (
            obdDtcResult.dtcs.length === 0 ? (
              <p className="inline-alert">Aucun code retourné.{obdDtcResult.dtc_error ? ` ${obdDtcResult.dtc_error}` : ""}</p>
            ) : (
              <div className="dtc-list">
                {obdDtcResult.dtcs.map((dtc) => (
                  <article className={`dtc-card ${dtc.state}`} key={`${dtc.raw_hex}-${dtc.state}`}>
                    <div className="dtc-code"><code>{dtc.code}</code></div>
                    <div className="dtc-description"><strong>{dtc.title ?? "Description spécifique inconnue"}</strong><p>{dtc.state_detail}</p></div>
                    <div className="dtc-meta"><span>{dtc.state_label}</span></div>
                  </article>
                ))}
              </div>
            )
          )}
        </section>}

        {selectedIdentityProfile?.identity_scope === "identity_only" && <section className="panel">
          <div className="section-heading">
            <div><span className="eyebrow">Prudence avant d’aller plus loin</span><h2>Test de présence UDS</h2><p>Une seule lecture DID standard (0xF186, session de diagnostic active) pour voir si le calculateur répond en UDS — sans supposer qu’il le fasse.</p></div>
          </div>
          <div className="dtc-clear-form">
            <label>Calculateur
              <select value={udsProbeEcuKey} onChange={(event) => { setUdsProbeEcuKey(event.target.value); setUdsProbeResult(null); }}>
                <option value="body_computer">Body Computer / BSI Fiat (0x7B0/0x7C0)</option>
                <option value="instrument_cluster">Combiné d'instruments Fiat (0x7B0/0x7C3)</option>
              </select>
            </label>
            <button className="secondary-button" onClick={() => void testUdsPresence()} disabled={udsProbeBusy || !identityReadReady}>{udsProbeBusy ? "Test…" : "Tester"}</button>
          </div>
          {udsProbeResult && (
            udsProbeResult.error ? (
              <p className="inline-alert">Pas de réponse UDS exploitable : {udsProbeResult.error}. Cohérent avec un silence total, une adresse fausse pour ce véhicule, ou un protocole KWP2000 non géré par ce firmware.</p>
            ) : (
              <p className="inline-alert">Réponse UDS reçue : session active = {String(udsProbeResult.value)}. Ce calculateur parle bien UDS à cette adresse.</p>
            )
          )}
        </section>}

        <section className="identity-layout">
          <article className={`panel vin-card ${displayedIdentity?.found ? "found" : ""}`}>
            <div className="section-heading"><div><span className="eyebrow">Vehicle Identification Number</span><h2>VIN</h2></div><span className={`status-pill ${displayedIdentity?.found ? "good" : "neutral"}`}><i /> {displayedIdentity?.found ? "Validé" : "Non lu"}</span></div>
            {displayedIdentity?.found ? (
              <>
                <strong className="vin-value">{displayedIdentity.vin}</strong>
                <div className="vin-metadata">
                  <div><span>WMI</span><strong>{displayedIdentity.wmi ?? "—"}</strong></div>
                  <div><span>Constructeur détecté</span><strong>{displayedIdentity.detected_manufacturer ?? "WMI non catalogué"}</strong></div>
                  <div><span>Correspondance profil</span><strong>{displayedIdentity.profile_match === true ? "Oui" : displayedIdentity.profile_match === false ? "Non" : "Non déterminée"}</strong></div>
                </div>
                <small className="identity-saved">Session {displayedIdentity.debug.session_id} · trace locale sauvegardée</small>
              </>
            ) : <EmptyState title="VIN pas encore lu" text="Sélectionne la Peugeot ou la Fiat, connecte l’ESP32 diagnostic, puis lance une lecture." />}
          </article>

          <article className="panel identity-methods-panel">
            <div className="section-heading"><div><span className="eyebrow">Ordre de repli contrôlé</span><h2>Méthodes prévues</h2></div></div>
            <div className="identity-method-list">
              {(selectedIdentityProfile?.vin_methods ?? []).map((method, index) => <div key={method}><span>{index + 1}</span><strong>{method}</strong></div>)}
            </div>
            {selectedIdentityProfile?.notes.slice(0, 3).map((note) => <p className="identity-note" key={note}>{note}</p>)}
          </article>
        </section>

        {displayedIdentity && (
          <>
            <section className="panel identity-attempts-panel">
              <div className="section-heading"><div><span className="eyebrow">{displayedIdentity.attempts.length} méthode(s) réellement interrogée(s)</span><h2>Preuves de lecture du VIN</h2></div><code>{displayedIdentity.transport}</code></div>
              <div className="identity-attempt-list">
                {displayedIdentity.attempts.map((attempt) => (
                  <article className={attempt.success ? "success" : "failed"} key={attempt.key}>
                    <i />
                    <div><span>{attempt.protocol.toUpperCase()} · {hexadecimal(attempt.request_id)} → {hexadecimal(attempt.response_id)}</span><strong>{attempt.label}</strong><small>{attempt.success ? `VIN ${attempt.vin}` : attempt.error ?? "Aucune réponse valide"}</small></div>
                    <div>{LAB_MODE && <code>{attempt.command_hex}</code>}<small>{attempt.confidence}</small>{attempt.source && <a href={attempt.source} target="_blank" rel="noreferrer">Source ↗</a>}</div>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel identity-fields-panel">
              <div className="section-heading"><div><span className="eyebrow">Informations complémentaires</span><h2>Logiciel, calibration et ECU</h2><p>{successfulFields.length} champ(s) décodé(s), les refus et absences restent visibles.</p></div></div>
              <div className="identity-field-grid">
                {displayedIdentity.fields.map((field) => (
                  <article className={field.error ? "field-error" : ""} key={field.key}>
                    <span>{field.protocol.toUpperCase()} · lecture d’identification</span>
                    <strong>{field.name}</strong>
                    <code>{field.error ?? field.value ?? "Réponse vide"}</code>
                    <small>{field.confidence}</small>
                  </article>
                ))}
              </div>
              {displayedIdentity.warnings.map((warning) => <p className="inline-alert" key={warning}>{warning}</p>)}
            </section>
          </>
        )}
      </div>
    );
  }

  function renderInjection() {
    const supportedCatalogCount = diagnosticSensorCatalog.filter((sensor) => injectionSnapshot?.supported_pids.includes(sensor.pid)).length;
    const measuredCount = injectionSnapshot?.values.filter((value) => value.value !== null && value.value !== undefined && !value.error).length ?? 0;
    const pressureInBar = (sensor: DiagnosticSensorCatalogEntry, value?: DiagnosticSensorValue) => {
      if (!["fuel_rail_gauge_pressure", "absolute_fuel_rail_pressure"].includes(sensor.key) || typeof value?.value !== "number") return null;
      return `${(value.value / 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} bar`;
    };
    const psaSpecificSensors = [
      ["Correction injecteur 1", "DID PSA à identifier"],
      ["Correction injecteur 2", "DID PSA à identifier"],
      ["Correction injecteur 3", "DID PSA à identifier"],
      ["Correction injecteur 4", "DID PSA à identifier"],
      ["Temps / quantité injectée", "DID PSA à identifier"],
      ["Consigne pression de rampe", "DID PSA à identifier"],
      ["Commande turbo / géométrie", "DID PSA à identifier"],
      ["Charge FAP / pression différentielle", "DID PSA à identifier"],
    ];

    return (
      <div className="injection-page">
        <section className="panel injection-gate">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Lecture active normalisée · aucune commande d'actionneur</span>
              <h2>Relevé moteur et injection</h2>
              <p>Interroge uniquement les PID OBD-II supportés par le calculateur moteur. Aucune écriture, adaptation ou commande d'injecteur.</p>
            </div>
            <span className={`status-pill ${obdReadReady ? "good" : "neutral"}`}><i /> {obdReadReady ? "Prêt" : capture?.active ? "Capture active" : status?.can_tx_enabled ? "Firmware 6/14 à valider" : "Verrouillé"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Liaison ESP32</span><strong>{diagnosticGatewayVerified ? "Validée" : "Connexion requise"}</strong></div>
            <div><span>Calculateur interrogé</span><strong>Calculateur moteur principal</strong></div>
            <div><span>Mode diagnostic</span><strong>OBD-II 01 · lecture seule</strong></div>
            <div><span>Réseau utilisé</span><strong>{obdReadReady ? "6/14 · OBD 01/09 filtré" : "6/14 indisponible"}</strong></div>
          </div>
          {obdReadReady ? (
            <button className="primary-button full-scan-button" onClick={() => void readInjectionParameters()} disabled={injectionBusy}>{injectionBusy ? "Lecture en cours…" : injectionSnapshot ? "Actualiser les paramètres d'injection" : "Lire les paramètres d'injection"}</button>
          ) : (
            <p className="inline-alert">{capture?.active && !dualCanOperational
              ? "Cette passerelle ne confirme pas deux contrôleurs CAN disponibles simultanément."
              : status?.can_tx_enabled
                ? "Connecte puis flashe le firmware principal compatible OBD 01/09 sur 6/14."
                : "Le backend est actuellement en écoute passive stricte; les requêtes OBD-II restent bloquées."}</p>
          )}
        </section>

        <section className="injection-summary-grid">
          <article><span>PID catalogués</span><strong>{diagnosticSensorCatalog.length || "—"}</strong><small>Mode 01 normalisé</small></article>
          <article><span>PID supportés</span><strong>{injectionSnapshot ? supportedCatalogCount : "—"}</strong><small>Déclarés par cet ECU</small></article>
          <article><span>Valeurs reçues</span><strong>{injectionSnapshot ? measuredCount : "—"}</strong><small>Dernier relevé</small></article>
          <article><span>Voyant / DTC émissions</span><strong>{injectionSnapshot?.mil_on === false ? `Éteint · ${injectionSnapshot.emissions_dtc_count ?? 0} DTC` : injectionSnapshot?.mil_on === true ? `Allumé · ${injectionSnapshot.emissions_dtc_count ?? 0} DTC` : "—"}</strong><small>Mode 01 · PID 01, sans effacement</small></article>
          <article><span>Trace locale</span><strong>{injectionSnapshot?.debug.session_id ? "Sauvegardée" : "—"}</strong><small>{injectionSnapshot?.debug.session_id ?? "Après la première lecture"}</small></article>
        </section>

        {injectionGroups.map(({ group, sensors }) => (
          <section className="panel injection-group" key={group}>
            <div className="section-heading">
              <div><span className="eyebrow">Injection · {group}</span><h2>{group}</h2></div>
              <span className="injection-group-count">{injectionSnapshot ? sensors.filter((sensor) => injectionSnapshot.supported_pids.includes(sensor.pid)).length : 0} / {sensors.length} supportés</span>
            </div>
            <div className="injection-sensor-grid">
              {sensors.map((sensor) => {
                const supported = Boolean(injectionSnapshot?.supported_pids.includes(sensor.pid));
                const value = injectionValues.get(sensor.key);
                const available = typeof value?.value === "number" && !value.error;
                const barValue = pressureInBar(sensor, value);
                return (
                  <article className={`${supported ? "supported" : ""} ${available ? "available" : ""}`} key={sensor.key}>
                    <header><span>PID 0x{sensor.pid.toString(16).toUpperCase().padStart(2, "0")}</span><i /></header>
                    <h3>{sensor.name}</h3>
                    <div className="injection-value">
                      <strong>{available ? Number(value?.value).toLocaleString("fr-FR", { maximumFractionDigits: 3 }) : "—"}</strong>
                      <span>{available ? value?.unit ?? sensor.unit : injectionSnapshot ? supported ? value?.error ?? "Réponse invalide" : "Non exposé par l'ECU" : "À lire"}</span>
                      {barValue && <small>{barValue}</small>}
                    </div>
                    <p>{sensor.description}</p>
                    <footer><span>{available ? "Mesuré" : supported ? "Support déclaré" : "Indisponible"}</span>{LAB_MODE && value?.raw_hex && <code>{value.raw_hex}</code>}</footer>
                  </article>
                );
              })}
            </div>
          </section>
        ))}

        <section className="panel psa-injection-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Données constructeur Peugeot / PSA</span>
              <h2>Paramètres avancés à cartographier</h2>
              <p>Ces valeurs ne sont pas des PID OBD universels. Elles nécessitent les DID exacts du calculateur d'injection de cette 308.</p>
            </div>
            <button className="secondary-button" onClick={() => setView("discovery")}>Ouvrir la découverte</button>
          </div>
          <div className="psa-specific-grid">
            {psaSpecificSensors.map(([name, state]) => <article key={name}><i /><div><strong>{name}</strong><span>{state}</span></div></article>)}
          </div>
          <p className="inline-alert">Les « corrections injecteurs » ne sont pas les corrections de richesse OBD B1/B2. Elles seront affichées cylindre par cylindre seulement après identification et validation des DID PSA, moteur tournant dans des conditions maîtrisées.</p>
        </section>

        <section className="panel injection-dtc-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Calculateur moteur / injection</span><h2>Défauts liés au moteur</h2><p>{report ? `${engineDtcs.length} défaut(s) remonté(s) au dernier inventaire ECU.` : "Lance l’inventaire ECU pour lire la mémoire de défauts du calculateur moteur."}</p></div>
            <button className="secondary-button" onClick={() => setView("ecus")}>{report ? "Voir l'inventaire" : "Préparer le scan ECU"}</button>
          </div>
          {engineDtcs.length > 0 ? <div className="injection-dtc-list">{engineDtcs.map((dtc) => <article key={`${dtc.code}-${dtc.raw_hex}`}><code>{dtc.code}</code><div><strong>{dtc.title ?? "Défaut injection non décodé"}</strong><span>{dtc.status_labels.join(" · ") || `Statut ${dtc.status_hex}`}</span></div></article>)}</div> : <p className="injection-empty-dtc">{report ? "Aucun DTC moteur remonté lors du dernier scan." : "Aucune lecture du calculateur moteur dans cette session."}</p>}
        </section>
      </div>
    );
  }

  function renderMaintenance() {
    if (!maintenanceCatalog) {
      return <EmptyState title="Catalogue en chargement" text="Lecture des capacités du profil véhicule actif." />;
    }
    const applicabilityLabel: Record<MaintenanceService["applicability"], string> = {
      applicable: "Applicable",
      if_equipped: "Selon équipement",
      not_applicable: "Non applicable",
      unknown: "À rechercher",
    };
    const statusLabel: Record<MaintenanceService["implementation_status"], string> = {
      vehicle_validated: "Validé véhicule",
      procedure_required: "Procédure à valider",
      equipment_confirmation_required: "Équipement à confirmer",
      not_applicable: "Masqué sur ce profil",
      research_required: "Documentation requise",
    };
    return (
      <>
        <section className="panel maintenance-overview">
          <div className="section-heading">
            <div><span className="eyebrow">{maintenanceCatalog.manufacturer} {maintenanceCatalog.model}</span><h2>{maintenanceCatalog.service_count} services référencés</h2><p>Le catalogue n'autorise jamais une trame tant que la procédure exacte et ses prérequis ne sont pas validés sur le véhicule.</p></div>
            <span className={`status-pill ${maintenanceCatalog.execution_enabled ? "good" : "neutral"}`}><i />{maintenanceCatalog.execution_enabled ? "Procédures validées disponibles" : "Catalogue sécurisé"}</span>
          </div>
          <div className="maintenance-protocol-grid">
            {maintenanceCatalog.protocol_coverage.map((protocol) => <article className={protocol.supported ? "supported" : "missing"} key={protocol.key}><strong>{protocol.name}</strong><span>{protocol.supported ? "Pris en charge" : "Matériel requis"}</span><p>{protocol.detail}</p></article>)}
          </div>
          {maintenanceCatalog.notes.map((note) => <p className="inline-alert" key={note}>{note}</p>)}
        </section>

        <section className="panel maintenance-catalog-panel">
          <div className="section-heading"><div><span className="eyebrow">Matrice d'applicabilité</span><h2>Fonctions Fiat / Peugeot</h2></div></div>
          <div className="sensor-category-tabs">
            {maintenanceCategories.map((category) => <button className={maintenanceCategory === category ? "active" : ""} key={category} onClick={() => setMaintenanceCategory(category)}>{category}</button>)}
          </div>
          <div className="maintenance-service-grid">
            {visibleMaintenanceServices.map((service) => (
              <article className={`${service.applicability} risk-${service.risk}`} key={service.key}>
                <header><span>{service.category}</span><b>{applicabilityLabel[service.applicability]}</b></header>
                <h3>{service.name}</h3>
                <p>{service.description}</p>
                <small>{service.reason}</small>
                <footer><span>{statusLabel[service.implementation_status]}</span><button className="secondary-button" disabled={!service.execution_enabled} onClick={() => setError("L'exécuteur de cette procédure n'est pas encore installé.")}>{service.execution_enabled ? "Ouvrir la procédure" : "Verrouillé"}</button></footer>
              </article>
            ))}
          </div>
        </section>
      </>
    );
  }

  function renderPsaAdvanced() {
    const firmwarePolicy = String(status?.gateway_hello?.tx_policy ?? (status?.transport === "virtual" ? "virtual-psa-lab" : "non vérifié"));
    const psaFirmwareReady = status?.transport === "virtual" || status?.gateway_hello?.psa_lab === true;
    const labRuntimeReady = Boolean(
      psaCatalog?.enabled
      && psaCatalog.actuator_enabled
      && !psaCatalog.read_only
      && diagnosticReady
      && psaFirmwareReady,
    );
    const psaReadReady = diagnosticReady && psaVehicleCompatible;
    const activeAuthorizationSteps = [
      { label: "Passerelle", detail: diagnosticGatewayVerified ? "ESP32 authentifié" : "Connexion requise", complete: diagnosticGatewayVerified },
      { label: "Firmware", detail: psaFirmwareReady ? "Allowlist PSA lab" : "Profil PSA lab requis", complete: psaFirmwareReady },
      { label: "Backend", detail: psaCatalog?.actuator_enabled && !psaCatalog.read_only ? "Actions explicitement activées" : "Configuration verrouillée", complete: Boolean(psaCatalog?.actuator_enabled && !psaCatalog.read_only) },
      { label: "Véhicule", detail: !psaVehicleCompatible ? "Profil PSA requis" : psaLabChecksComplete ? "VIN et préconditions confirmés" : "Contrôles à terminer", complete: psaVehicleCompatible && psaLabChecksComplete },
    ];
    const activeAuthorizationProgress = activeAuthorizationSteps.filter((step) => step.complete).length;
    const activeAuthorizationReady = labRuntimeReady && psaVehicleCompatible && psaLabChecksComplete;
    const unlockableEcus = psaCatalog?.ecus.filter((ecu) => ["bsi", "telematics"].includes(ecu.key) && ecu.security_keys.length) ?? [];
    const updateLabCheck = (key: keyof typeof psaLabChecks, checked: boolean) => {
      setPsaLabChecks((current) => ({ ...current, [key]: checked }));
    };

    return (
      <div className="psa-advanced-page">
        <section className="panel psa-advanced-hero">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Inspiré d'arduino-psa-diag · intégration native OpenDiag</span>
              <h2>Passerelle PSA sans VCI Diagbox</h2>
              <p>Notre ESP32 transporte directement les échanges ISO-TP. Les lectures restent disponibles avec le firmware diagnostic; les commandes actives exigent le profil PSA lab à allowlist stricte.</p>
            </div>
            <span className={`status-pill ${psaCatalog?.enabled ? "good" : "neutral"}`}><i /> {psaCatalog?.enabled ? "Module chargé" : "Indisponible"}</span>
          </div>
          <div className="psa-readiness-grid">
            <article><span>Transport</span><strong>{status?.transport ?? "—"}</strong><small>{diagnosticGatewayVerified ? "Passerelle validée" : "Connexion requise"}</small></article>
            <article><span>Politique firmware</span><strong>{firmwarePolicy}</strong><small>{psaFirmwareReady ? "PSA lab reconnu" : "Lecture seule uniquement"}</small></article>
            <article><span>Lecture UDS</span><strong>{psaReadReady ? "Prête" : "Verrouillée"}</strong><small>{psaVehicleCompatible ? "Services 0x19 / 0x22 / 0x3E" : "Charge un véhicule PSA"}</small></article>
            <article><span>Actionneurs</span><strong>{labRuntimeReady ? "Armables" : "Verrouillés"}</strong><small>0x2F exact · temporisation ≤ 3 s</small></article>
          </div>
          {psaCatalog && <div className="psa-wiring-note"><strong>Réseaux OBD à vérifier avant branchement</strong><span>{psaCatalog.wiring.vehicle_can} · {psaCatalog.wiring.standard_obd}</span><p>{psaCatalog.wiring.warning}</p></div>}
        </section>

        <nav className="workspace-tabs" aria-label="Mode du diagnostic PSA">
          <button className={psaSection === "read" ? "active" : ""} onClick={() => setPsaSection("read")}><span>01</span><div><strong>Lecture sécurisée</strong><small>DID et identification</small></div></button>
          <button className={psaSection === "actions" ? "active danger" : ""} onClick={() => setPsaSection("actions")}><span>02</span><div><strong>Commandes actives</strong><small>Armement contrôlé</small></div></button>
          <button className={psaSection === "expert" ? "active" : ""} onClick={() => setPsaSection("expert")}><span>03</span><div><strong>Outils experts</strong><small>Seed/key et SecurityAccess</small></div></button>
        </nav>

        {psaSection === "read" && <section className="panel psa-zone-reader">
          <div className="section-heading">
            <div><span className="eyebrow">ReadDataByIdentifier · service 0x22</span><h2>Lire une zone brute BSI, NAC ou ECU</h2><p>Cette lecture accepte un DID PSA non encore catalogué et conserve sa réponse brute dans une trace locale.</p></div>
            <span className={`status-pill ${psaReadReady ? "good" : "neutral"}`}><i /> {psaReadReady ? "Lecture autorisée" : psaVehicleCompatible ? "CAN TX lecture requis" : "Mauvais véhicule actif"}</span>
          </div>
          <div className="psa-zone-form">
            <label>Calculateur<select value={psaEcuKey} onChange={(event) => { setPsaEcuKey(event.target.value); setPsaDidResult(null); }}>{psaCatalog?.ecus.map((ecu) => <option key={ecu.key} value={ecu.key}>{ecu.name}</option>)}</select></label>
            <label>DID hexadécimal<div className="psa-hex-input"><span>0x</span><input value={psaDid} onChange={(event) => setPsaDid(event.target.value.toUpperCase())} maxLength={6} /></div></label>
            <button className="primary-button" onClick={() => void readPsaDid()} disabled={psaBusy === "did" || !psaReadReady}>{psaBusy === "did" ? "Lecture…" : "Lire la zone"}</button>
          </div>
          <div className="psa-ecu-address"><span>{selectedPsaEcu?.family ?? "Famille inconnue"}</span><code>{hexadecimal(selectedPsaEcu?.request_id)} → {hexadecimal(selectedPsaEcu?.response_id)}</code><small>{selectedPsaEcu?.optional ? "Équipement optionnel" : "Calculateur attendu sur T9"}</small></div>
          {psaDidResult && <div className="psa-zone-result">
            <div><span>DID 0x{psaDidResult.did.toString(16).toUpperCase().padStart(4, "0")}</span><strong>{String(psaDidResult.value ?? "Réponse vide")}</strong></div>
            <code>{psaDidResult.raw_hex ?? "—"}</code>
            <small>{psaDidResult.codec} · {psaDidResult.confidence}</small>
            {psaDidResult.telecoding && <TelecodingDetails zone={psaDidResult.telecoding} />}
          </div>}
        </section>}

        {psaSection === "expert" && <section className="psa-two-column">
          <article className="panel psa-seed-panel">
            <div className="section-heading"><div><span className="eyebrow">Calcul local · aucune émission CAN</span><h2>Calculateur seed/key PSA</h2><p>Reproduit l'algorithme PSA public pour une seed de 4 octets et une clé application de 2 octets.</p></div></div>
            <div className="psa-seed-form">
              <label>Seed<input value={psaSeed} onChange={(event) => setPsaSeed(event.target.value.toUpperCase())} maxLength={8} /></label>
              <label>Clé application<input value={psaApplicationKey} onChange={(event) => setPsaApplicationKey(event.target.value.toUpperCase())} maxLength={4} /></label>
              <button className="secondary-button" onClick={() => void calculatePsaSeedKey()} disabled={psaBusy === "seed"}>{psaBusy === "seed" ? "Calcul…" : "Calculer hors ligne"}</button>
            </div>
            {psaSeedResult && <div className="psa-seed-result"><span>Réponse key</span><strong>{psaSeedResult.response_key_hex}</strong><small>Non transmise · source publique PSA seed/key</small></div>}
          </article>

          <article className="panel psa-keys-panel">
            <div className="section-heading"><div><span className="eyebrow">Variantes à confirmer par identification ECU</span><h2>Clés candidates documentées</h2></div></div>
            <div className="psa-key-list">
              {(psaCatalog?.ecus.filter((ecu) => ecu.security_keys.length) ?? []).map((ecu) => <div key={ecu.key}><span>{ecu.name}</span><div>{ecu.security_keys.map((candidate) => <button key={candidate.variant} onClick={() => { setPsaApplicationKey(candidate.key_hex); setPsaSeedResult(null); }}><strong>{candidate.variant}</strong><code>{candidate.key_hex}</code></button>)}</div></div>)}
            </div>
            <p className="inline-alert">Une clé candidate ne confirme pas la variante montée. Une identification erronée peut déclencher l'anti-bruteforce de l'ECU.</p>
          </article>
        </section>}

        {psaSection === "actions" && <>
        <section className="panel active-authorization-panel">
          <div className="authorization-heading">
            <div><span className="eyebrow">Autorisation temporaire · non mémorisée</span><h2>Préparer une commande active</h2><p>Une action ne devient exécutable que lorsque les quatre couches sont vertes. Une mesure CAN disponible ne peut pas être remplacée par une déclaration manuelle contradictoire.</p></div>
            <div className={`authorization-score ${activeAuthorizationReady ? "ready" : ""}`}><strong>{activeAuthorizationProgress}/4</strong><span>{activeAuthorizationReady ? "Prêt à armer" : "Verrouillé"}</span></div>
          </div>
          <div className="authorization-chain">
            {activeAuthorizationSteps.map((step, index) => <div className={step.complete ? "complete" : ""} key={step.label}><span>{index + 1}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div></div>)}
          </div>
          <div className="authorization-conditions">
            <label className={`${effectivePsaLabChecks.vehicle_stationary ? "complete" : ""} ${liveSafetyEvidence.speedKnown && !liveSafetyEvidence.stationary ? "blocked" : ""}`}>
              <input type="checkbox" disabled={liveSafetyEvidence.speedKnown} checked={effectivePsaLabChecks.vehicle_stationary} onChange={(event) => updateLabCheck("vehicle_stationary", event.target.checked)} />
              <span><strong>Véhicule immobilisé</strong><small>{liveSafetyEvidence.speedKnown ? liveSafetyEvidence.stationary ? "Mesuré sur 5 s : 0 km/h" : "Refusé : vitesse détectée" : "À confirmer manuellement"}</small></span>
            </label>
            <label className={`${effectivePsaLabChecks.ignition_on_engine_off ? "complete" : ""} ${liveSafetyEvidence.rpmKnown && !liveSafetyEvidence.engineOff ? "blocked" : ""}`}>
              <input type="checkbox" disabled={liveSafetyEvidence.rpmKnown} checked={effectivePsaLabChecks.ignition_on_engine_off} onChange={(event) => updateLabCheck("ignition_on_engine_off", event.target.checked)} />
              <span><strong>Contact mis, moteur arrêté</strong><small>{liveSafetyEvidence.rpmKnown ? liveSafetyEvidence.engineOff ? "Mesuré sur 5 s : régime nul" : "Refusé : moteur tournant" : "À confirmer manuellement"}</small></span>
            </label>
            <label className={`${effectivePsaLabChecks.stable_battery_voltage ? "complete" : ""} ${liveSafetyEvidence.batteryKnown && !liveSafetyEvidence.batteryStable ? "blocked" : ""}`}>
              <input type="checkbox" disabled={liveSafetyEvidence.batteryKnown} checked={effectivePsaLabChecks.stable_battery_voltage} onChange={(event) => updateLabCheck("stable_battery_voltage", event.target.checked)} />
              <span><strong>Tension batterie stable</strong><small>{liveSafetyEvidence.batteryKnown ? liveSafetyEvidence.batteryStable ? `Mesurée : ${liveSafetyEvidence.batteryValue?.toFixed(2)} V` : "Refusée : tension instable/hors plage" : "À confirmer manuellement"}</small></span>
            </label>
            <label className={effectivePsaLabChecks.workshop_or_private_site ? "complete" : ""}>
              <input type="checkbox" checked={psaLabChecks.workshop_or_private_site} onChange={(event) => updateLabCheck("workshop_or_private_site", event.target.checked)} />
              <span><strong>Atelier ou site privé</strong><small>Confirmation humaine obligatoire</small></span>
            </label>
          </div>
          {!passiveSensors?.active && <p className="authorization-hint">Pour automatiser vitesse, régime et tension, démarre le direct CAN avec la double passerelle. Sans télémétrie fraîche, ces trois conditions restent des confirmations manuelles transmises et journalisées.</p>}
        </section>

        <section className="panel psa-actions-panel">
          <div className="section-heading">
            <div><span className="eyebrow">InputOutputControlByIdentifier · service 0x2F</span><h2>Actionneurs nommés</h2><p>Aucun champ de trame libre : le backend et le firmware vérifient tous deux chaque payload exact.</p></div>
            <span className={`status-pill ${labRuntimeReady ? "good" : "neutral"}`}><i /> {labRuntimeReady ? "PSA lab prêt" : "Double verrou actif"}</span>
          </div>
          <div className="psa-action-grid">
            {psaCatalog?.actions.map((action) => (
              <article className={`${action.available ? "available" : "unknown"} ${psaSelectedActionKey === action.key ? "selected" : ""}`} key={action.key}>
                <header><span>{action.ecu_key.toUpperCase()}</span><i /></header>
                <h3>{action.name}</h3><p>{action.description}</p>
                <code>{action.start_payload_hex ?? "COMMANDE À IDENTIFIER"}</code>
                <span className={`validation-badge ${action.vehicle_confirmed ? "validated" : action.available ? "plausible" : "candidate"}`}>{action.vehicle_confirmed ? "Confirmé sur ce VIN" : action.available ? "Documenté · essai véhicule requis" : "Non documenté"}</span>
                {action.unavailable_reason && <small>{action.unavailable_reason}</small>}
                <button className="ghost-button" disabled={!action.available} onClick={() => { setPsaSelectedActionKey(action.key); setPsaConfirmation(""); setPsaFeedback(""); }}>{action.available ? "Préparer le test" : "Non disponible"}</button>
              </article>
            ))}
          </div>

          {selectedPsaAction && <div className="psa-action-gate">
            <div><span>Action préparée</span><strong>{selectedPsaAction.name}</strong><code>{selectedPsaAction.start_payload_hex}{selectedPsaAction.stop_payload_hex ? ` → arrêt ${selectedPsaAction.stop_payload_hex}` : ""}</code></div>
            {selectedPsaAction.timed && <label>Durée<input type="number" min={250} max={3000} step={250} value={psaDurationMs} onChange={(event) => setPsaDurationMs(Math.max(250, Math.min(3000, Number(event.target.value))))} /><span>ms</span></label>}
            <label className="psa-confirmation-field">Confirmation exacte<input value={psaConfirmation} onChange={(event) => setPsaConfirmation(event.target.value)} placeholder={selectedPsaAction.confirmation ?? ""} /><small>{selectedPsaAction.confirmation}</small></label>
            <button className="danger-button" onClick={() => void executePsaAction()} disabled={!activeAuthorizationReady || psaConfirmation !== selectedPsaAction.confirmation || psaBusy === "action"}>{psaBusy === "action" ? "Action en cours…" : "Exécuter puis arrêter"}</button>
          </div>}
        </section>
        </>}

        {psaSection === "expert" && <section className="panel psa-security-panel">
          <div className="section-heading"><div><span className="eyebrow">Verrous communs aux actions et à SecurityAccess</span><h2>Armement atelier</h2><p>Ces confirmations sont transmises avec l'opération; elles ne sont pas mémorisées.</p></div></div>
          <div className="psa-safety-checks">
            <label><input type="checkbox" disabled={liveSafetyEvidence.speedKnown} checked={effectivePsaLabChecks.vehicle_stationary} onChange={(event) => updateLabCheck("vehicle_stationary", event.target.checked)} /><span>Véhicule immobilisé</span></label>
            <label><input type="checkbox" disabled={liveSafetyEvidence.rpmKnown} checked={effectivePsaLabChecks.ignition_on_engine_off} onChange={(event) => updateLabCheck("ignition_on_engine_off", event.target.checked)} /><span>Contact mis, moteur arrêté</span></label>
            <label><input type="checkbox" disabled={liveSafetyEvidence.batteryKnown} checked={effectivePsaLabChecks.stable_battery_voltage} onChange={(event) => updateLabCheck("stable_battery_voltage", event.target.checked)} /><span>Tension batterie stable</span></label>
            <label><input type="checkbox" checked={psaLabChecks.workshop_or_private_site} onChange={(event) => updateLabCheck("workshop_or_private_site", event.target.checked)} /><span>Atelier ou site privé</span></label>
          </div>
          <div className="psa-unlock-row">
            <label>ECU<select value={psaUnlockEcuKey} onChange={(event) => { const key = event.target.value; const ecu = psaCatalog?.ecus.find((candidate) => candidate.key === key); setPsaUnlockEcuKey(key); setPsaUnlockApplicationKey(ecu?.security_keys[0]?.key_hex ?? ""); setPsaUnlockConfirmation(""); }}>{unlockableEcus.map((ecu) => <option value={ecu.key} key={ecu.key}>{ecu.name}</option>)}</select></label>
            <label>Clé<select value={psaUnlockApplicationKey} onChange={(event) => setPsaUnlockApplicationKey(event.target.value)}>{psaUnlockEcu?.security_keys.map((candidate) => <option value={candidate.key_hex} key={candidate.variant}>{candidate.variant} · {candidate.key_hex}</option>)}</select></label>
            <label>Confirmation<input value={psaUnlockConfirmation} onChange={(event) => setPsaUnlockConfirmation(event.target.value)} placeholder={`DEVERROUILLER ${psaUnlockEcuKey.toUpperCase()}`} /></label>
            <button className="danger-button" onClick={() => void unlockPsaConfiguration()} disabled={!psaCatalog?.security_access_enabled || !psaFirmwareReady || !psaLabChecksComplete || psaUnlockConfirmation !== `DEVERROUILLER ${psaUnlockEcuKey.toUpperCase()}` || psaBusy === "unlock"}>{psaBusy === "unlock" ? "Échange seed/key…" : "Déverrouiller sans écrire"}</button>
          </div>
          <p className="inline-alert">SecurityAccess est désactivé par défaut (`PSA_SECURITY_ACCESS_ENABLED=false`). La session est refermée immédiatement et aucune écriture `0x2E`, routine `0x31`, programmation ou effacement n'est autorisé.</p>
        </section>}

        {psaFeedback && <div className="psa-feedback"><strong>Opération terminée</strong><span>{psaFeedback}</span></div>}
      </div>
    );
  }

  function renderEcus() {
    return (
      <div className="ecu-discovery-page">
        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Découverte passive · aucune émission</span>
              <h2>Systèmes observés sur le CAN</h2>
              <p>Présence déduite des messages diffusés; ce n'est pas encore une identification UDS du calculateur.</p>
            </div>
            <button className="secondary-button" onClick={() => startFullSensorDetection(false, false)} disabled={detectionBusy || detectionRemaining > 0}>
              {detectionRemaining > 0 ? `Observation · ${detectionRemaining} s` : "Relancer l'observation"}
            </button>
          </div>
          <div className="passive-system-grid">
            {passiveSubsystems.map((subsystem) => (
              <article className={subsystem.detected ? "detected" : ""} key={subsystem.category}>
                <div><span className={`state-dot ${subsystem.detected ? "online" : "offline"}`} /><small>{subsystem.detected ? "Trafic observé" : "Non observé"}</small></div>
                <h3>{subsystem.name}</h3>
                <p>{subsystem.description}</p>
                <footer>{subsystem.messages.length ? subsystem.messages.slice(0, 4).join(" · ") : "Aucune preuve passive"}</footer>
              </article>
            ))}
          </div>
        </section>

        <section className="panel active-diagnostic-gate">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Diagnostic actif en lecture seule</span>
              <h2>Identifier tous les ECU et lire leurs défauts</h2>
              <p>Cette étape ouvre une session de lecture, identifie les systèmes et relève leurs défauts, sans effacement ni télécodage.</p>
            </div>
            <span className={`status-pill ${diagnosticReady ? "good" : "neutral"}`}><i /> {diagnosticReady ? (dualCanOperational ? "Double CAN prêt" : "Prêt") : capture?.active ? "Capture active" : status?.can_tx_enabled ? "ESP32 à valider" : "Verrouillé"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Liaison ESP32</span><strong>{diagnosticGatewayVerified ? "Poignée de main validée" : "Connexion requise"}</strong></div>
            <div><span>Réseaux CAN</span><strong>{dualCanOperational ? liveObdReadOnly ? "6/14 OBD lecture + 3/8 diagnostic" : "6/14 live + 3/8 diagnostic" : status?.gateway_hello?.dual_can === true ? "Double CAN détecté" : "Interface unique"}</strong></div>
            <div><span>Firmware ESP32</span><strong>{status?.gateway_hello?.diagnostic_read_only === true || status?.transport === "virtual" ? "Lecture seule validée" : status?.can_tx_enabled ? "À confirmer" : "Listen-only"}</strong></div>
            <div><span>Requêtes CAN</span><strong>{status?.can_tx_enabled ? "UDS lecture uniquement" : "Bloquées"}</strong></div>
            <div><span>Effacement / télécodage</span><strong>{status?.dtc_clear_enabled ? "Maintenance armée" : "Toujours interdit"}</strong></div>
          </div>
          {diagnosticReady ? (
            <button className="primary-button full-scan-button" onClick={scan} disabled={busy}>{busy ? "Inventaire en cours…" : "Lancer l'inventaire ECU + DTC"}</button>
          ) : (
            <p className="inline-alert">{capture?.active && !dualCanOperational
              ? "La capture est active mais le MCP2515 diagnostic 3/8 n’est pas confirmé disponible."
              : status?.can_tx_enabled
                ? "Retourne au Dashboard direct, sélectionne l’ESP32 puis clique sur Connecter. La poignée de main doit confirmer le firmware diagnostic en lecture seule."
                : "Le backend est verrouillé en écoute passive. Un firmware diagnostic séparé et CAN_TX_ENABLED=true sont nécessaires pour les lectures UDS."}</p>
          )}
        </section>

        {report && (
          <section className="panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">{detectedEcus.length} détectés sur {report.ecus.length}</span>
                <h2>Diagnostic par calculateur</h2>
                <p>Sélectionne un système pour retrouver son état, son identification, ses défauts et les fonctions qui lui sont rattachées.</p>
              </div>
              <div className="section-actions">
                <button className="ghost-button" onClick={() => void verifyDiagnosticRegression()} disabled={!report.scan_id || diagnosticRegressionBusy}>{diagnosticRegressionBusy ? "Comparaison…" : "Vérifier la référence"}</button>
                <button className="secondary-button" onClick={scan} disabled={busy || !diagnosticReady}>Relancer le scan</button>
              </div>
            </div>
            {diagnosticRegression && <div className={`regression-result ${diagnosticRegression.connectivity_match ? "good" : "warning"}`}>
              <strong>{diagnosticRegression.connectivity_match ? "Couverture ECU conforme" : "Écart de couverture ECU"}</strong>
              <span>{diagnosticRegression.connectivity_match ? "Les 8 calculateurs, leurs adresses et leurs réponses de session correspondent à la référence réelle." : `${diagnosticRegression.differences.filter((item) => item.scope === "connectivity").length} différence(s) de communication.`}</span>
              <small>{diagnosticRegression.dtc_match ? "Mémoire DTC brute identique à la référence." : "Les DTC ont évolué : ce résultat peut être normal après une réparation ou un effacement."}</small>
            </div>}
            <div className="ecu-selector" role="tablist" aria-label="Calculateurs détectés">
              {detectedEcus.map((ecu) => <button
                type="button"
                role="tab"
                aria-selected={selectedEcu?.key === ecu.key}
                className={selectedEcu?.key === ecu.key ? "selected" : ""}
                onClick={() => setSelectedEcuKey(ecu.key)}
                key={ecu.key}
              >
                <i />
                <span>{ecu.name}</span>
                <small>{ecu.dtcs.filter((dtc) => dtc.state === "active").length || "OK"}</small>
              </button>)}
            </div>

            {selectedEcu && <div className="ecu-workspace">
              <header>
                <div>
                  <span className="eyebrow">{selectedEcu.family ?? selectedEcu.network}</span>
                  <h3>{selectedEcu.name}</h3>
                  <p>{selectedEcu.detected ? "Calculateur joignable lors du dernier diagnostic." : "Calculateur non joint lors du dernier diagnostic."}</p>
                </div>
                <span className={`status-pill ${selectedEcu.detected ? "good" : "neutral"}`}><i /> {selectedEcu.detected ? "Détecté" : "Absent"}</span>
              </header>
              <div className="ecu-workspace-summary">
                <div><span>Identification</span><strong>{selectedEcu.identification.filter((item) => !item.error).length} information(s)</strong><small>Versions, références et numéros disponibles</small></div>
                <div><span>Défauts actifs</span><strong>{selectedEcu.dtcs.filter((dtc) => dtc.state === "active").length}</strong><small>{selectedEcu.dtcs.length} entrée(s) lue(s) au total</small></div>
                <div><span>Communication</span><strong>{selectedEcu.active_session ? "Session diagnostic" : "Présence confirmée"}</strong><small>{selectedEcu.probe_method ? `Méthode ${selectedEcu.probe_method}` : selectedEcu.network}</small></div>
                <div><span>Tests fonctionnels</span><strong>Aucun test publié</strong><small>Une commande reste indisponible tant que son workflow n’est pas validé</small></div>
              </div>
              <div className="ecu-workspace-actions">
                <button className="secondary-button" onClick={() => void openPassiveSensors()}>Live Data</button>
                <button className="secondary-button" onClick={() => setView("dtcs")}>Défauts</button>
                <button className="secondary-button" onClick={() => setView("garage")}>Historique</button>
                <button className="secondary-button" onClick={() => setView("database")}>Documentation</button>
                <button className="ghost-button" onClick={() => setView("maintenance")}>Fonctions disponibles</button>
              </div>
              {selectedEcu.identification.some((item) => !item.error) ? <div className="ecu-identification-list">
                {selectedEcu.identification.filter((item) => !item.error).map((item) => <article key={item.did}>
                  <span>{item.name}</span>
                  <strong>{String(item.value ?? "—")}</strong>
                  <small>{item.source ?? "Lecture véhicule"} · confiance {item.confidence}</small>
                </article>)}
              </div> : <p className="inline-alert">Aucune version ni référence n’a encore été obtenue pour ce calculateur.</p>}
              {selectedEcu.identification.some((item) => item.error) && <p className="ecu-read-summary">{selectedEcu.identification.filter((item) => item.error).length} information(s) supplémentaire(s) non disponible(s) sur cette session.</p>}
              {LAB_MODE && <details className="ecu-technical-details">
                <summary>Preuves protocolaires · mode laboratoire</summary>
                <div><code>{hexadecimal(selectedEcu.request_id)} → {hexadecimal(selectedEcu.response_id)}</code><span>Adressage diagnostic</span><small>{selectedEcu.network}</small></div>
                {selectedEcu.probe_attempts?.map((attempt, index) => <div key={`${attempt.request_hex}-${index}`}><code>{attempt.request_hex}</code><span>{attempt.outcome}</span><small>{attempt.response_hex ?? attempt.error ?? "Aucune réponse"}</small></div>)}
              </details>}
              {(selectedEcu.did_sweep_range || selectedEcu.did_sweep_error) && <div className="did-sweep-panel">
                <div className="section-heading">
                  <div><span className="eyebrow">Recherche approfondie du dernier scan</span><h3>Balayage automatique {selectedEcu.did_sweep_range}</h3></div>
                </div>
                {selectedEcu.did_sweep_error ? (
                  <p className="inline-alert">{selectedEcu.did_sweep_error}</p>
                ) : selectedEcu.did_sweep_hits && selectedEcu.did_sweep_hits.length > 0 ? (
                  <div className="did-sweep-results">
                    <p><strong>{selectedEcu.did_sweep_hits.length}</strong> réponse(s) exploitable(s) trouvée(s) automatiquement.</p>
                    {selectedEcu.did_sweep_hits.map((hit) => (
                      <div className="did-sweep-hit" key={hit.did}>
                        <code>0x{hit.did.toString(16).toUpperCase().padStart(4, "0")}</code>
                        <span>{hit.outcome === "positive" ? "Réponse positive" : `NRC 0x${hit.nrc?.toString(16).toUpperCase().padStart(2, "0")} ${hit.nrc_name ?? ""}`}</span>
                        <small>{hit.raw_hex ?? hit.response_hex ?? "—"}</small>
                        {hit.telecoding && <TelecodingDetails zone={hit.telecoding} />}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="inline-alert">Aucun identifiant supplémentaire trouvé sur cette plage lors du dernier scan.</p>
                )}
              </div>}
              {LAB_MODE && <div className="did-sweep-panel">
                <div className="section-heading">
                  <div><span className="eyebrow">Exploration en lecture seule</span><h3>Balayage de DID (0x22)</h3><p>Envoie une lecture 0x22 pour chaque identifiant de la plage sur {selectedEcu.name}, afin de découvrir ceux réellement supportés au-delà de la liste standard.</p></div>
                </div>
                <div className="did-sweep-form">
                  <label>Début<input value={didSweepStart} onChange={(event) => setDidSweepStart(event.target.value)} placeholder="F180" /></label>
                  <label>Fin<input value={didSweepEnd} onChange={(event) => setDidSweepEnd(event.target.value)} placeholder="F1FF" /></label>
                  <button className="secondary-button" onClick={() => void sweepSelectedEcuDids()} disabled={didSweepBusy}>{didSweepBusy ? "Balayage…" : "Lancer le balayage"}</button>
                </div>
                {didSweepResult && didSweepResult.ecu_key === selectedEcu.key && <div className="did-sweep-results">
                  <p><strong>{didSweepResult.hits.length}</strong> réponse(s) exploitable(s) sur {didSweepResult.scanned_count} identifiant(s) testé(s) · {didSweepResult.unsupported_count} non supporté(s){didSweepResult.timeout_count > 0 && ` · ${didSweepResult.timeout_count} sans réponse`}</p>
                  {didSweepResult.hits.length === 0 ? <p className="inline-alert">Aucun identifiant supplémentaire trouvé dans cette plage.</p> : didSweepResult.hits.map((hit) => (
                    <div className="did-sweep-hit" key={hit.did}>
                      <code>0x{hit.did.toString(16).toUpperCase().padStart(4, "0")}</code>
                      <span>{hit.outcome === "positive" ? "Réponse positive" : `NRC 0x${hit.nrc?.toString(16).toUpperCase().padStart(2, "0")} ${hit.nrc_name ?? ""}`}</span>
                      <small>{hit.raw_hex ?? hit.response_hex ?? "—"}</small>
                      {hit.telecoding && <TelecodingDetails zone={hit.telecoding} />}
                    </div>
                  ))}
                </div>}
              </div>}
            </div>}

            <details className="ecu-inventory-details">
              <summary>Voir l’inventaire complet ({report.ecus.length} calculateurs configurés)</summary>
              <div className="ecu-list">
              {report.ecus.map((ecu) => (
                <article className={`ecu-card ${ecu.detected ? "detected" : ""}`} key={ecu.key}>
                  <div className="ecu-state">
                    <span className={`state-dot ${ecu.detected ? "online" : "offline"}`} />
                    <small>{ecu.detected ? "Détecté" : "Absent"}</small>
                  </div>
                  <div className="ecu-content">
                    <div className="ecu-title-row">
                      <div><h3>{ecu.name}</h3><p>{ecu.family ?? ecu.network}</p></div>
                      <button className="ghost-button" disabled={!ecu.detected} onClick={() => { setSelectedEcuKey(ecu.key); document.querySelector(".ecu-selector")?.scrollIntoView({ behavior: "smooth", block: "center" }); }}>Ouvrir</button>
                    </div>
                    <div className="tag-row">
                      <span>{ecu.optional ? "Optionnel" : "Attendu"}</span>
                      <span>{ecu.confidence}</span>
                      {ecu.dtcs.filter((dtc) => dtc.state === "active").length > 0 && <span className="warn-tag">{ecu.dtcs.filter((dtc) => dtc.state === "active").length} actif(s)</span>}
                      {ecu.dtcs.filter((dtc) => dtc.state === "historical").length > 0 && <span>{ecu.dtcs.filter((dtc) => dtc.state === "historical").length} historique(s)</span>}
                      {ecu.dtcs.filter((dtc) => dtc.state === "not_tested").length > 0 && <span>{ecu.dtcs.filter((dtc) => dtc.state === "not_tested").length} non testé(s)</span>}
                      {ecu.probe_method && <span>Réponse via {ecu.probe_method}</span>}
                      {ecu.active_session !== null && ecu.active_session !== undefined && <span>Session {hexadecimal(ecu.active_session)}</span>}
                    </div>
                    {LAB_MODE && ecu.identification.some((item) => item.error) && <details className="ecu-technical-details">
                      <summary>{ecu.identification.filter((item) => item.error).length} DID refusé(s), absent(s) ou non décodable(s)</summary>
                      {ecu.identification.filter((item) => item.error).map((item) => <div key={item.did}>
                        <code>{item.request_hex ?? `22${item.did.toString(16).toUpperCase()}`}</code>
                        <span>{item.error}</span>
                        <small>{item.response_hex ? `Réponse ${item.response_hex}` : "Aucune réponse"}</small>
                      </div>)}
                    </details>}
                    {LAB_MODE && ecu.probe_attempts && ecu.probe_attempts.length > 0 && <details className="ecu-technical-details">
                      <summary>Preuve de présence et échanges bruts</summary>
                      {ecu.probe_attempts.map((attempt, index) => <div key={`${attempt.request_hex}-${index}`}>
                        <code>{attempt.request_hex}</code>
                        <span>{attempt.outcome === "positive" ? "Réponse positive" : attempt.outcome === "negative_response" ? `NRC ${hexadecimal(attempt.nrc)}` : "Timeout"}</span>
                        <small>{attempt.response_hex ?? attempt.error ?? "Aucune réponse"}</small>
                      </div>)}
                      {ecu.dtc_request_hex && <div><code>{ecu.dtc_request_hex}</code><span>Lecture DTC</span><small>{ecu.dtc_response_hex ?? ecu.dtc_error ?? "Aucune réponse"}</small></div>}
                    </details>}
                    {(ecu.error || ecu.dtc_error) && <p className="inline-alert">{ecu.error ?? ecu.dtc_error}</p>}
                  </div>
                </article>
              ))}
              </div>
            </details>
          </section>
        )}

        {report && <section className="panel dtc-clear-panel">
          <div className="section-heading"><div><span className="eyebrow">Maintenance unitaire contrôlée</span><h2>Effacer la mémoire DTC d’un seul calculateur</h2><p>Le backend lit les défauts avant, exige un acquittement positif, puis relit immédiatement le même ECU.</p></div><span className={`status-pill ${status?.dtc_clear_enabled ? "warning" : "neutral"}`}><i /> {status?.dtc_clear_enabled ? "Armé par configuration" : "Verrouillé"}</span></div>
          <div className="dtc-clear-form">
            <label>Calculateur<select value={dtcClearEcuKey} onChange={(event) => { setDtcClearEcuKey(event.target.value); setDtcClearConfirmation(""); setDtcClearResult(null); }}><option value="">Choisir un ECU</option>{report.ecus.filter((ecu) => ecu.detected).map((ecu) => <option value={ecu.key} key={ecu.key}>{ecu.name} · {ecu.dtcs.length} entrée(s)</option>)}</select></label>
            <div className="dtc-clear-checks">
              <label><input type="checkbox" checked={dtcClearChecks.vehicle_stationary} onChange={(event) => setDtcClearChecks((current) => ({ ...current, vehicle_stationary: event.target.checked }))} /> Véhicule immobilisé</label>
              <label><input type="checkbox" checked={dtcClearChecks.ignition_on_engine_off} onChange={(event) => setDtcClearChecks((current) => ({ ...current, ignition_on_engine_off: event.target.checked }))} /> Contact mis, moteur arrêté</label>
              <label><input type="checkbox" checked={dtcClearChecks.stable_battery_voltage} onChange={(event) => setDtcClearChecks((current) => ({ ...current, stable_battery_voltage: event.target.checked }))} /> Tension batterie stable</label>
              <label><input type="checkbox" checked={dtcClearChecks.report_saved} onChange={(event) => setDtcClearChecks((current) => ({ ...current, report_saved: event.target.checked }))} /> Rapport avant effacement sauvegardé</label>
            </div>
            <label>Confirmation exacte<input value={dtcClearConfirmation} onChange={(event) => setDtcClearConfirmation(event.target.value)} placeholder={dtcClearEcuKey ? `EFFACER ${dtcClearEcuKey.toUpperCase()}` : "Choisir d’abord un ECU"} /></label>
            <button className="danger-button" onClick={() => void clearSelectedEcuDtcs()} disabled={!status?.dtc_clear_enabled || !dtcClearEcuKey || dtcClearConfirmation !== `EFFACER ${dtcClearEcuKey.toUpperCase()}` || !Object.values(dtcClearChecks).every(Boolean) || dtcClearBusy}>{dtcClearBusy ? "Lecture, effacement, contrôle…" : "Effacer cet ECU et vérifier"}</button>
          </div>
          {!status?.dtc_clear_enabled && <p className="inline-alert">Verrou actif : `DTC_CLEAR_ENABLED=false`. Les ECU ABS, BSI, airbag, direction et caméra exigent en plus `SAFETY_ECU_CLEAR_ENABLED=true`.</p>}
          {dtcClearResult && <div className={`regression-result ${dtcClearResult.verified ? "good" : "warning"}`}><strong>{dtcClearResult.verified ? "Effacement contrôlé" : "Effacement accepté, contrôle incomplet"}</strong><span>{dtcClearResult.message}</span><small>{dtcClearResult.before_dtcs.length} avant · {dtcClearResult.after_dtcs.length} après · preuve enregistrée dans le rapport</small>{LAB_MODE && <code>TX {dtcClearResult.request_hex} / RX {dtcClearResult.response_hex ?? "—"}</code>}</div>}
        </section>}
      </div>
    );
  }

  function renderDtcs() {
    const filterLabels: Array<{ key: DtcValue["state"] | "all"; label: string; count: number }> = [
      { key: "active", label: "Actifs", count: report?.dtc_summary.active ?? 0 },
      { key: "historical", label: "Historiques", count: report?.dtc_summary.historical ?? 0 },
      { key: "not_tested", label: "Non testés", count: report?.dtc_summary.not_tested ?? 0 },
      { key: "all", label: "Tous", count: report?.dtc_summary.total ?? 0 },
    ];
    const renderChanges = (changes: DtcChange[], kind: "appeared" | "resolved" | "changed") => changes.map((change) => (
      <article className={`comparison-change ${kind}`} key={`${kind}-${change.ecu_key}-${change.raw_hex}`}>
        <code>{change.code}</code>
        <div>
          <strong>{change.title ?? "Description spécifique inconnue"}</strong>
          <span>{change.ecu_name}</span>
        </div>
        <small>{kind === "appeared"
          ? `Apparu · ${change.after_state ?? "—"}`
          : kind === "resolved"
            ? `Disparu · ${change.before_state ?? "—"}`
            : `${change.before_state ?? "—"} → ${change.after_state ?? "—"}`}</small>
      </article>
    ));
    return (
      <div className="dtc-page">
        <section className="panel diagnostic-history-toolbar">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Historique par véhicule</span>
              <h2>Rapports enregistrés automatiquement</h2>
              <p>Chaque diagnostic est conservé localement sous son VIN, sans mélanger Peugeot et Fiat.</p>
            </div>
            <button className="ghost-button" onClick={() => void refreshDiagnosticHistory(selectedDiagnosticVin || undefined)}>Actualiser</button>
          </div>
          <div className="diagnostic-history-controls">
            <label>Véhicule
              <select value={selectedDiagnosticVin} onChange={(event) => void selectDiagnosticVehicle(event.target.value)}>
                {!diagnosticVehicles.length && <option value="">Aucun VIN enregistré</option>}
                {diagnosticVehicles.map((vehicle) => <option value={vehicle.vin} key={vehicle.vin}>{vehicle.manufacturer} {vehicle.model} · {vehicle.vin}</option>)}
              </select>
            </label>
            <label>Diagnostic
              <select value={report?.scan_id ?? ""} onChange={(event) => void selectDiagnosticReport(event.target.value)} disabled={!diagnosticReportHistory.length}>
                {!diagnosticReportHistory.length && <option value="">Aucun diagnostic</option>}
                {diagnosticReportHistory.map((item) => <option value={item.scan_id} key={item.scan_id}>{formatIsoDate(item.scanned_at)} · {item.dtc_summary.active} actif(s)</option>)}
              </select>
            </label>
            <div className="diagnostic-history-identity">
              <span>VIN sélectionné</span>
              <strong>{selectedDiagnosticVehicle?.vin ?? report?.vin ?? "Non identifié"}</strong>
              <small>{selectedDiagnosticVehicle ? `${selectedDiagnosticVehicle.manufacturer} ${selectedDiagnosticVehicle.model} · ${selectedDiagnosticVehicle.scan_count} scan(s)` : "Lis d’abord l’identité du véhicule"}</small>
            </div>
            <div className="diagnostic-export-actions">
              {report?.scan_id ? <>
                <a className="secondary-button" href={`${API_BASE}/api/diagnostic/reports/${encodeURIComponent(report.scan_id)}/export?format=html`} target="_blank" rel="noreferrer">Rapport HTML</a>
                <a className="ghost-button" href={`${API_BASE}/api/diagnostic/reports/${encodeURIComponent(report.scan_id)}/export?format=json`} target="_blank" rel="noreferrer">JSON brut</a>
              </> : <span>Aucun rapport à exporter</span>}
            </div>
          </div>
        </section>

        {observedDtcs.length > 0 && (
          <section className="panel observed-dtc-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Constat enregistré sur ce véhicule</span>
                <h2>Défauts relevés</h2>
                <p>Ces codes restent visibles après redémarrage, indépendamment d'un nouveau scan.</p>
              </div>
              <span className="candidate-count">{observedDtcs.length} sauvegardés</span>
            </div>
            <div className="dtc-list">
              {observedDtcs.map((dtc) => (
                <article className="dtc-card observed" key={`${dtc.code}-${dtc.ecu_key ?? "unknown"}`}>
                  <div className="dtc-code"><code>{dtc.code}</code><span>{dtc.ecu_name}</span></div>
                  <div className="dtc-description">
                    <strong>{dtc.title ?? "Description spécifique inconnue"}</strong>
                    <p>{dtc.note ?? "Code relevé manuellement; état UDS non fourni."}</p>
                    <div className="tag-row">
                      <span className="warn-tag">À confirmer par lecture UDS</span>
                      <span>Statut UDS inconnu</span>
                      {dtc.catalogs.slice(0, 3).map((catalog) => <span key={catalog}>{catalog}</span>)}
                      {dtc.catalogs.length > 3 && <span>+{dtc.catalogs.length - 3} catalogues</span>}
                    </div>
                  </div>
                  <div className="dtc-meta">
                    <span>Constat local</span>
                    <small>{dtc.recorded_at ? formatDate(new Date(dtc.recorded_at).getTime() * 1000) : "Date inconnue"}</small>
                  </div>
                </article>
              ))}
            </div>
            <p className="inline-alert">Un code seul ne confirme ni que le défaut est actuellement actif, ni sa cause mécanique. Un prochain scan UDS permettra d'ajouter le calculateur, le sous-type et l'état exact.</p>
          </section>
        )}

        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Lecture UDS 0x19</span>
              <h2>Dernier scan des calculateurs</h2>
              {report && <p>{report.manufacturer} {report.model} · {report.vin ?? "VIN non rattaché"} · {formatIsoDate(report.scanned_at)}</p>}
            </div>
            <div className="section-actions">
              <label className="extended-probe-toggle" title="Ajoute un balayage DID sur les calculateurs moteur et télématique (0x0000-0x01FF, identifiants non documentés) ainsi que sur la caméra/CVM et le radar avant (0x2100-0x21FF, zones de télécodage). Rallonge le scan.">
                <input type="checkbox" checked={extendedProbeEnabled} onChange={(event) => setExtendedProbeEnabled(event.target.checked)} /> Recherche approfondie (injection, GPS, caméra, radar)
              </label>
              <span className="locked-label">Effacement verrouillé</span>
              <button className="secondary-button" onClick={scan} disabled={busy || !diagnosticReady}>{busy ? "Scan…" : "Nouveau scan"}</button>
            </div>
          </div>
          {!report ? (
            <EmptyState
              title={diagnosticReady ? "Aucun rapport de scan disponible" : "Diagnostic actif non prêt"}
              text={diagnosticReady
                ? "Lance un scan pour vérifier les défauts présents et récupérer leur état UDS."
                : capture?.active
                  ? "Arrête la capture CAN avant d’interroger les calculateurs."
                  : status?.can_tx_enabled
                    ? "Valide d’abord la connexion ESP32 diagnostic depuis le Dashboard direct."
                    : "La lecture DTC nécessite un firmware diagnostic et des requêtes UDS en lecture seule."}
              action={<button className="primary-button" disabled={!diagnosticReady} onClick={scan}>{diagnosticReady ? "Scanner le véhicule" : "Connexion diagnostic requise"}</button>}
            />
          ) : (
            <>
              <div className="dtc-summary-grid">
                <button className={dtcFilter === "active" ? "active" : ""} onClick={() => setDtcFilter("active")}><span>Défauts actifs</span><strong>{report.dtc_summary.active}</strong><small>À traiter maintenant</small></button>
                <button className={dtcFilter === "historical" ? "active" : ""} onClick={() => setDtcFilter("historical")}><span>Historiques</span><strong>{report.dtc_summary.historical}</strong><small>Mémorisés, non actuels</small></button>
                <button className={dtcFilter === "not_tested" ? "active" : ""} onClick={() => setDtcFilter("not_tested")}><span>Tests non exécutés</span><strong>{report.dtc_summary.not_tested}</strong><small>Pas des pannes confirmées</small></button>
                <div><span>ECU affectés</span><strong>{report.dtc_summary.affected_ecus}</strong><small>{detectedEcus.length}/{report.ecus.length} ECU détectés</small></div>
              </div>
              <div className="dtc-filter-tabs">
                {filterLabels.map((filter) => <button className={dtcFilter === filter.key ? "active" : ""} onClick={() => setDtcFilter(filter.key)} key={filter.key}>{filter.label}<span>{filter.count}</span></button>)}
              </div>
              {dtcFilter === "not_tested" && <p className="dtc-technical-note"><strong>Information technique, pas une panne :</strong> le calculateur indique que le moniteur n’a pas encore terminé ou exécuté son test depuis l’effacement ou le cycle courant.</p>}
              {visibleDtcs.length === 0 ? (
                <EmptyState
                  title={dtcFilter === "active" ? "Aucun défaut actif" : `Aucun élément dans « ${filterLabels.find((item) => item.key === dtcFilter)?.label ?? dtcFilter} »`}
                  text={dtcFilter === "active" ? "Ce scan ne contient aucune panne confirmée comme présente au moment de la lecture." : "Change de filtre pour consulter les autres états UDS."}
                />
              ) : <div className="dtc-list">
                {visibleDtcs.map(({ ecu, dtc }) => {
                  const snapshotKey = `${ecu.key}-${dtc.raw_hex}`;
                  const snapshot = dtcSnapshotResults[snapshotKey];
                  return (
                  <article className={`dtc-card ${dtc.state}`} key={`${ecu.key}-${dtc.raw_hex}-${dtc.status_hex}`}>
                    <div className="dtc-code"><code>{dtc.code}</code><span>{ecu.name}</span></div>
                    <div className="dtc-description">
                      <strong>{dtc.title ?? "Description spécifique inconnue"}</strong>
                      <p>{dtc.state_detail}</p>
                      <div className="tag-row"><span className={`dtc-state-tag ${dtc.state}`}>{dtc.state_label}</span>{dtc.status_labels.map((label) => <span key={label}>{label}</span>)}</div>
                      {LAB_MODE && <>
                        {dtc.failure_type_label && <small>Type de défaut : {dtc.failure_type_label} (0x{dtc.failure_type.toString(16).toUpperCase().padStart(2, "0")})</small>}
                        <button className="ghost-button" onClick={() => void readDtcSnapshot(ecu.key, dtc)} disabled={dtcSnapshotBusy === snapshotKey}>{dtcSnapshotBusy === snapshotKey ? "Lecture…" : "Lire la trame gelée (0x19/0x04)"}</button>
                        {snapshot && (snapshot.error
                          ? <p className="inline-alert">{snapshot.error}</p>
                          : <div className="dtc-snapshot-result">
                              <span>Enregistrement {snapshot.snapshot_record_number ?? "—"} · {snapshot.identifier_count ?? 0} identifiant(s)</span>
                              <code>{snapshot.raw_data_hex || "Aucune donnée"}</code>
                            </div>)}
                      </>}
                    </div>
                    <div className="dtc-meta">
                      <span>{dtc.state_label}</span>
                      {LAB_MODE && <code>Statut 0x{dtc.status_hex}</code>}
                      <small>{dtc.catalogs.join(", ") || "Catalogue inconnu"}</small>
                    </div>
                  </article>
                  );
                })}
              </div>}
            </>
          )}
        </section>

        {report?.comparison && (
          <section className="panel diagnostic-comparison">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Comparaison automatique avant / après</span>
                <h2>Évolution depuis le diagnostic précédent</h2>
                <p>Comparaison limitée aux {report.comparison.comparable_ecus.length} ECU dont la lecture DTC a réussi dans les deux scans.</p>
              </div>
              <span className="candidate-count">{report.comparison.appeared.length + report.comparison.resolved.length + report.comparison.changed.length} changement(s)</span>
            </div>
            {report.comparison.appeared.length + report.comparison.resolved.length + report.comparison.changed.length === 0 ? (
              <EmptyState title="Aucune évolution significative" text={`${report.comparison.unchanged} défaut(s) actif(s) ou historique(s) inchangé(s). Les états « non testé » ne sont pas interprétés comme des pannes.`} />
            ) : <div className="comparison-list">
              {renderChanges(report.comparison.appeared, "appeared")}
              {renderChanges(report.comparison.changed, "changed")}
              {renderChanges(report.comparison.resolved, "resolved")}
            </div>}
            {report.comparison.excluded_ecus.length > 0 && <p className="comparison-coverage">ECU exclus faute de lecture comparable : {report.comparison.excluded_ecus.join(", ")}.</p>}
          </section>
        )}
      </div>
    );
  }

  function candidateLocation(candidate: SignalCandidate) {
    const parts = [hexadecimal(candidate.arbitration_id)];
    if (candidate.dbc_message) parts.push(candidate.dbc_message);
    if (candidate.dbc_signal) parts.push(candidate.dbc_signal);
    if (candidate.byte_index !== null && candidate.byte_index !== undefined) parts.push(`octet ${candidate.byte_index}`);
    if (candidate.bit_index !== null && candidate.bit_index !== undefined) parts.push(`bit ${candidate.bit_index}`);
    return parts.join(" · ");
  }

  function renderDatabase() {
    const documentedDids = report?.ecus.reduce(
      (count, ecu) => count + ecu.identification.filter((item) => !item.error).length,
      0,
    ) ?? 0;
    return (
      <div className="database-page">
        <section className="panel module-contract-panel">
          <div className="section-heading"><div><span className="eyebrow">Référentiel partagé</span><h2>Connaissances OpenDiag</h2><p>Cette base décrit ce que l’outil sait, d’où vient l’information et avec quel niveau de confiance. Elle ne communique jamais directement avec le véhicule.</p></div><span className="status-pill good"><i /> Lecture documentaire</span></div>
          <div className="diagnostic-preflight">
            <div><span>Profils véhicule</span><strong>{vehicleProfiles.length}</strong></div>
            <div><span>ECU observés Peugeot</span><strong>{detectedEcus.length}</strong></div>
            <div><span>PID OBD catalogués</span><strong>{diagnosticSensorCatalog.length}</strong></div>
            <div><span>Capteurs locaux actifs</span><strong>{liveSensorDefinitions.length}</strong></div>
          </div>
        </section>
        <section className="module-card-grid">
          <button onClick={() => setView("ecus")}><span>ECU</span><strong>Calculateurs et identifications</strong><p>{documentedDids} identifiant(s) actuellement lus sur le véhicule actif.</p><small>Adresses · familles · versions · séries</small></button>
          <button onClick={() => void openPassiveSensors()}><span>DATA</span><strong>Registre des capteurs</strong><p>Sources CAN, OBD et définitions locales rattachées au VIN.</p><small>Unité · conversion · confiance · historique</small></button>
          <button onClick={() => setView("dtcs")}><span>DTC</span><strong>Catalogue des défauts</strong><p>{report?.dtc_summary.total ?? 0} entrée(s) dans le dernier scan.</p><small>État · source · description</small></button>
          <button onClick={() => setView("maintenance")}><span>WF</span><strong>Procédures métier</strong><p>{maintenanceCatalog?.service_count ?? 0} capacités classées, exécutables uniquement après validation.</p><small>Applicabilité · risque · maturité</small></button>
        </section>
        <section className="panel knowledge-lifecycle"><div className="section-heading"><div><span className="eyebrow">Cycle obligatoire</span><h2>Découvert → observé → validé → documenté → publié</h2><p>Une corrélation Learn ne devient jamais automatiquement un capteur officiel ni une commande exécutable.</p></div></div></section>
      </div>
    );
  }

  function renderSecurity() {
    const currentMode = operatingMode?.mode ?? (status?.read_only === false ? "maintenance" : "read_only");
    return (
      <div className="security-page">
        <section className="panel operating-mode-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Mode global temporaire</span><h2>Choisir le niveau d’autorisation</h2><p>Le mode limite toutes les opérations du backend. Chaque fonction conserve ensuite ses propres verrous et confirmations.</p></div>
            <span className={`status-pill ${currentMode === "read_only" ? "good" : "bad"}`}><i /> {currentMode === "read_only" ? "Lecture seule" : "Maintenance contrôlée"}</span>
          </div>
          <div className="operating-mode-selector">
            <button className={currentMode === "read_only" ? "selected safe" : ""} onClick={() => void activateReadOnlyMode()} disabled={modeSwitchBusy}>
              <span>MODE 1</span><strong>Lecture seule</strong><p>Identification, paramètres, défauts et Live Data. Aucune opération de maintenance.</p><small>Toujours disponible · retour immédiat</small>
            </button>
            <button className={currentMode === "maintenance" ? "selected maintenance" : ""} onClick={openMaintenanceModeDialog} disabled={modeSwitchBusy || currentMode === "maintenance" || !operatingMode?.maintenance_available}>
              <span>MODE 2</span><strong>Maintenance contrôlée</strong><p>Autorise uniquement les workflows métier déjà activés et validés par leurs propres allowlists.</p><small>{operatingMode?.maintenance_available ? "Préconditions et confirmation requises" : operatingMode?.blockers.join(" · ") || "Vérification du backend…"}</small>
            </button>
          </div>
          {currentMode === "maintenance" && <p className="inline-alert danger-alert"><strong>Mode maintenance armé pour cette session backend.</strong> Reviens en lecture seule dès que l’opération est terminée.</p>}
        </section>
        <section className="panel module-contract-panel security-contract">
          <div className="section-heading"><div><span className="eyebrow">Aucune commande directe</span><h2>Toutes les opérations actives passent par un workflow</h2><p>Le moteur vérifie les conditions, limite la commande à une allowlist nommée, journalise l’échange et contrôle le résultat.</p></div><span className={`status-pill ${status?.read_only ? "good" : "warning"}`}><i /> {status?.read_only ? "Lecture seule" : "Maintenance armée"}</span></div>
          <div className="workflow-chain">
            {[
              ["01", "Demande métier", "Une fonction lisible, jamais un payload UDS"],
              ["02", "Préconditions", "Vitesse, moteur, batterie et environnement"],
              ["03", "Autorisation", "ECU, session, sécurité et firmware compatibles"],
              ["04", "Exécution", "Commande exacte avec temporisation et arrêt"],
              ["05", "Contrôle", "Relecture, comparaison et défauts persistants"],
              ["06", "Rapport", "Trace horodatée rattachée au VIN"],
            ].map(([step, title, text]) => <div key={step}><span>{step}</span><strong>{title}</strong><small>{text}</small></div>)}
          </div>
        </section>
        <section className="security-state-grid">
          <article><span>Émission CAN</span><strong>{status?.can_tx_enabled ? "Autorisée par configuration" : "Bloquée"}</strong><small>Une autorisation générale ne contourne jamais les allowlists.</small></article>
          <article><span>Effacement DTC</span><strong>{status?.dtc_clear_enabled ? "Workflow armé" : "Verrouillé"}</strong><small>Lecture avant, acquittement positif et relecture après.</small></article>
          <article><span>ECU de sécurité</span><strong>{status?.safety_ecu_clear_enabled ? "Autorisation spéciale active" : "Protection renforcée"}</strong><small>ABS, BSI, caméra, airbag et direction.</small></article>
          <article><span>Actionneurs PSA</span><strong>{status?.psa_actuator_enabled ? "Profil laboratoire" : "Indisponibles"}</strong><small>Aucune routine inconnue ou commande arbitraire.</small></article>
        </section>
        {LAB_MODE && <section className="panel lab-entry"><div><span className="eyebrow">Mode laboratoire explicite</span><h2>Outils protocolaires</h2><p>Cette zone reste séparée de l’usage normal et n’est visible qu’avec `lab=1`.</p></div><button className="danger-button" onClick={() => setView("psa")}>Ouvrir le laboratoire PSA</button></section>}
      </div>
    );
  }

  function renderAnalysis() {
    if (!analysis) return null;
    return (
      <section className="analysis-stack">
        <article className="panel analysis-summary">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Rapport sauvegardé</span>
              <h2>Résultats du post-traitement</h2>
            </div>
            <button className="secondary-button" onClick={() => analyzeSession(analysis.session_id)}>
              Recalculer
            </button>
          </div>
          <div className="compact-metrics">
            <div><span>Trames</span><strong>{analysis.total_frames.toLocaleString("fr-FR")}</strong></div>
            <div><span>Identifiants</span><strong>{analysis.unique_ids}</strong></div>
            <div><span>Marqueurs</span><strong>{analysis.marker_count}</strong></div>
            <div><span>Durée</span><strong>{formatDuration(analysis.duration_ms)}</strong></div>
          </div>
          {analysis.opendbc && (
            <div className={`opendbc-strip ${analysis.opendbc.loaded ? "loaded" : "unavailable"}`}>
              <span>OPENDBC</span>
              <div>
                <strong>{analysis.opendbc.database}</strong>
                <small>{analysis.opendbc.loaded ? `${analysis.opendbc.message_count} messages · ${analysis.opendbc.signal_count} signaux` : analysis.opendbc.error}</small>
              </div>
              <div><small>Messages reconnus</small><strong>{analysis.opendbc.observed_message_count}</strong></div>
              <div><small>Trames décodées</small><strong>{analysis.opendbc.decoded_frame_count.toLocaleString("fr-FR")}</strong></div>
              <a href={analysis.opendbc.source_url} target="_blank" rel="noreferrer">Source ↗</a>
            </div>
          )}
          {analysis.warnings.map((warning) => <p className="inline-alert" key={warning}>{warning}</p>)}
        </article>

        {analysis.correlations.map((correlation) => (
          <article className="panel" key={correlation.marker}>
            <div className="section-heading correlation-heading">
              <div>
                <span className="eyebrow">{correlation.occurrences} occurrence(s)</span>
                <h2>{correlation.marker}</h2>
                <p>Fenêtres −{correlation.before_ms} ms / +{correlation.after_ms} ms</p>
              </div>
              <span className="candidate-count">{correlation.candidates.length} hypothèses</span>
            </div>
            {correlation.notes.length > 0 && <p className="notes">{correlation.notes.join(" · ")}</p>}
            {correlation.candidates.length === 0 ? (
              <EmptyState title="Pas de signal assez stable" text="Répète l'action trois fois ou augmente la durée de capture avant et après le marqueur." />
            ) : (
              <div className="candidate-list">
                {correlation.candidates.map((candidate, index) => (
                  <div className="candidate-row" key={`${candidateLocation(candidate)}-${candidate.kind}-${index}`}>
                    <div className="candidate-rank">{String(index + 1).padStart(2, "0")}</div>
                    <div className="candidate-main">
                      <div>
                        <code>{candidateLocation(candidate)}</code>
                        <span className="kind-tag">{candidate.kind === "dbc_signal" ? "signal DBC" : candidate.kind}</span>
                        {candidate.source === "opendbc" && <span className="source-tag">opendbc</span>}
                      </div>
                      <strong>{candidate.before_value} <b>→</b> {candidate.after_value}</strong>
                      <small>{candidate.rationale[0]}</small>
                    </div>
                    <div className="score-box">
                      <span className={`confidence ${candidate.confidence}`}>{candidate.confidence}</span>
                      <strong>{Math.round(candidate.score * 100)}%</strong>
                      <div className="score-track"><i style={{ width: `${candidate.score * 100}%` }} /></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </article>
        ))}

        <article className="panel">
          <div className="section-heading">
            <div><span className="eyebrow">Cartographie passive</span><h2>Inventaire CAN</h2></div>
          </div>
          <div className="inventory-table">
            <div className="inventory-head"><span>ID</span><span>Trames</span><span>Fréquence</span><span>DLC</span><span>Octets variables</span><span>opendbc</span></div>
            {analysis.inventory.map((profile) => (
              <div className="inventory-row" key={`${profile.arbitration_id}-${profile.extended}`}>
                <code>{hexadecimal(profile.arbitration_id)}</code>
                <span>{profile.frame_count.toLocaleString("fr-FR")}</span>
                <span>{profile.frequency_hz.toFixed(1)} Hz</span>
                <span>{Object.entries(profile.dlc_counts).map(([dlc, count]) => `${dlc}×${count}`).join(" · ")}</span>
                <strong>{profile.changing_bytes.length ? profile.changing_bytes.join(", ") : "stables"}</strong>
                <span className={profile.opendbc_message ? "known-message" : "unknown-message"} title={profile.opendbc_signals.join(", ")}>
                  {profile.opendbc_message ?? "inconnu"}
                </span>
              </div>
            ))}
          </div>
        </article>
      </section>
    );
  }

  function renderDiscovery() {
    return (
      <>
        <section className="workflow-grid">
          <article><span>01</span><strong>Enregistrer</strong><p>Capturer le trafic CAN sans commande applicative.</p></article>
          <article><span>02</span><strong>Marquer</strong><p>Placer le marqueur juste avant l'action, toujours avec le même nom.</p></article>
          <article><span>03</span><strong>Analyser</strong><p>Comparer les fenêtres avant/après hors ligne.</p></article>
          <article><span>04</span><strong>Valider</strong><p>Confirmer sur plusieurs sessions avant intégration.</p></article>
        </section>

        <section className="panel trace-import-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Import & analyse hors véhicule</span>
              <h2>Importer une trace Diagbox</h2>
              <p>Reconstitue les échanges, recense les informations lues et isole les services actifs pour revue. Learn n’émet aucune trame vers la voiture.</p>
            </div>
            <label className={`secondary-button file-button ${traceImportBusy ? "disabled" : ""}`}>
              {traceImportBusy ? "Analyse…" : "Choisir une trace"}
              <input type="file" accept=".log,.txt,.csv,.jsonl" disabled={traceImportBusy} onChange={(event) => { void importDiagnosticTrace(event.target.files?.[0]); event.currentTarget.value = ""; }} />
            </label>
          </div>
          {traceImportResult && <div className="trace-import-result">
            <div className="diagnostic-preflight">
              <div><span>Trames CAN</span><strong>{traceImportResult.frame_count}</strong></div>
              <div><span>Échanges reconstruits</span><strong>{traceImportResult.exchange_count}</strong></div>
              <div><span>Informations observées</span><strong>{traceImportResult.observed_dids.length}</strong></div>
              <div><span>Services actifs isolés</span><strong>{traceImportResult.observed_actions.length}</strong></div>
            </div>
            {traceImportResult.observed_actions.length > 0 && <p className="inline-alert">{traceImportResult.observed_actions.length} commande(s) repérée(s), conservée(s) comme preuve non exécutable jusqu’à validation manuelle.</p>}
            <small>Import {traceImportResult.import_id} · {traceImportResult.unparsed_line_count} ligne(s) non interprétée(s)</small>
          </div>}
        </section>

        <section className="discovery-grid">
          <article className="panel capture-panel">
            <div className="section-heading">
              <div><span className="eyebrow">Enregistreur</span><h2>Session annotée</h2></div>
              <span className={`recording-badge ${capture?.active ? "recording" : ""}`}>
                <i /> {capture?.active ? "Enregistrement" : "Arrêté"}
              </span>
            </div>

            {!capture?.active ? (
              <div className="capture-form">
                <label>Nom de l'expérience<input value={captureName} onChange={(event) => setCaptureName(event.target.value)} /></label>
                <label>Objectif / conditions<textarea value={captureNote} onChange={(event) => setCaptureNote(event.target.value)} placeholder="Contact mis, moteur arrêté, aucun autre actionneur…" /></label>
                <label className="gps-capture-option">
                  <input type="checkbox" checked={captureGpsEnabled} onChange={(event) => setCaptureGpsEnabled(event.target.checked)} />
                  <span><strong>Enregistrer le trajet GPS</strong><small>Position du navigateur, synchronisée avec le CAN</small></span>
                </label>
                <button className="primary-button record-button" onClick={() => void startCapture(false)}>Démarrer la capture passive</button>
              </div>
            ) : (
              <>
                <div className="live-capture">
                  <div><span>Session</span><strong>{capture.name || capture.session_id}</strong></div>
                  <div><span>Direct 6/14</span><strong>{(capture.live_frame_count ?? capture.frame_count).toLocaleString("fr-FR")}</strong></div>
                  <div><span>Diagnostic 3/8</span><strong>{(capture.diagnostic_frame_count ?? 0).toLocaleString("fr-FR")}</strong></div>
                  <div><span>Marqueurs</span><strong>{capture.marker_count}</strong></div>
                  <div><span>GPS</span><strong>{captureGpsEnabled
                    ? capture.gps_point_count
                      ? `${capture.gps_point_count.toLocaleString("fr-FR")} pts · ±${Math.round(capture.gps_last_accuracy_m ?? gpsTracking.accuracyM ?? 0)} m`
                      : gpsTracking.state === "requesting" ? "Autorisation…" : gpsTracking.state === "active" ? "Acquisition…" : "Indisponible"
                    : "Désactivé"}</strong></div>
                  <div><span>Mode</span><strong>{capture.dual_can ? liveObdReadOnly ? "6/14 OBD lecture + 3/8 diag" : "6/14 passif + 3/8 diag" : capture.strict_passive === true ? "Passif strict" : capture.strict_passive === false ? "Observation" : "Vérification…"}</strong></div>
                </div>
                {capture.error && <p className="inline-alert danger-alert">{capture.error}</p>}
                {captureGpsEnabled && gpsTracking.message && gpsTracking.state !== "active" && (
                  <p className="inline-alert">GPS : {gpsTracking.message}</p>
                )}
                <div className="marker-editor">
                  <label>Nom du marqueur<input value={markerName} onChange={(event) => setMarkerName(event.target.value)} /></label>
                  <label>Note facultative<input value={markerNote} onChange={(event) => setMarkerNote(event.target.value)} placeholder="Pédale maintenue 2 secondes" /></label>
                  <button className="primary-button" onClick={() => addMarker()}>Marquer maintenant</button>
                </div>
                <div className="preset-grid">
                  {markerPresets.map((preset) => (
                    <button key={preset} onClick={() => addMarker(preset)}>{preset.replaceAll("_", " ")}</button>
                  ))}
                </div>
                <button className="stop-button" onClick={stopCapture}>Arrêter et sauvegarder</button>
              </>
            )}
          </article>

          <article className="panel protocol-panel">
            <div><span className="eyebrow">Protocole conseillé</span><h2>Obtenir une bonne corrélation</h2></div>
            <ol>
              <li><span>1</span><p><strong>Stabilise la voiture</strong> pendant 5 secondes sans toucher aux commandes.</p></li>
              <li><span>2</span><p><strong>Clique sur le marqueur</strong>, puis effectue immédiatement une seule action et maintiens-la 2 s.</p></li>
              <li><span>3</span><p><strong>Répète trois fois</strong> avec exactement le même nom de marqueur.</p></li>
              <li><span>4</span><p><strong>Arrête la capture</strong> puis lance l'analyse hors ligne.</p></li>
            </ol>
            <p className="inline-alert">Une corrélation élevée n'est pas encore une preuve de décodage.</p>
            <div className={`opendbc-source-card ${opendbcCatalog?.source.loaded ? "loaded" : ""}`}>
              <span>BASE EXTERNE</span>
              <strong>{opendbcCatalog?.source.loaded ? "opendbc PSA chargé" : "opendbc indisponible"}</strong>
              <small>
                {opendbcCatalog?.source.loaded
                  ? `${opendbcCatalog.source.message_count} messages · ${opendbcCatalog.source.signal_count} signaux`
                  : "Le mode statistique reste disponible."}
              </small>
              {opendbcCatalog?.source.loaded && <a href={opendbcCatalog.source.source_url} target="_blank" rel="noreferrer">Voir la révision ↗</a>}
            </div>
          </article>
        </section>

        <section className="panel sessions-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Historique local</span><h2>Captures enregistrées</h2></div>
            <button className="ghost-button" onClick={refreshSessions}>Actualiser</button>
          </div>
          {sessions.length === 0 ? (
            <EmptyState title="Aucune capture enregistrée" text="La première session apparaîtra ici après son arrêt." />
          ) : (
            <div className="session-list">
              {sessions.map((session) => (
                <article key={session.session_id}>
                  <div className="session-status"><i className={session.error ? "failed" : ""} /></div>
                  <div className="session-main">
                    <strong>{session.name}</strong>
                    <small>{formatDate(session.started_at_us)} · {formatDuration(session.duration_ms)}</small>
                    <div className="tag-row">
                      {session.markers.slice(0, 4).map((marker) => <span key={marker}>{marker}</span>)}
                    </div>
                  </div>
                <div className="session-stats"><span>{session.frame_count.toLocaleString("fr-FR")} trames</span>{Boolean(session.diagnostic_frame_count) && <span>{session.live_frame_count?.toLocaleString("fr-FR")} live / {session.diagnostic_frame_count?.toLocaleString("fr-FR")} diag</span>}<span>{session.marker_count} marqueurs</span></div>
                  <button
                    className={session.analyzed ? "secondary-button" : "primary-button"}
                    disabled={analysisBusy === session.session_id}
                    onClick={() => analyzeSession(session.session_id, session.analyzed)}
                  >
                    {analysisBusy === session.session_id ? "Analyse…" : session.analyzed ? "Ouvrir" : "Analyser"}
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>

        {renderAnalysis()}
      </>
    );
  }

  if (view === "studio") return renderStudio();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span>OD</span><div><strong>Diagbox++</strong><small>OpenDiag Auto</small></div></div>
        <nav>
          <p>OpenDiag</p>
          <NavButton active={view === "dashboard"} glyph="⌂" label="Accueil" onClick={() => setView("dashboard")} />
          <NavButton active={view === "garage"} glyph="▣" label="Garage" onClick={() => { setError(""); setView("garage"); }} count={diagnosticVehicles.length || undefined} />
          <button className={`nav-disclosure ${openNavModule === "diagnostic" ? "open" : ""}`} onClick={() => setOpenNavModule((open) => open === "diagnostic" ? null : "diagnostic")} aria-expanded={openNavModule === "diagnostic"}><span>▦</span><strong>Diagnostic</strong><b>⌄</b></button>
          {openNavModule === "diagnostic" && <div className="nav-submenu">
            <NavButton active={view === "ecus"} glyph="ECU" label="Calculateurs" onClick={() => { setError(""); setView("ecus"); }} count={report ? detectedEcus.length : undefined} />
            <NavButton active={view === "sensors"} glyph="∿" label="Live Data" onClick={openPassiveSensors} />
            <NavButton active={view === "dtcs"} glyph="!" label="Défauts" onClick={() => setView("dtcs")} count={dtcCount || undefined} />
            <NavButton active={view === "identity"} glyph="VIN" label="Identité" onClick={() => { setError(""); setView("identity"); }} />
          </div>}
          <button className={`nav-disclosure ${openNavModule === "atelier" ? "open" : ""}`} onClick={() => setOpenNavModule((open) => open === "atelier" ? null : "atelier")} aria-expanded={openNavModule === "atelier"}><span>⌁</span><strong>Atelier</strong><b>⌄</b></button>
          {openNavModule === "atelier" && <div className="nav-submenu">
            <NavButton active={view === "injection"} glyph="INJ" label="Moteur / injection" onClick={() => { setError(""); setView("injection"); }} />
            <NavButton active={view === "maintenance"} glyph="WF" label="Procédures métier" onClick={() => { setError(""); setView("maintenance"); }} count={maintenanceCatalog?.service_count} />
            <NavButton active={view === "studio"} glyph="◉" label="Tableaux de bord" onClick={() => setView("studio")} />
          </div>}
          <button className={`nav-disclosure ${openNavModule === "learn" ? "open" : ""}`} onClick={() => setOpenNavModule((open) => open === "learn" ? null : "learn")} aria-expanded={openNavModule === "learn"}><span>◎</span><strong>Learn</strong><b>⌄</b></button>
          {openNavModule === "learn" && <div className="nav-submenu">
            <NavButton active={view === "discovery"} glyph="REC" label="Capturer & corréler" onClick={() => setView("discovery")} />
            <NavButton active={view === "inventory"} glyph="✓" label="Valider les capteurs" onClick={() => { setError(""); setView("inventory"); }} count={validationQueue.length || undefined} />
            <NavButton active={view === "replay"} glyph="▷" label="Replays" onClick={() => setView("replay")} />
          </div>}
          <NavButton active={view === "database"} glyph="DB" label="Database" onClick={() => setView("database")} />
          <NavButton active={view === "security" || view === "psa"} glyph="◆" label="Security & Workflow" onClick={() => setView("security")} />
        </nav>
        <div className="sidebar-footer">
          <div className={`connection-dot ${status ? "connected" : ""}`} />
          <div><strong>{status ? "Backend connecté" : "Backend hors ligne"}</strong><small>{status?.transport ?? API_BASE.replace(/^https?:\/\//, "")}</small></div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">{activeTitle.eyebrow}</span><h1>{activeTitle.title}</h1><p>{activeTitle.description}</p></div>
          <div className="topbar-status">
            {view !== "studio" && <button className="topbar-customize" onClick={() => setView("studio")}>Personnaliser le direct</button>}
            <div className="vehicle-switcher-compact">
              <span>Véhicule actif</span>
              <select aria-label="Véhicule actif" value={selectedDiagnosticVin} disabled={!diagnosticVehicles.length || vehicleSelectionBusy || capture?.active} onChange={(event) => void selectDiagnosticVehicle(event.target.value)}>
                {!diagnosticVehicles.length && <option value="">Aucun VIN chargé</option>}
                {diagnosticVehicles.map((vehicle) => <option value={vehicle.vin} key={vehicle.vin}>{vehicle.manufacturer} {vehicle.model} · {vehicle.vin.slice(-6)}</option>)}
              </select>
              <button aria-label="Ouvrir le garage" title="Ouvrir le garage" onClick={() => setView("garage")}>▣</button>
            </div>
            <button className={`status-pill mode-status-button ${status?.read_only ? "good" : status ? "bad" : "neutral"}`} onClick={() => { setView("security"); if (status?.read_only) openMaintenanceModeDialog(); }}>
              <i /> {status ? (status.read_only ? "Lecture seule · changer" : "Maintenance · gérer") : "État inconnu"}
            </button>
          </div>
        </header>

        <main className="content">
          {error && <div className="global-error"><strong>Opération impossible</strong><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
          {view === "dashboard" && renderDashboard()}
          {view === "garage" && renderGarage()}
          {view === "replay" && renderReplay()}
          {view === "sensors" && renderSensors()}
          {view === "inventory" && renderSensorInventory()}
          {view === "identity" && renderVehicleIdentity()}
          {view === "injection" && renderInjection()}
          {view === "maintenance" && renderMaintenance()}
          {view === "ecus" && renderEcus()}
          {view === "dtcs" && renderDtcs()}
          {view === "discovery" && renderDiscovery()}
          {view === "database" && renderDatabase()}
          {view === "security" && renderSecurity()}
          {view === "psa" && (LAB_MODE ? renderPsaAdvanced() : renderSecurity())}
        </main>
      </div>
      {modeDialogOpen && <div className="sensor-editor-backdrop" role="presentation" onMouseDown={() => !modeSwitchBusy && setModeDialogOpen(false)}>
        <form className="sensor-editor mode-switch-modal" onSubmit={activateMaintenanceMode} onMouseDown={(event) => event.stopPropagation()}>
          <div className="section-heading">
            <div><span className="eyebrow">Security & Workflow</span><h2>Activer la maintenance contrôlée</h2><p>Cette autorisation reste en mémoire uniquement jusqu’au redémarrage du backend ou au retour manuel en lecture seule.</p></div>
            <button type="button" className="ghost-button" onClick={() => setModeDialogOpen(false)} disabled={modeSwitchBusy}>Fermer</button>
          </div>
          <div className="mode-readiness-grid">
            <div className={operatingMode?.can_tx_enabled ? "ready" : "blocked"}><span>Émission CAN</span><strong>{operatingMode?.can_tx_enabled ? "Configurée" : "Désactivée"}</strong></div>
            <div className={operatingMode?.gateway_ready ? "ready" : "blocked"}><span>Passerelle</span><strong>{operatingMode?.gateway_ready ? "Validée" : "Non validée"}</strong></div>
            <div className={selectedDiagnosticVin ? "ready" : "blocked"}><span>Véhicule</span><strong>{selectedDiagnosticVin || "VIN requis"}</strong></div>
          </div>
          {!operatingMode?.maintenance_available && <p className="inline-alert danger-alert">Mode actuellement indisponible : {operatingMode?.blockers.join(" · ") || "état serveur inconnu"}.</p>}
          <div className="mode-preconditions">
            <label><input type="checkbox" checked={modeChecks.vehicle_stationary} onChange={(event) => setModeChecks((current) => ({ ...current, vehicle_stationary: event.target.checked }))} /><span><strong>Véhicule immobilisé</strong><small>Frein de stationnement appliqué</small></span></label>
            <label><input type="checkbox" checked={modeChecks.ignition_on_engine_off} onChange={(event) => setModeChecks((current) => ({ ...current, ignition_on_engine_off: event.target.checked }))} /><span><strong>Contact mis, moteur arrêté</strong><small>Sauf instruction contraire du workflow métier</small></span></label>
            <label><input type="checkbox" checked={modeChecks.stable_battery_voltage} onChange={(event) => setModeChecks((current) => ({ ...current, stable_battery_voltage: event.target.checked }))} /><span><strong>Tension batterie stable</strong><small>Alimentation adaptée aux opérations prévues</small></span></label>
            <label><input type="checkbox" checked={modeChecks.workshop_or_private_site} onChange={(event) => setModeChecks((current) => ({ ...current, workshop_or_private_site: event.target.checked }))} /><span><strong>Atelier ou site privé</strong><small>Aucun usage sur route ouverte</small></span></label>
          </div>
          <label>Confirmation exacte<input value={modeConfirmation} onChange={(event) => setModeConfirmation(event.target.value)} placeholder="ACTIVER MAINTENANCE" /><small>Saisis ACTIVER MAINTENANCE</small></label>
          <p className="inline-alert">Ce changement n’active pas automatiquement l’effacement DTC, SecurityAccess ou les actionneurs. Chaque fonction garde son workflow dédié.</p>
          <div className="sensor-editor-actions">
            <button type="button" className="ghost-button" onClick={() => setModeDialogOpen(false)} disabled={modeSwitchBusy}>Annuler</button>
            <button type="submit" className="danger-button" disabled={modeSwitchBusy || !operatingMode?.maintenance_available || !selectedDiagnosticVin || modeConfirmation !== "ACTIVER MAINTENANCE" || !Object.values(modeChecks).every(Boolean)}>{modeSwitchBusy ? "Armement…" : "Activer la maintenance"}</button>
          </div>
        </form>
      </div>}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
