import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { vehicleSensorCandidates } from "./sensorInventory";
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

type DidValue = {
  did: number;
  name: string;
  codec: string;
  value?: string | number | boolean | null;
  raw_hex?: string | null;
  source?: string | null;
  confidence: string;
  error?: string | null;
};

type DtcValue = {
  code: string;
  raw_hex: string;
  failure_type: number;
  status: number;
  status_hex: string;
  status_labels: string[];
  title?: string | null;
  catalogs: string[];
  source?: string | null;
  confidence: string;
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
  dtc_error?: string | null;
  error?: string | null;
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
  vehicle_profile: string;
  transport: string;
  readonly: boolean;
  ecus: Ecu[];
  warnings: string[];
  debug: DebugSummary;
};

type DiagnosticSensorCatalogEntry = {
  key: string;
  pid: number;
  name: string;
  unit: string;
  group: string;
  description: string;
};

type DiagnosticSensorValue = {
  key: string;
  pid: number;
  name: string;
  value?: number | null;
  unit?: string | null;
  raw_hex?: string | null;
  error?: string | null;
};

type DiagnosticSensorSnapshot = {
  transport: string;
  request_id: number;
  response_id: number;
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
};
type PsaAdvancedCatalog = {
  enabled: boolean;
  security_access_enabled: boolean;
  actuator_enabled: boolean;
  read_only: boolean;
  can_tx_enabled: boolean;
  required_firmware_policy: string;
  wiring: { vehicle_can: string; nac_reference: string; warning: string };
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
  source: "OBD-II" | "CAN direct" | "PSA spécifique";
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
  confidence: "validated" | "dbc_candidate";
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
};

type CaptureStatus = {
  session_id: string;
  active: boolean;
  source: string;
  frame_count: number;
  marker_count: number;
  path: string;
  name: string;
  started_at_us?: number | null;
  strict_passive?: boolean | null;
  error?: string | null;
};

type DiscoverySession = {
  session_id: string;
  name: string;
  source: string;
  started_at_us?: number | null;
  duration_ms: number;
  frame_count: number;
  marker_count: number;
  markers: string[];
  size_bytes: number;
  analyzed: boolean;
  error?: string | null;
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
  steering_angle_deg?: number | null;
  steering_rate_deg_s?: number | null;
  driver_torque?: number | null;
  accelerator_pct?: number | null;
  engine_torque_nm?: number | null;
  current_gear?: number | null;
  target_gear?: number | null;
  gear_shift_active?: boolean | null;
  drivetrain_engaged_state?: number | null;
  longitudinal_accel_ms2?: number | null;
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
  wheel_front_left_kph?: number | null;
  wheel_front_right_kph?: number | null;
  wheel_rear_left_kph?: number | null;
  wheel_rear_right_kph?: number | null;
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
  gps_available: boolean;
  route_method: string;
  steering_zero_offset_deg: number;
  route_bounds: Record<string, number>;
  available_fields: string[];
  field_quality: Record<string, string>;
  warnings: string[];
  events: ReplayEvent[];
  points: ReplaySample[];
};

type RouteGeometry = {
  path: string;
  coordinates: { x: number; y: number }[];
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
};

const replayGaugeCatalog: ReplayGaugeDefinition[] = [
  { key: "speed_kph", label: "Vitesse véhicule", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#62e39a", note: "Vitesse véhicule calculée à partir des roues ABS." },
  { key: "engine_rpm", label: "Régime moteur", unit: "tr/min", minimum: 0, maximum: 6500, color: "#8ce9b4", note: "Régime moteur diffusé par le calculateur moteur." },
  { key: "current_gear", label: "Rapport engagé", unit: "rapport", minimum: 0, maximum: 6, color: "#f2cc60", note: "Rapport réellement engagé diffusé par le calculateur moteur." },
  { key: "target_gear", label: "Rapport cible", unit: "rapport", minimum: 0, maximum: 6, color: "#ffb45f", note: "Rapport demandé pendant la stratégie de changement de vitesse." },
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
  { key: "fuel_liters", label: "Carburant estimé", unit: "L", minimum: 0, maximum: 53, precision: 1, color: "#f2cc60", note: "Quantité estimée par le BSI; valeur à confirmer." },
  { key: "engine_torque_nm", label: "Couple moteur", unit: "Nm", minimum: -100, maximum: 400, color: "#ff8d72", note: "Estimation de couple moteur réel." },
  { key: "accelerator_pct", label: "Accélérateur", unit: "%", minimum: 0, maximum: 100, color: "#62e39a", note: "Position de pédale diffusée par le moteur." },
  { key: "longitudinal_accel_ms2", label: "Accélération longitudinale", unit: "m/s²", minimum: -4, maximum: 4, precision: 2, color: "#72c6ff", note: "Accélération calculée à partir des roues." },
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
  { key: "lane", label: "Aide au maintien de voie", color: "green", icon: "lane", fields: ["lka_active", "lane_departure"], note: "Activation ou alerte de franchissement de ligne." },
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
  "abs", "esp", "oil_pressure", "coolant", "battery", "fuel", "engine", "door", "seatbelt", "lane",
];

const PEUGEOT_308_HANDBOOK_URL = "https://public.servicebox.peugeot.com/APddb/modeles/308n/eGuide_308n_308_ed01-18_dag/pdfs/9999_9999_226_en-GB.pdf";

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
  { id: "studio-capture", kind: "capture", x: 0, y: 7, w: 6, h: 2 },
];

type View = "dashboard" | "studio" | "replay" | "sensors" | "inventory" | "identity" | "injection" | "psa" | "ecus" | "dtcs" | "discovery";

const views: View[] = ["dashboard", "studio", "replay", "sensors", "inventory", "identity", "injection", "psa", "ecus", "dtcs", "discovery"];

function initialView(): View {
  const requested = new URLSearchParams(window.location.search).get("view");
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
    eyebrow: "CAN passif temps réel",
    title: "Capteurs en direct",
    description: "Inventaire global, valeurs décodées et signaux bruts sans aucune émission.",
  },
  inventory: {
    eyebrow: "Couverture véhicule",
    title: "Inventaire des capteurs",
    description: "Ce qui est mesuré, disponible, à tester, à décoder ou absent de cette motorisation.",
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
  psa: {
    eyebrow: "UDS constructeur · laboratoire protégé",
    title: "Diagnostic PSA avancé",
    description: "Zones brutes, seed/key, sessions BSI/NAC et actionneurs nommés avec allowlist matérielle.",
  },
  ecus: {
    eyebrow: "Architecture véhicule",
    title: "Calculateurs",
    description: "Détection, identification UDS et variantes d'équipement.",
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
  if (!replay?.points.length) return { path: "", coordinates: [] };
  const width = 760;
  const height = 470;
  const padding = 52;
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
  return { path, coordinates };
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
  const turnSignalValue = integer("HS2_DAT_MDD_CMD_452.TURN_SIGNAL_STATUS");
  const headlampFaults = [
    logical("HS2_DAT7_BSI_612.DEF_FEU_CROISMNT_D"), logical("HS2_DAT7_BSI_612.DEF_FEU_CROISMNT_G"),
    logical("HS2_DAT7_BSI_612.DEF_FEU_ROUTE_D"), logical("HS2_DAT7_BSI_612.DEF_FEU_ROUTE_G"),
  ];
  const point: ReplaySample = {
    t_ms: 0,
    x_m: 0,
    y_m: 0,
    heading_deg: 0,
    distance_m: 0,
    speed_kph: numeric("HS2_DYN_ABR_38D.VITESSE_VEHICULE_ROUES"),
    engine_rpm: numeric("Dyn_CMM.P000_Com_nEng"),
    steering_angle_deg: snapshot.steering.detected ? snapshot.steering.angle_degrees ?? null : null,
    steering_rate_deg_s: snapshot.steering.detected ? snapshot.steering.rate_degrees_s ?? null : null,
    driver_torque: snapshot.steering.detected ? snapshot.steering.driver_torque ?? null : null,
    accelerator_pct: numeric("Dyn_CMM.P002_Com_rAPP") ?? numeric("Dyn5_CMM.P334_ACCPed_Position") ?? numeric("DRIVER.GAS_PEDAL"),
    engine_torque_nm: numeric("Dyn_CMM.P003_Com_trqActOut"),
    current_gear: integer("Dyn2_CMM.P152_Gearbx_stGear"),
    target_gear: integer("Dyn_V2_BVMP.P283_Com_stGearTrgtPos"),
    gear_shift_active: logical("Dyn_V2_BVMP.P009_Com_bGearShftActv"),
    drivetrain_engaged_state: integer("Dyn_V2_BVMP.P030_Gbx_stDrvTrnEgd"),
    longitudinal_accel_ms2: numeric("HS2_DYN_ABR_38D.ACCEL_LONGI_ROUES"),
    brake_active: logical("Dat_BSI.P013_MainBrake"),
    brake_system_state: integer("Dyn2_FRE.P226_Com_stBrkActv"),
    brake_pressure_raw: numeric("Dyn2_FRE.BRAKE_PRESSURE"),
    turn_signal: turnSignalValue === null ? null : ({ 0: "off", 1: "right", 2: "left", 3: "hazard" } as const)[turnSignalValue as 0 | 1 | 2 | 3] ?? "off",
    low_beam: logical("HS2_DAT7_BSI_612.ETAT_FEUX_CROIST"),
    high_beam: logical("HS2_DAT7_BSI_612.ETAT_FEUX_ROUTE"),
    reverse: logical("Dat_BSI.P103_Com_bRevGear"),
    parking_brake: logical("Dat_BSI.PARKING_BRAKE"),
    driver_door: logical("Dat_BSI.DRIVER_DOOR"),
    passenger_door: logical("Dat_BSI.PASSENGER_DOOR"),
    front_wiper_status: integer("HS2_DAT_MDD_CMD_452.FRONT_WIPER_STATUS"),
    fuel_liters: numeric("HS2_DAT7_BSI_612.INFO_NIV_CARB"),
    oil_temperature_c: numeric("Dat_CMM.P011_Oil_tSwmp"),
    coolant_temperature_c: numeric("Dat_CMM.P005_CEngDst_tSens"),
    intake_air_temperature_c: numeric("Dat_CMM.P158_Air_tAFS"),
    oil_pressure_switch: logical("Dat2_CMM.P278_Oil_stPSwmp"),
    battery_voltage_v: numeric("Dat6_BSI.P418_Com_uBattRaw"),
    battery_temperature_c: numeric("Dat6_BSI.P273_Com_tBatt"),
    battery_charge_pct: numeric("Dat6_BSI.P272_Com_rBattCh"),
    ambient_temperature_c: numeric("Contexte1_5B2.P146_Com_tEnvT"),
    atmospheric_pressure_hpa: numeric("Dat2_CMM.P338_EnvP_p"),
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
    wheel_front_left_kph: numeric("Dyn4_FRE.P263_VehV_VPsvValWhlFrtL"),
    wheel_front_right_kph: numeric("Dyn4_FRE.P264_VehV_VPsvValWhlFrtR"),
    wheel_rear_left_kph: numeric("Dyn4_FRE.P265_VehV_VPsvValWhlBckL"),
    wheel_rear_right_kph: numeric("Dyn4_FRE.P266_VehV_VPsvValWhlBckR"),
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
      return { available, active: Boolean(point.lka_active || point.lane_departure), detail: point.lane_departure ? `Alerte ligne brute ${point.lane_departure}` : point.lka_active ? "Aide demandée" : "Veille" };
    case "reverse":
      return { available, active: Boolean(point.reverse), detail: point.reverse ? "Rapport arrière" : "Inactive" };
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
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState("");
  const [transportCatalog, setTransportCatalog] = useState<TransportCatalog | null>(null);
  const [selectedTransportId, setSelectedTransportId] = useState("");
  const [transportConnectBusy, setTransportConnectBusy] = useState(false);
  const [transportMessage, setTransportMessage] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [observedDtcs, setObservedDtcs] = useState<ObservedDtc[]>([]);
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
  const [psaCatalog, setPsaCatalog] = useState<PsaAdvancedCatalog | null>(null);
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
  const [powertrainProfile, setPowertrainProfile] = useState<PowertrainProfile>(() => {
    const saved = window.localStorage.getItem("opendiag.powertrain-profile");
    return saved === "gasoline" || saved === "diesel" ? saved : "unknown";
  });
  const [inventorySearch, setInventorySearch] = useState("");
  const [inventorySystem, setInventorySystem] = useState("Tous");
  const [inventoryStatus, setInventoryStatus] = useState<"all" | "available" | "missing" | "excluded">("all");
  const [inventoryPriorityOnly, setInventoryPriorityOnly] = useState(false);
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
  const [detectionEndsAt, setDetectionEndsAt] = useState<number | null>(null);
  const [detectionRemaining, setDetectionRemaining] = useState(0);
  const [detectionBusy, setDetectionBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [capture, setCapture] = useState<CaptureStatus | null>(null);
  const [captureName, setCaptureName] = useState("Découverte 308 T9");
  const [captureNote, setCaptureNote] = useState("");
  const [markerName, setMarkerName] = useState("frein_appuye");
  const [markerNote, setMarkerNote] = useState("");
  const [sessions, setSessions] = useState<DiscoverySession[]>([]);
  const [analysis, setAnalysis] = useState<BehavioralAnalysis | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState("");
  const [opendbcCatalog, setOpendbcCatalog] = useState<OpendbcCatalog | null>(null);
  const [replay, setReplay] = useState<ReplayData | null>(null);
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

  useEffect(() => {
    api<Status>("/api/system/status")
      .then((payload) => {
        setStatus(payload);
        setStatusError("");
      })
      .catch((err) => setStatusError(err instanceof Error ? err.message : String(err)));
    refreshCapture();
    refreshTransportCatalog();
    refreshPassiveSensors();
    refreshSessions();
    api<ObservedDtc[]>("/api/diagnostic/dtcs/observed")
      .then(setObservedDtcs)
      .catch(() => setObservedDtcs([]));
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
    if (!capture?.active) return;
    const timer = window.setInterval(refreshCapture, 800);
    return () => window.clearInterval(timer);
  }, [capture?.active]);

  useEffect(() => {
    if (!["sensors", "ecus", "studio"].includes(view) || !capture?.active) return;
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
    void loadReplay(sessions[0].session_id);
  }, [view, sessions, replaySessionId, replayBusy]);

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
    window.localStorage.setItem("opendiag.identity-profile", identityProfileKey);
  }, [identityProfileKey]);

  useEffect(() => () => studioInteractionCleanup.current?.(), []);

  const detectedEcus = report?.ecus.filter((ecu) => ecu.detected) ?? [];
  const dtcs = useMemo(
    () => report?.ecus.flatMap((ecu) => ecu.dtcs.map((dtc) => ({ ecu, dtc }))) ?? [],
    [report],
  );
  const dtcCount = new Set([
    ...dtcs.map(({ dtc }) => dtc.code),
    ...observedDtcs.map((dtc) => dtc.code),
  ]).size;
  const activeTitle = viewTitles[view];
  const diagnosticGatewayVerified = status?.transport === "virtual" || Boolean(status?.gateway_verified);
  const diagnosticReady = Boolean(status?.can_tx_enabled && diagnosticGatewayVerified && !capture?.active);
  const selectedIdentityProfile = vehicleProfiles.find((profile) => profile.key === identityProfileKey) ?? null;
  const selectedPsaEcu = psaCatalog?.ecus.find((ecu) => ecu.key === psaEcuKey) ?? null;
  const selectedPsaAction = psaCatalog?.actions.find((action) => action.key === psaSelectedActionKey) ?? null;
  const psaLabChecksComplete = Object.values(psaLabChecks).every(Boolean);
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
  const studioLiveSample = useMemo(
    () => passiveSensors ? passiveSnapshotToReplaySample(passiveSensors) : null,
    [passiveSensors],
  );
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
    const advancedRows: SensorInventoryRow[] = vehicleSensorCandidates.map((candidate) => {
      const applicability = candidate.applicability ?? "all";
      const excluded = powertrainProfile !== "unknown" && applicability !== "all" && applicability !== powertrainProfile;
      let status: SensorInventoryStatus = excluded ? "not_applicable" : candidate.source === "psa" ? "to_decode" : "to_observe";
      let value: string | null = null;
      if (!excluded && candidate.source === "can") {
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
        source: candidate.source === "can" ? "CAN direct" : "PSA spécifique",
        status,
        statusLabel: statusLabels[status],
        priority: candidate.priority,
        optional: Boolean(candidate.optional),
        value,
        reference: candidate.source === "can" ? candidate.liveFields?.join(" · ") : "DID ou trame constructeur à identifier",
      };
    });
    const criticalObdKeys = new Set([
      "engine_rpm", "coolant_temperature", "fuel_pressure", "intake_manifold_pressure", "maf",
      "fuel_rail_gauge_pressure", "absolute_fuel_rail_pressure", "fuel_rate", "control_module_voltage",
    ]);
    const obdRows: SensorInventoryRow[] = diagnosticSensorCatalog.map((sensor) => {
      const value = injectionValues.get(sensor.key);
      const supported = Boolean(injectionSnapshot?.supported_pids.includes(sensor.pid));
      let status: SensorInventoryStatus = "to_test";
      if (injectionSnapshot) status = supported ? value?.error ? "supported" : typeof value?.value === "number" ? "measured" : "supported" : "unsupported";
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
  }, [diagnosticSensorCatalog, injectionSnapshot, injectionValues, powertrainProfile, studioLiveSample]);
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

  async function loadReplay(sessionId: string, force = false) {
    if (!sessionId) return;
    setReplayBusy(true);
    setReplayPlaying(false);
    setReplaySessionId(sessionId);
    setReplayTimeMs(0);
    setError("");
    try {
      const payload = await api<ReplayData>(`/api/learn/replay/${encodeURIComponent(sessionId)}${force ? "?force=true" : ""}`);
      setReplay(payload);
    } catch (err) {
      setReplay(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReplayBusy(false);
    }
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
      const path = cursor > 0
        ? `/api/learn/sensors/passive/updates?since_us=${cursor}`
        : "/api/learn/sensors/passive";
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
    await refreshPassiveSensors();
  }

  async function startFullSensorDetection(openSensors = true) {
    setDetectionBusy(true);
    setError("");
    setSensorCategory("Essentiels");
    setSensorSearch("");
    try {
      const payload = await api<PassiveSensorSnapshot>("/api/learn/sensors/passive/detect", {
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

  async function scan() {
    if (capture?.active) {
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
      const payload = await api<Report>("/api/diagnostic/scan", { method: "POST" });
      setReport(payload);
      setView("ecus");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function readInjectionParameters(destination: View = "injection") {
    if (capture?.active) {
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
    setInjectionBusy(true);
    setError("");
    try {
      const payload = await api<DiagnosticSensorSnapshot>("/api/sensors/snapshot", { method: "POST" });
      setInjectionSnapshot(payload);
      setView(destination);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInjectionBusy(false);
    }
  }

  async function readVehicleIdentity() {
    if (capture?.active) {
      setError("Arrête et sauvegarde la capture CAN avant de lire l’identité du véhicule.");
      return;
    }
    if (!diagnosticReady) {
      setError(status?.can_tx_enabled
        ? "Connecte et valide d’abord l’ESP32 avec le firmware diagnostic en lecture seule."
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
      setView("identity");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIdentityBusy(false);
    }
  }

  async function readPsaDid() {
    if (!diagnosticReady) {
      setError(capture?.active
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
          ...psaLabChecks,
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
          ...psaLabChecks,
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

  async function startCapture() {
    if (transportConnectBusy) return;
    setError("");
    try {
      const payload = await api<CaptureStatus>("/api/learn/capture/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: captureName, note: captureNote || null }),
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
    const playableSessions = sessions.filter((session) => session.frame_count > 0);
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
          {playableSessions.map((session) => (
            <option key={session.session_id} value={session.session_id}>
              {formatDate(session.started_at_us)} · {session.name}
            </option>
          ))}
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

    const point = currentReplayPoint;
    const coordinate = currentRouteGeometry.coordinates[currentReplayIndex] ?? { x: 380, y: 235 };
    const progress = replay.duration_ms ? replayTimeMs / replay.duration_ms : 0;
    const speed = Math.max(0, point.speed_kph ?? 0);
    const rpm = Math.max(0, point.engine_rpm ?? 0);
    const currentGearLabel = point.reverse ? "R" : (point.current_gear ?? 0) > 0 ? String(point.current_gear) : "N";
    const targetGearLabel = point.reverse ? "R" : (point.target_gear ?? 0) > 0 ? String(point.target_gear) : "—";
    const steering = point.steering_angle_deg ?? 0;
    const accelerator = Math.max(0, Math.min(100, point.accelerator_pct ?? 0));
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
    const steeringDirection = Math.abs(steering) < 1 ? "centré" : steering < 0 ? "droite" : "gauche";
    const availableGaugeDefinitions = replayGaugeCatalog.filter((definition) => replay.available_fields.includes(definition.key));
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

    return (
      <div className="replay-page">
        {selector}

        <section className="replay-summary-grid">
          <article><span>Distance reconstruite</span><strong>{replay.distance_km.toFixed(2)} <small>km</small></strong></article>
          <article><span>Vitesse maximale</span><strong>{replay.max_speed_kph.toFixed(1)} <small>km/h</small></strong></article>
          <article><span>Vitesse moyenne roulante</span><strong>{replay.average_moving_speed_kph.toFixed(1)} <small>km/h</small></strong></article>
          <article><span>Début des données</span><strong>{replayDate.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</strong></article>
        </section>

        <section className="replay-hero-grid">
          <article className="panel replay-map-panel">
            <div className="section-heading replay-map-heading">
              <div>
                <span className="eyebrow">Carte de mouvement</span>
                <h2>Trajectoire locale reconstruite</h2>
                <p>Vitesse ABS + angle du volant · origine et orientation arbitraires</p>
              </div>
              <span className="source-badge estimated">GPS absent</span>
            </div>
            <div className="route-map">
              <svg viewBox="0 0 760 470" role="img" aria-label="Trajectoire reconstruite sans position GPS">
                <defs>
                  <pattern id="map-grid" width="30" height="30" patternUnits="userSpaceOnUse">
                    <path d="M 30 0 L 0 0 0 30" className="map-grid-line" fill="none" />
                  </pattern>
                  <filter id="route-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                  </filter>
                </defs>
                <rect width="760" height="470" fill="url(#map-grid)" />
                <path className="france-silhouette" d="M333 36 L409 54 466 91 489 139 527 174 506 221 521 262 478 295 456 352 404 405 357 438 314 405 264 386 231 342 196 319 207 266 184 218 215 174 221 121 273 96 292 55 Z" />
                <path className="france-corsica" d="M529 350 C544 358 548 382 536 401 C525 388 520 367 529 350 Z" />
                <text x="380" y="240" className="map-watermark">FRANCE · POSITION ABSOLUE INDISPONIBLE</text>
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
                <circle cx={currentRouteGeometry.coordinates[0]?.x} cy={currentRouteGeometry.coordinates[0]?.y} r="5" className="route-start" />
                <image
                  href="/peugeot-308-top.png"
                  x={coordinate.x - 26}
                  y={coordinate.y - 26}
                  width="52"
                  height="52"
                  transform={`rotate(${point.heading_deg + 180} ${coordinate.x} ${coordinate.y})`}
                  className="map-car"
                />
                <circle cx={coordinate.x} cy={coordinate.y} r="3" className="map-car-center" />
              </svg>
              <div className="map-readout">
                <span><i className="measured-dot" />Vitesse mesurée <strong>{speed.toFixed(1)} km/h</strong></span>
                <span><i className="estimated-dot" />Cap estimé <strong>{point.heading_deg.toFixed(0)}°</strong></span>
                <span>Distance <strong>{(point.distance_m / 1000).toFixed(2)} km</strong></span>
              </div>
            </div>
          </article>

          <article className="panel vehicle-panel">
            <div className="section-heading">
              <div><span className="eyebrow">État carrosserie</span><h2>Peugeot 308 vue du dessus</h2></div>
              <span className="source-badge candidate">CAN décodé</span>
            </div>
            <div className="vehicle-stage">
              <div className={`headlight-cone left ${point.low_beam || point.high_beam ? "on" : ""} ${point.high_beam ? "high" : ""}`} />
              <div className={`headlight-cone right ${point.low_beam || point.high_beam ? "on" : ""} ${point.high_beam ? "high" : ""}`} />
              <img src="/peugeot-308-top.png" alt="Peugeot 308 vue du dessus" className="vehicle-image" />
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
            <div className="section-heading"><div><span className="eyebrow">Combiné</span><h2>Instruments conducteur</h2></div><span className="source-badge candidate">OpenDBC candidat</span></div>
            <div className="instrument-layout">
              <div className="speed-gauge-wrap">
                <div
                  className="speed-gauge"
                  style={{ background: `conic-gradient(from 225deg, #62e39a 0deg ${speedGaugeAngle}deg, #263039 ${speedGaugeAngle}deg 270deg, transparent 270deg)` }}
                >
                  <div><strong>{Math.round(speed)}</strong><span>km/h</span><small>ABS roues</small></div>
                </div>
              </div>
              <div className="engine-readouts">
                <div><span>Régime moteur</span><strong>{Math.round(rpm).toLocaleString("fr-FR")} <small>tr/min</small></strong><i><b style={{ width: `${Math.min(100, rpm / 6000 * 100)}%` }} /></i></div>
                <div><span>Couple moteur</span><strong>{(point.engine_torque_nm ?? 0).toFixed(0)} <small>Nm</small></strong></div>
                <div><span>Accélération long.</span><strong>{(point.longitudinal_accel_ms2 ?? 0).toFixed(2)} <small>m/s²</small></strong></div>
                <div className={`gear-readout ${point.gear_shift_active ? "shifting" : ""}`}>
                  <span>Rapport engagé</span>
                  <strong>{currentGearLabel}</strong>
                  <div className="gear-scale">
                    {[1, 2, 3, 4, 5, 6].map((gear) => <b key={gear} className={point.current_gear === gear ? "active" : point.target_gear === gear ? "target" : ""}>{gear}</b>)}
                  </div>
                  <small>Cible {targetGearLabel} · {point.gear_shift_active ? "changement en cours" : "rapport stabilisé"}</small>
                </div>
              </div>
              <div className="driver-inputs">
                <div className="steering-wheel-block">
                  <img src="/peugeot-308-gt-steering.png" style={{ transform: `rotate(${Math.max(-540, Math.min(540, -steering))}deg)` }} alt={`Volant Peugeot GT tourné à ${steeringDirection}`} />
                  <strong>{Math.abs(steering).toFixed(1)}°</strong><span>angle volant · {steeringDirection}</span>
                </div>
                <div className="pedal-stack">
                  <div><span>Accélérateur</span><i><b style={{ height: `${accelerator}%` }} /></i><strong>{accelerator.toFixed(0)}%</strong></div>
                  <div className={point.brake_active ? "pressed" : ""}><span>Frein</span><i><b style={{ height: point.brake_active ? "100%" : "0%" }} /></i><strong>{point.brake_active ? "ON" : "OFF"}</strong></div>
                </div>
              </div>
            </div>
          </article>

          <article className="panel adas-panel">
            <div className="section-heading"><div><span className="eyebrow">Aides à la conduite</span><h2>Lecture ADAS</h2></div><span className="source-badge candidate">À confirmer</span></div>
            <div className={`lane-visual departure-${laneDeparture}`}>
              <i className="lane-line left" /><i className="lane-line right" />
              <span className="lane-car">▲</span>
              <b>{point.lane_departure ? "Alerte de ligne" : "Voie stable"}</b>
            </div>
            <div className="adas-state-grid">
              <div><span>Maintien dans la voie</span><strong>État brut {point.lane_assist_status ?? "—"}</strong><small>{point.lka_active ? "Activation demandée" : "Aucune activation LXA"}</small></div>
              <div><span>Régulation longitudinale</span><strong>{point.acc_requested ? "Demandée" : "Inactive"}</strong><small>Mode brut {point.acc_mode ?? "—"} · consigne {point.speed_setpoint_kph ?? 0} km/h</small></div>
              <div><span>Frein conducteur</span><strong className={point.brake_active ? "danger-text" : ""}>{point.brake_active ? "Appuyé" : "Relâché"}</strong><small>État système {point.brake_system_state ?? "—"} · pression brute {point.brake_pressure_raw?.toFixed(0) ?? "—"}</small></div>
              <div><span>Effort au volant</span><strong>{point.driver_torque?.toFixed(0) ?? "—"}</strong><small>Valeur colonne non calibrée en N·m</small></div>
            </div>
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
            Référentiel visuel basé sur les catégories du <a href={PEUGEOT_308_HANDBOOK_URL} target="_blank" rel="noreferrer">manuel officiel Peugeot 308</a>. Un pictogramme gris signifie uniquement que son signal n'est pas présent dans la capture.
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
                {addableGaugeDefinitions.map((definition) => <option key={definition.key} value={definition.key}>{definition.label}</option>)}
              </select>
              <button className="secondary-button" disabled={!replayGaugeToAdd} onClick={addReplayGauge}>Ajouter</button>
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
                  : numericValue === null ? "—" : numericValue.toFixed(definition.precision ?? 0);
                const quality = replay.field_quality[definition.key] ?? "opendbc_candidate";
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
                      <span style={{ color: definition.color }}>{quality.includes("state_only") ? "Contacteur logique" : "Candidat OpenDBC"}</span>
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
                {addableGraphDefinitions.map((definition) => <option key={definition.key} value={definition.key}>{definition.label}</option>)}
              </select>
              <button className="secondary-button" disabled={!replayGraphToAdd} onClick={addReplayGraph}>Ajouter</button>
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
          <span className="source-badge measured">Validé véhicule</span><p>Angle, vitesse de rotation et effort du volant.</p>
          <span className="source-badge candidate">Candidat DBC</span><p>Vitesse, commandes, moteur, freinage et ADAS.</p>
          <span className="source-badge estimated">Estimé</span><p>Position, cap et distance sans GPS.</p>
        </section>
      </div>
    );
  }

  function renderStudio() {
    const point = studioLiveSample?.point ?? null;
    const liveAvailableFields = studioLiveSample?.availableFields ?? [];
    const gaugeDefinitions = replayGaugeCatalog;
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
            <div className="studio-capture-stats"><span>Trames <strong>{(capture?.frame_count ?? 0).toLocaleString("fr-FR")}</strong></span><span>Marqueurs <strong>{capture?.marker_count ?? 0}</strong></span><span>Source <strong>{capture?.source ?? "—"}</strong></span></div>
          </div>
        );
      }
      if (!point) return <div className="studio-widget-empty">Démarre le direct pour recevoir les capteurs CAN.</div>;
      if (widget.kind === "speed") {
        const speed = Math.max(0, point.speed_kph ?? 0);
        const ratio = Math.min(1, speed / 150);
        return (
          <div className="studio-speed-widget">
            <div className="studio-speed-dial" style={{ background: `conic-gradient(from 225deg, #62e39a 0deg ${ratio * 270}deg, #263039 ${ratio * 270}deg 270deg, transparent 270deg)` }}>
              <div><strong>{Math.round(speed)}</strong><span>km/h</span><small>ABS roues</small></div>
            </div>
          </div>
        );
      }
      if (widget.kind === "steering") {
        const steering = point.steering_angle_deg ?? 0;
        const direction = Math.abs(steering) < 1 ? "centré" : steering < 0 ? "droite" : "gauche";
        return (
          <div className="studio-steering-widget">
            <img src="/peugeot-308-gt-steering.png" style={{ transform: `rotate(${Math.max(-540, Math.min(540, -steering))}deg)` }} alt="Volant Peugeot 308 GT" />
            <strong>{Math.abs(steering).toFixed(1)}°</strong><span>{direction}</span>
          </div>
        );
      }
      if (widget.kind === "gear") {
        const label = point.reverse ? "R" : (point.current_gear ?? 0) > 0 ? String(point.current_gear) : "N";
        return (
          <div className={`studio-gear-widget ${point.gear_shift_active ? "shifting" : ""}`}>
            <strong>{label}</strong>
            <div>{[1, 2, 3, 4, 5, 6].map((gear) => <b key={gear} className={point.current_gear === gear ? "active" : point.target_gear === gear ? "target" : ""}>{gear}</b>)}</div>
            <span>Cible {point.target_gear ?? "—"}</span><small>{point.gear_shift_active ? "Changement en cours" : "Rapport stabilisé"}</small>
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
            <img src="/peugeot-308-top.png" alt="Peugeot 308 vue du dessus" />
            <i className={`studio-car-lamp front left ${left ? "on" : ""}`} /><i className={`studio-car-lamp front right ${right ? "on" : ""}`} />
            <i className={`studio-car-lamp rear left ${left ? "on" : ""}`} /><i className={`studio-car-lamp rear right ${right ? "on" : ""}`} />
            <span>{point.low_beam ? "Feux ON" : "Feux OFF"} · {point.turn_signal ?? "off"}</span>
          </div>
        );
      }
      if (widget.kind === "gauge") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key);
        if (!definition) return <div className="studio-widget-empty">Capteur inconnu.</div>;
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const logical = typeof raw === "boolean" ? raw : null;
        const ratio = definition.status ? logical ? 1 : 0 : numeric === null ? 0 : Math.max(0, Math.min(1, (numeric - definition.minimum) / (definition.maximum - definition.minimum)));
        const value = definition.status ? logical === null ? "—" : logical ? "Actif" : "Inactif" : numeric?.toFixed(definition.precision ?? 0) ?? "—";
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
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const logical = typeof raw === "boolean" ? raw : null;
        const value = definition.status
          ? logical === null ? "—" : logical ? "ACTIF" : "INACTIF"
          : numeric?.toFixed(definition.precision ?? 0) ?? "—";
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
          <div className={`studio-live-source ${capture?.active ? "active" : ""}`}>
            <i /><div><strong>{capture?.active ? "CAN DIRECT" : "DIRECT EN ATTENTE"}</strong><small>{capture?.active ? `${(capture.frame_count ?? 0).toLocaleString("fr-FR")} trames · mise à jour 5 Hz` : "Clique sur Enregistrer pour démarrer"}</small></div>
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
              <optgroup label="Jauges">{gaugeDefinitions.map((definition) => <option key={`g-${definition.key}`} value={`gauge:${definition.key}`}>{definition.label}</option>)}</optgroup>
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
    );
  }

  function renderDashboard() {
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
            <strong>{status?.vehicle_profile ?? "Non chargé"}</strong>
            <small>Peugeot 308 T9 · 2018</small>
          </article>
          <article className="metric-card">
            <span className="metric-label">Calculateurs</span>
            <strong>{report ? `${detectedEcus.length} / ${report.ecus.length}` : "—"}</strong>
            <small>{report ? "détectés au dernier scan" : "aucun scan effectué"}</small>
          </article>
          <article className="metric-card">
            <span className="metric-label">Défauts mémorisés</span>
            <strong>{dtcCount || (report ? 0 : "—")}</strong>
            <small>{observedDtcs.length ? `${observedDtcs.length} relevés sauvegardés · effacement verrouillé` : status?.dtc_clear_enabled ? "effacement armé" : "effacement verrouillé"}</small>
          </article>
        </section>

        <section className="dashboard-grid">
          <article className="panel quick-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Opérations</span>
                <h2>Commencer un diagnostic</h2>
              </div>
            </div>
            <button className="operation-card" onClick={diagnosticReady ? scan : () => setView(status?.can_tx_enabled && !diagnosticGatewayVerified ? "studio" : "ecus")} disabled={busy}>
              <span className="operation-icon">SCAN</span>
              <span>
                <strong>{busy ? "Scan en cours…" : diagnosticReady ? "Scanner le véhicule" : capture?.active ? "Arrêter la capture avant le scan" : status?.can_tx_enabled ? "Connecter l’ESP32 diagnostic" : "Découvrir les systèmes"}</strong>
                <small>{diagnosticReady ? "Inventaire ECU, identification et lecture DTC" : status?.can_tx_enabled ? "La poignée de main lecture seule doit être validée" : "Observation passive maintenant · diagnostic actif séparé"}</small>
              </span>
              <b>→</b>
            </button>
            <button className="operation-card" onClick={openPassiveSensors}>
              <span className="operation-icon">LIVE</span>
              <span>
                <strong>Voir les capteurs CAN</strong>
                <small>Volant, freinage, moteur, BSI et ADAS sans émission</small>
              </span>
              <b>→</b>
            </button>
            <button className="operation-card" onClick={() => setView("identity")}>
              <span className="operation-icon">VIN</span>
              <span>
                <strong>Identifier Peugeot ou Fiat</strong>
                <small>VIN, logiciel, calibration, CVN et nom du calculateur en lecture seule</small>
              </span>
              <b>→</b>
            </button>
            <button className="operation-card" onClick={() => setView("inventory")}>
              <span className="operation-icon">COV</span>
              <span>
                <strong>Inventaire des capteurs</strong>
                <small>Mesurés, à tester, à décoder et équipements non applicables</small>
              </span>
              <b>→</b>
            </button>
            <button className="operation-card" onClick={() => setView("injection")}>
              <span className="operation-icon">INJ</span>
              <span>
                <strong>Injection & moteur</strong>
                <small>Pression de rampe, débit d'air, carburant, lambda, EGR et températures</small>
              </span>
              <b>→</b>
            </button>
            <button className="operation-card" onClick={() => setView("replay")}>
              <span className="operation-icon">REPLAY</span>
              <span>
                <strong>Rejouer le trajet</strong>
                <small>Carte, Peugeot animée, instruments et aides à la conduite</small>
              </span>
              <b>→</b>
            </button>
            <button className="operation-card" onClick={() => setView("discovery")}>
              <span className="operation-icon">LEARN</span>
              <span>
                <strong>Mode découverte</strong>
                <small>Capture annotée et corrélation hors ligne</small>
              </span>
              <b>→</b>
            </button>
          </article>

          <article className="panel safety-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Garde-fous</span>
                <h2>État de sécurité</h2>
              </div>
              <span className={`status-pill ${status?.read_only ? "good" : status ? "bad" : "neutral"}`}>
                {status ? (status.read_only ? "Lecture seule" : "Écriture active") : "État inconnu"}
              </span>
            </div>
            <div className="safety-list">
              <div><span>Émission CAN</span><strong>{status?.can_tx_enabled ? "Autorisée" : "Bloquée"}</strong></div>
              <div><span>Effacement DTC</span><strong>{status?.dtc_clear_enabled ? "Armé" : "Verrouillé"}</strong></div>
              <div><span>ECU de sécurité</span><strong>{status?.safety_ecu_clear_enabled ? "Déverrouillés" : "Protégés"}</strong></div>
              <div><span>Traces CAN</span><strong>{status?.trace_can_frames ? "Actives" : "Inactives"}</strong></div>
              <div><span>Liaison ESP32</span><strong>{status?.transport === "esp32_wifi" ? "Wi-Fi privé" : status?.transport ?? "Inconnue"}</strong></div>
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
            <span className={`status-pill ${passiveSensors?.strict_passive ? "good" : "bad"}`}>
              <i /> {passiveSensors?.strict_passive ? "Passif strict · émission impossible" : "Sécurité à vérifier"}
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
              <div className="steering-sources">
                <code>{passiveSensors.steering.angle_source ?? "Angle indisponible"}</code>
                <code>{passiveSensors.steering.torque_source ?? "Couple indisponible"}</code>
              </div>
              {passiveSensors.steering.warning && <p className="inline-alert">{passiveSensors.steering.warning}</p>}
            </>
          ) : (
            <EmptyState title="Volant non observé" text="Démarre une capture passive puis tourne doucement le volant à l'arrêt." />
          )}
        </section>

        <section className="panel passive-sensors-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Écoute CAN · aucune requête</span>
              <h2>Tous les signaux décodés</h2>
              <p>{passiveSensors
                ? `${passiveSensors.decoded_signal_count} signaux live · ${passiveSensors.observed_message_count} messages OpenDBC · ${passiveSensors.frame_count.toLocaleString("fr-FR")} trames`
                : "En attente de la capture"}</p>
            </div>
            <button className="secondary-button" onClick={() => refreshPassiveSensors()}>
              Actualiser
            </button>
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
                      <span>{signal.category}{signal.essential ? " · essentiel" : ""}</span>
                      <strong>{signal.display_name}</strong>
                      <p>{signal.description}</p>
                    </div>
                    <div className="sensor-live-value">
                      <strong>{String(signal.value ?? "—")}</strong>
                      <span>{signal.unit || "sans unité"}</span>
                      {signal.customized && <small>Brut : {String(signal.raw_value ?? "—")} {signal.source_unit ?? ""}</small>}
                    </div>
                    <div className="sensor-live-source">
                      <code>{hexadecimal(signal.arbitration_id)} · {signal.message}.{signal.signal}</code>
                      <span>{signal.confidence === "validated" ? "Validé sur cette 308" : "Définition OpenDBC à confirmer"}</span>
                    </div>
                    <button className="ghost-button" onClick={() => editPassiveSensor(signal)}>
                      {signal.customized ? "Modifier" : "Corriger"}
                    </button>
                  </article>
                ))}
              </div>
              {visiblePassiveSignals.length === 0 && (
                <p className="inline-alert">Aucun signal ne correspond aux filtres.</p>
              )}
              <div className="footer-meta">
                <span>{visiblePassiveSignals.length} affichés</span>
                <span>{passiveSensors.strict_passive ? "Passif strict" : "Mode à vérifier"}</span>
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
                <div><span className="eyebrow">Correction locale persistante</span><h2>{sensorEditor.key}</h2></div>
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
      </div>
    );
  }

  function renderSensorInventory() {
    const applicableTotal = Math.max(1, sensorInventoryRows.length - inventoryCounts.excluded);
    const coveredCount = inventoryCounts.measured + inventoryCounts.supported;
    const coverage = Math.round(coveredCount / applicableTotal * 100);
    const actionFor = (row: SensorInventoryRow) => {
      if (["to_test", "supported"].includes(row.status)) {
        return <button className="ghost-button" disabled={injectionBusy} onClick={() => void readInjectionParameters("inventory")}>{injectionBusy ? "Lecture…" : "Tester OBD"}</button>;
      }
      if (row.status === "to_observe") {
        return <button className="ghost-button" disabled={detectionBusy || detectionRemaining > 0} onClick={() => void startFullSensorDetection(false)}>{detectionRemaining > 0 ? `${detectionRemaining} s` : "Observer CAN"}</button>;
      }
      if (row.status === "to_decode") {
        return <button className="ghost-button" onClick={() => setView("discovery")}>Découvrir</button>;
      }
      if (row.status === "measured") {
        return <button className="ghost-button" onClick={() => setView(row.source === "OBD-II" ? "injection" : "studio")}>Voir</button>;
      }
      return null;
    };

    return (
      <div className="sensor-inventory-page">
        <section className="panel inventory-hero">
          <div className="inventory-hero-copy">
            <span className="eyebrow">Couverture diagnostic de la Peugeot 308</span>
            <h2>{coverage}% des informations applicables couvertes</h2>
            <p>Le classement est recalculé à partir du dernier direct CAN et du dernier relevé OBD-II. Une ligne « à décoder » correspond à une donnée PSA plausible, pas à la preuve que le véhicule possède physiquement ce capteur.</p>
            <div className="inventory-progress"><i style={{ width: `${coverage}%` }} /></div>
          </div>
          <label className="powertrain-selector">
            <span>Motorisation</span>
            <select value={powertrainProfile} onChange={(event) => setPowertrainProfile(event.target.value as PowertrainProfile)}>
              <option value="unknown">Encore inconnue</option>
              <option value="gasoline">Essence THP / PureTech</option>
              <option value="diesel">Diesel BlueHDi</option>
            </select>
            <small>{powertrainProfile === "unknown" ? "FAP, SCR et paramètres essence restent tous visibles." : "Les éléments incompatibles sont classés non applicables."}</small>
          </label>
        </section>

        <section className="inventory-summary-grid">
          <button className={inventoryStatus === "available" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "available" ? "all" : "available")}><i className="measured" /><span>Mesurés</span><strong>{inventoryCounts.measured}</strong><small>Valeur reçue</small></button>
          <button className={inventoryStatus === "missing" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "missing" ? "all" : "missing")}><i className="missing" /><span>À compléter</span><strong>{inventoryCounts.missing}</strong><small>Test ou décodage requis</small></button>
          <button className={inventoryStatus === "excluded" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "excluded" ? "all" : "excluded")}><i className="excluded" /><span>Non applicables</span><strong>{inventoryCounts.excluded}</strong><small>Selon la motorisation</small></button>
          <div><span>Total catalogué</span><strong>{sensorInventoryRows.length}</strong><small>{inventorySystems.length - 1} systèmes</small></div>
        </section>

        <section className="panel inventory-actions-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Actualiser les preuves</span><h2>Tester la couverture réelle</h2><p>Les deux lectures sont séparées : le CAN passif n'émet rien; l'OBD-II envoie des requêtes de lecture au calculateur moteur.</p></div>
          </div>
          <div className="inventory-actions">
            <button className="inventory-action" onClick={() => void startFullSensorDetection(false)} disabled={detectionBusy || detectionRemaining > 0}>
              <span>CAN</span><div><strong>{detectionRemaining > 0 ? `Observation · ${detectionRemaining} s` : "Observer le CAN pendant 30 s"}</strong><small>Recherche les signaux diffusés spontanément</small></div>
            </button>
            <button className="inventory-action" onClick={() => void readInjectionParameters("inventory")} disabled={injectionBusy}>
              <span>OBD</span><div><strong>{injectionBusy ? "Lecture moteur en cours…" : "Tester les PID moteur"}</strong><small>{diagnosticReady ? "ESP32 validé · lecture seule" : "La liaison ESP32 sera vérifiée avant toute requête"}</small></div>
            </button>
            <button className="inventory-action" onClick={() => setView("discovery")}>
              <span>PSA</span><div><strong>Découvrir un paramètre constructeur</strong><small>Capture annotée et corrélation hors ligne</small></div>
            </button>
          </div>
          {powertrainProfile === "unknown" && <p className="inline-alert">Sélectionne la motorisation exacte dès qu'elle est confirmée : cela évitera de compter l'AdBlue, le FAP diesel ou le cliquetis essence comme des manques.</p>}
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
            <span className={`status-pill ${diagnosticReady ? "good" : "neutral"}`}><i /> {diagnosticReady ? "Lecture prête" : capture?.active ? "Capture active" : "ESP32 à valider"}</span>
          </div>

          <div className="identity-launcher">
            <label>Véhicule à identifier
              <select value={identityProfileKey} onChange={(event) => { setIdentityProfileKey(event.target.value); setVehicleIdentity(null); setError(""); }}>
                {vehicleProfiles.map((profile) => <option value={profile.key} key={profile.key}>{profile.manufacturer} {profile.model} · {profile.year ?? "année inconnue"}</option>)}
              </select>
            </label>
            <div className="identity-profile-summary">
              <span>{selectedIdentityProfile?.architecture ?? "Architecture à confirmer"}</span>
              <strong>{selectedIdentityProfile?.platform ?? "Plateforme inconnue"}</strong>
              <small>{selectedIdentityProfile?.identity_scope === "identity_only" ? "Identification seulement" : "Profil diagnostic complet"}</small>
            </div>
            <button className="primary-button" onClick={() => void readVehicleIdentity()} disabled={identityBusy || !diagnosticReady || !selectedIdentityProfile}>
              {identityBusy ? "Lecture du véhicule…" : "Lire VIN + identité"}
            </button>
          </div>

          {!diagnosticReady && <p className="inline-alert">{capture?.active
            ? "Arrête et sauvegarde la capture avant cette lecture active."
            : status?.can_tx_enabled
              ? "Connecte l’ESP32 et vérifie la poignée de main du firmware diagnostic en lecture seule."
              : "CAN_TX_ENABLED doit autoriser les requêtes de lecture; les écritures restent bloquées."}</p>}
          {selectedIdentityProfile?.identity_scope === "identity_only" && <p className="inline-alert fiat-profile-note">Le profil Fiat est volontairement limité au VIN et aux informations OBD normalisées. Donne-moi ensuite l’année, la motorisation et si c’est une 500, 500X ou 500e pour construire le bon inventaire ECU.</p>}
        </section>

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
                    <div><code>{attempt.command_hex}</code><small>{attempt.confidence}</small>{attempt.source && <a href={attempt.source} target="_blank" rel="noreferrer">Source ↗</a>}</div>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel identity-fields-panel">
              <div className="section-heading"><div><span className="eyebrow">Informations complémentaires</span><h2>Logiciel, calibration et ECU</h2><p>{successfulFields.length} champ(s) décodé(s), les refus et absences restent visibles.</p></div></div>
              <div className="identity-field-grid">
                {displayedIdentity.fields.map((field) => (
                  <article className={field.error ? "field-error" : ""} key={field.key}>
                    <span>{field.protocol.toUpperCase()} · {field.command_hex}</span>
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
            <span className={`status-pill ${diagnosticReady ? "good" : "neutral"}`}><i /> {diagnosticReady ? "Prêt" : capture?.active ? "Capture active" : status?.can_tx_enabled ? "ESP32 à valider" : "Verrouillé"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Liaison ESP32</span><strong>{diagnosticGatewayVerified ? "Validée" : "Connexion requise"}</strong></div>
            <div><span>Calculateur interrogé</span><strong>{hexadecimal(injectionSnapshot?.request_id ?? 0x7E0)} → {hexadecimal(injectionSnapshot?.response_id ?? 0x7E8)}</strong></div>
            <div><span>Mode diagnostic</span><strong>OBD-II 01 · lecture seule</strong></div>
            <div><span>Capture CAN</span><strong>{capture?.active ? "À arrêter d'abord" : "Port disponible"}</strong></div>
          </div>
          {diagnosticReady ? (
            <button className="primary-button full-scan-button" onClick={() => void readInjectionParameters()} disabled={injectionBusy}>{injectionBusy ? "Lecture en cours…" : injectionSnapshot ? "Actualiser les paramètres d'injection" : "Lire les paramètres d'injection"}</button>
          ) : (
            <p className="inline-alert">{capture?.active
              ? "Arrête et sauvegarde d’abord la capture : les requêtes OBD et l’enregistrement passif ne partagent pas le port série."
              : status?.can_tx_enabled
                ? "Connecte l’ESP32 dans le Dashboard direct et valide la poignée de main lecture seule."
                : "Le backend est actuellement en écoute passive stricte; les requêtes OBD-II restent bloquées."}</p>
          )}
        </section>

        <section className="injection-summary-grid">
          <article><span>PID catalogués</span><strong>{diagnosticSensorCatalog.length || "—"}</strong><small>Mode 01 normalisé</small></article>
          <article><span>PID supportés</span><strong>{injectionSnapshot ? supportedCatalogCount : "—"}</strong><small>Déclarés par cet ECU</small></article>
          <article><span>Valeurs reçues</span><strong>{injectionSnapshot ? measuredCount : "—"}</strong><small>Dernier relevé</small></article>
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
                    <footer><span>{available ? "Mesuré" : supported ? "Support déclaré" : "Indisponible"}</span>{value?.raw_hex && <code>{value.raw_hex}</code>}</footer>
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
            <article><span>Lecture UDS</span><strong>{diagnosticReady ? "Prête" : "Verrouillée"}</strong><small>Services 0x19 / 0x22 / 0x3E</small></article>
            <article><span>Actionneurs</span><strong>{labRuntimeReady ? "Armables" : "Verrouillés"}</strong><small>0x2F exact · temporisation ≤ 3 s</small></article>
          </div>
          {psaCatalog && <div className="psa-wiring-note"><strong>Réseaux OBD à vérifier avant branchement</strong><span>{psaCatalog.wiring.vehicle_can} · référence NAC : {psaCatalog.wiring.nac_reference}</span><p>{psaCatalog.wiring.warning}</p></div>}
        </section>

        <section className="panel psa-zone-reader">
          <div className="section-heading">
            <div><span className="eyebrow">ReadDataByIdentifier · service 0x22</span><h2>Lire une zone brute BSI, NAC ou ECU</h2><p>Cette lecture accepte un DID PSA non encore catalogué et conserve sa réponse brute dans une trace locale.</p></div>
            <span className={`status-pill ${diagnosticReady ? "good" : "neutral"}`}><i /> {diagnosticReady ? "Lecture autorisée" : "CAN TX lecture requis"}</span>
          </div>
          <div className="psa-zone-form">
            <label>Calculateur<select value={psaEcuKey} onChange={(event) => { setPsaEcuKey(event.target.value); setPsaDidResult(null); }}>{psaCatalog?.ecus.map((ecu) => <option key={ecu.key} value={ecu.key}>{ecu.name}</option>)}</select></label>
            <label>DID hexadécimal<div className="psa-hex-input"><span>0x</span><input value={psaDid} onChange={(event) => setPsaDid(event.target.value.toUpperCase())} maxLength={6} /></div></label>
            <button className="primary-button" onClick={() => void readPsaDid()} disabled={psaBusy === "did" || !diagnosticReady}>{psaBusy === "did" ? "Lecture…" : "Lire la zone"}</button>
          </div>
          <div className="psa-ecu-address"><span>{selectedPsaEcu?.family ?? "Famille inconnue"}</span><code>{hexadecimal(selectedPsaEcu?.request_id)} → {hexadecimal(selectedPsaEcu?.response_id)}</code><small>{selectedPsaEcu?.optional ? "Équipement optionnel" : "Calculateur attendu sur T9"}</small></div>
          {psaDidResult && <div className="psa-zone-result"><div><span>DID 0x{psaDidResult.did.toString(16).toUpperCase().padStart(4, "0")}</span><strong>{String(psaDidResult.value ?? "Réponse vide")}</strong></div><code>{psaDidResult.raw_hex ?? "—"}</code><small>{psaDidResult.codec} · {psaDidResult.confidence}</small></div>}
        </section>

        <section className="psa-two-column">
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
                {action.unavailable_reason && <small>{action.unavailable_reason}</small>}
                <button className="ghost-button" disabled={!action.available} onClick={() => { setPsaSelectedActionKey(action.key); setPsaConfirmation(""); setPsaFeedback(""); }}>{action.available ? "Préparer le test" : "Non disponible"}</button>
              </article>
            ))}
          </div>

          {selectedPsaAction && <div className="psa-action-gate">
            <div><span>Action préparée</span><strong>{selectedPsaAction.name}</strong><code>{selectedPsaAction.start_payload_hex}{selectedPsaAction.stop_payload_hex ? ` → arrêt ${selectedPsaAction.stop_payload_hex}` : ""}</code></div>
            {selectedPsaAction.timed && <label>Durée<input type="number" min={250} max={3000} step={250} value={psaDurationMs} onChange={(event) => setPsaDurationMs(Math.max(250, Math.min(3000, Number(event.target.value))))} /><span>ms</span></label>}
            <label className="psa-confirmation-field">Confirmation exacte<input value={psaConfirmation} onChange={(event) => setPsaConfirmation(event.target.value)} placeholder={selectedPsaAction.confirmation ?? ""} /><small>{selectedPsaAction.confirmation}</small></label>
            <button className="danger-button" onClick={() => void executePsaAction()} disabled={!labRuntimeReady || !psaLabChecksComplete || psaConfirmation !== selectedPsaAction.confirmation || psaBusy === "action"}>{psaBusy === "action" ? "Action en cours…" : "Exécuter puis arrêter"}</button>
          </div>}
        </section>

        <section className="panel psa-security-panel">
          <div className="section-heading"><div><span className="eyebrow">Verrous communs aux actions et à SecurityAccess</span><h2>Armement atelier</h2><p>Ces confirmations sont transmises avec l'opération; elles ne sont pas mémorisées.</p></div></div>
          <div className="psa-safety-checks">
            <label><input type="checkbox" checked={psaLabChecks.vehicle_stationary} onChange={(event) => updateLabCheck("vehicle_stationary", event.target.checked)} /><span>Véhicule immobilisé</span></label>
            <label><input type="checkbox" checked={psaLabChecks.ignition_on_engine_off} onChange={(event) => updateLabCheck("ignition_on_engine_off", event.target.checked)} /><span>Contact mis, moteur arrêté</span></label>
            <label><input type="checkbox" checked={psaLabChecks.stable_battery_voltage} onChange={(event) => updateLabCheck("stable_battery_voltage", event.target.checked)} /><span>Tension batterie stable</span></label>
            <label><input type="checkbox" checked={psaLabChecks.workshop_or_private_site} onChange={(event) => updateLabCheck("workshop_or_private_site", event.target.checked)} /><span>Atelier ou site privé</span></label>
          </div>
          <div className="psa-unlock-row">
            <label>ECU<select value={psaUnlockEcuKey} onChange={(event) => { const key = event.target.value; const ecu = psaCatalog?.ecus.find((candidate) => candidate.key === key); setPsaUnlockEcuKey(key); setPsaUnlockApplicationKey(ecu?.security_keys[0]?.key_hex ?? ""); setPsaUnlockConfirmation(""); }}>{unlockableEcus.map((ecu) => <option value={ecu.key} key={ecu.key}>{ecu.name}</option>)}</select></label>
            <label>Clé<select value={psaUnlockApplicationKey} onChange={(event) => setPsaUnlockApplicationKey(event.target.value)}>{psaUnlockEcu?.security_keys.map((candidate) => <option value={candidate.key_hex} key={candidate.variant}>{candidate.variant} · {candidate.key_hex}</option>)}</select></label>
            <label>Confirmation<input value={psaUnlockConfirmation} onChange={(event) => setPsaUnlockConfirmation(event.target.value)} placeholder={`DEVERROUILLER ${psaUnlockEcuKey.toUpperCase()}`} /></label>
            <button className="danger-button" onClick={() => void unlockPsaConfiguration()} disabled={!psaCatalog?.security_access_enabled || !psaFirmwareReady || !psaLabChecksComplete || psaUnlockConfirmation !== `DEVERROUILLER ${psaUnlockEcuKey.toUpperCase()}` || psaBusy === "unlock"}>{psaBusy === "unlock" ? "Échange seed/key…" : "Déverrouiller sans écrire"}</button>
          </div>
          <p className="inline-alert">SecurityAccess est désactivé par défaut (`PSA_SECURITY_ACCESS_ENABLED=false`). La session est refermée immédiatement et aucune écriture `0x2E`, routine `0x31`, programmation ou effacement n'est autorisé.</p>
        </section>

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
            <button className="secondary-button" onClick={() => startFullSensorDetection(false)} disabled={detectionBusy || detectionRemaining > 0}>
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
              <p>Cette étape envoie des requêtes UDS 0x10/0x19/0x22, sans effacement ni télécodage.</p>
            </div>
            <span className={`status-pill ${diagnosticReady ? "good" : "neutral"}`}><i /> {diagnosticReady ? "Prêt" : capture?.active ? "Capture active" : status?.can_tx_enabled ? "ESP32 à valider" : "Verrouillé"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Liaison ESP32</span><strong>{diagnosticGatewayVerified ? "Poignée de main validée" : "Connexion requise"}</strong></div>
            <div><span>Firmware ESP32</span><strong>{status?.gateway_hello?.diagnostic_read_only === true || status?.transport === "virtual" ? "Lecture seule validée" : status?.can_tx_enabled ? "À confirmer" : "Listen-only"}</strong></div>
            <div><span>Requêtes CAN</span><strong>{status?.can_tx_enabled ? "UDS lecture uniquement" : "Bloquées"}</strong></div>
            <div><span>Effacement / télécodage</span><strong>{status?.dtc_clear_enabled ? "Maintenance armée" : "Toujours interdit"}</strong></div>
          </div>
          {diagnosticReady ? (
            <button className="primary-button full-scan-button" onClick={scan} disabled={busy}>{busy ? "Inventaire en cours…" : "Lancer l'inventaire ECU + DTC"}</button>
          ) : (
            <p className="inline-alert">{capture?.active
              ? "Arrête et sauvegarde d’abord la capture CAN : le port ESP32 doit être libéré pour le scan UDS."
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
                <h2>Inventaire UDS des calculateurs</h2>
              </div>
              <button className="secondary-button" onClick={scan} disabled={busy || !diagnosticReady}>Relancer le scan</button>
            </div>
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
                      <code>{hexadecimal(ecu.request_id)} → {hexadecimal(ecu.response_id)}</code>
                    </div>
                    <div className="tag-row">
                      <span>{ecu.optional ? "Optionnel" : "Attendu"}</span>
                      <span>{ecu.confidence}</span>
                      {ecu.dtcs.length > 0 && <span className="warn-tag">{ecu.dtcs.length} DTC</span>}
                    </div>
                    {ecu.identification.length > 0 && (
                      <div className="did-grid">
                        {ecu.identification.map((item) => (
                          <div key={item.did}>
                            <code>{hexadecimal(item.did)}</code>
                            <span>{item.name}</span>
                            <strong>{item.error ?? String(item.value ?? "—")}</strong>
                          </div>
                        ))}
                      </div>
                    )}
                    {(ecu.error || ecu.dtc_error) && <p className="inline-alert">{ecu.error ?? ecu.dtc_error}</p>}
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}
      </div>
    );
  }

  function renderDtcs() {
    return (
      <div className="dtc-page">
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
                      <span className="warn-tag">Relevé utilisateur</span>
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
            </div>
            <span className="locked-label">Effacement verrouillé</span>
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
          ) : dtcs.length === 0 ? (
            <EmptyState title="Aucun DTC retourné par ce scan" text="Les calculateurs interrogés n'ont remonté aucun défaut dans ce rapport; les constats antérieurs restent séparés au-dessus." />
          ) : (
            <div className="dtc-list">
              {dtcs.map(({ ecu, dtc }) => (
                <article className="dtc-card" key={`${ecu.key}-${dtc.raw_hex}-${dtc.status_hex}`}>
                  <div className="dtc-code"><code>{dtc.code}</code><span>{ecu.name}</span></div>
                  <div className="dtc-description">
                    <strong>{dtc.title ?? "Description spécifique inconnue"}</strong>
                    <p>{dtc.status_labels.length ? dtc.status_labels.join(" · ") : "Aucun indicateur actif"}</p>
                  </div>
                  <div className="dtc-meta">
                    <span>État 0x{dtc.status_hex}</span>
                    <small>{dtc.catalogs.join(", ") || "Catalogue inconnu"}</small>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
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
                <button className="primary-button record-button" onClick={startCapture}>Démarrer la capture</button>
              </div>
            ) : (
              <>
                <div className="live-capture">
                  <div><span>Session</span><strong>{capture.name || capture.session_id}</strong></div>
                  <div><span>Trames</span><strong>{capture.frame_count.toLocaleString("fr-FR")}</strong></div>
                  <div><span>Marqueurs</span><strong>{capture.marker_count}</strong></div>
                  <div><span>Mode</span><strong>{capture.strict_passive === true ? "Passif strict" : capture.strict_passive === false ? "Observation" : "Vérification…"}</strong></div>
                </div>
                {capture.error && <p className="inline-alert danger-alert">{capture.error}</p>}
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
                  <div className="session-stats"><span>{session.frame_count.toLocaleString("fr-FR")} trames</span><span>{session.marker_count} marqueurs</span></div>
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
          <p>Diagnostic</p>
          <NavButton active={view === "dashboard"} glyph="⌂" label="Tableau de bord" onClick={() => setView("dashboard")} />
          <NavButton active={view === "studio"} glyph="✣" label="Dashboard libre" onClick={() => setView("studio")} />
          <NavButton active={view === "replay"} glyph="▷" label="Replay véhicule" onClick={() => setView("replay")} />
          <NavButton active={view === "sensors"} glyph="∿" label="Capteurs live" onClick={openPassiveSensors} />
          <NavButton active={view === "inventory"} glyph="✓" label="Inventaire capteurs" onClick={() => { setError(""); setView("inventory"); }} count={inventoryCounts.missing || undefined} />
          <NavButton active={view === "identity"} glyph="VIN" label="VIN & véhicule" onClick={() => { setError(""); setView("identity"); }} />
          <NavButton active={view === "injection"} glyph="INJ" label="Injection & moteur" onClick={() => { setError(""); setView("injection"); }} />
          <NavButton active={view === "psa"} glyph="PSA" label="Diagnostic PSA avancé" onClick={() => { setError(""); setView("psa"); }} />
          <NavButton active={view === "ecus"} glyph="▦" label="ECU & découverte" onClick={() => { setError(""); setView("ecus"); }} count={report ? detectedEcus.length : undefined} />
          <NavButton active={view === "dtcs"} glyph="!" label="Codes DTC" onClick={() => setView("dtcs")} count={dtcCount || undefined} />
          <p>Laboratoire</p>
          <NavButton active={view === "discovery"} glyph="◎" label="Découverte" onClick={() => setView("discovery")} />
        </nav>
        <div className="sidebar-footer">
          <div className={`connection-dot ${status ? "connected" : ""}`} />
          <div><strong>{status ? "Backend connecté" : "Backend hors ligne"}</strong><small>{status?.transport ?? "127.0.0.1:8000"}</small></div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">{activeTitle.eyebrow}</span><h1>{activeTitle.title}</h1><p>{activeTitle.description}</p></div>
          <div className="topbar-status">
            <span className="vehicle-chip">{view === "identity" && selectedIdentityProfile
              ? <>{selectedIdentityProfile.manufacturer} {selectedIdentityProfile.model} <b>{selectedIdentityProfile.year ?? "?"}</b></>
              : <>308 T9 <b>2018</b></>}</span>
            <span className={`status-pill ${status?.read_only ? "good" : status ? "bad" : "neutral"}`}>
              <i /> {status ? (status.read_only ? "Lecture seule" : "Écriture active") : "État inconnu"}
            </span>
          </div>
        </header>

        <main className="content">
          {error && <div className="global-error"><strong>Opération impossible</strong><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
          {view === "dashboard" && renderDashboard()}
          {view === "replay" && renderReplay()}
          {view === "sensors" && renderSensors()}
          {view === "inventory" && renderSensorInventory()}
          {view === "identity" && renderVehicleIdentity()}
          {view === "injection" && renderInjection()}
          {view === "psa" && renderPsaAdvanced()}
          {view === "ecus" && renderEcus()}
          {view === "dtcs" && renderDtcs()}
          {view === "discovery" && renderDiscovery()}
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
