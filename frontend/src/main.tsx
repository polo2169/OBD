import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

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
  vehicle_profile: string;
  gateway_endpoint?: string | null;
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

type View = "dashboard" | "replay" | "sensors" | "ecus" | "dtcs" | "discovery";

const views: View[] = ["dashboard", "replay", "sensors", "ecus", "dtcs", "discovery"];

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
  const [report, setReport] = useState<Report | null>(null);
  const [observedDtcs, setObservedDtcs] = useState<ObservedDtc[]>([]);
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

  useEffect(() => {
    api<Status>("/api/system/status")
      .then((payload) => {
        setStatus(payload);
        setStatusError("");
      })
      .catch((err) => setStatusError(err instanceof Error ? err.message : String(err)));
    refreshCapture();
    refreshPassiveSensors();
    refreshSessions();
    api<ObservedDtc[]>("/api/diagnostic/dtcs/observed")
      .then(setObservedDtcs)
      .catch(() => setObservedDtcs([]));
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
    if (!["sensors", "ecus"].includes(view) || !capture?.active) return;
    const timer = window.setInterval(refreshPassiveSensors, 200);
    return () => window.clearInterval(timer);
  }, [view, capture?.active]);

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
  const currentRouteGeometry = useMemo(() => routeGeometry(replay), [replay]);

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

  async function startCapture() {
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
              </div>
              <div className="driver-inputs">
                <div className="steering-wheel-block">
                  <svg viewBox="0 0 120 120" style={{ transform: `rotate(${Math.max(-540, Math.min(540, -steering))}deg)` }} aria-label={`Volant tourné à ${steeringDirection}`}>
                    <circle cx="60" cy="60" r="48" />
                    <circle cx="60" cy="60" r="16" />
                    <path d="M60 44V14 M48 65L19 82 M72 65L101 82" />
                  </svg>
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
            <button className="operation-card" onClick={status?.can_tx_enabled ? scan : () => setView("ecus")} disabled={busy}>
              <span className="operation-icon">SCAN</span>
              <span>
                <strong>{busy ? "Scan en cours…" : status?.can_tx_enabled ? "Scanner le véhicule" : "Découvrir les systèmes"}</strong>
                <small>{status?.can_tx_enabled ? "Inventaire ECU, identification et lecture DTC" : "Observation passive maintenant · diagnostic actif séparé"}</small>
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
            <span className={`status-pill ${status?.can_tx_enabled ? "good" : "neutral"}`}><i /> {status?.can_tx_enabled ? "Prêt" : "Verrouillé"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Firmware ESP32</span><strong>{status?.can_tx_enabled ? "Diagnostic autorisé" : "Listen-only"}</strong></div>
            <div><span>Émission CAN</span><strong>{status?.can_tx_enabled ? "Requêtes de lecture" : "Bloquée"}</strong></div>
            <div><span>Effacement DTC</span><strong>{status?.dtc_clear_enabled ? "Autorisé" : "Toujours verrouillé"}</strong></div>
            <div><span>Écriture / télécodage</span><strong>Interdit</strong></div>
          </div>
          {status?.can_tx_enabled ? (
            <button className="primary-button full-scan-button" onClick={scan} disabled={busy}>{busy ? "Inventaire en cours…" : "Lancer l'inventaire ECU + DTC"}</button>
          ) : (
            <p className="inline-alert">Pour identifier réellement moteur, ABS, BSI, airbag, caméra, direction et lire leurs DTC, il faudra charger un firmware diagnostic séparé. Je garderai uniquement les services de lecture et demanderai ta confirmation avant le flash.</p>
          )}
        </section>

        {report && (
          <section className="panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">{detectedEcus.length} détectés sur {report.ecus.length}</span>
                <h2>Inventaire UDS des calculateurs</h2>
              </div>
              <button className="secondary-button" onClick={scan} disabled={busy || !status?.can_tx_enabled}>Relancer le scan</button>
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
              title={status?.can_tx_enabled ? "Aucun rapport de scan disponible" : "Lecture des défauts verrouillée en mode passif"}
              text={status?.can_tx_enabled
                ? "Les défauts constatés ci-dessus sont sauvegardés. Lance un scan pour vérifier lesquels sont encore présents et récupérer leur état UDS."
                : "La lecture DTC nécessite d'envoyer une requête UDS. Les codes relevés restent néanmoins enregistrés ci-dessus."}
              action={<button className="primary-button" disabled={!status?.can_tx_enabled} onClick={scan}>{status?.can_tx_enabled ? "Scanner le véhicule" : "Firmware diagnostic requis"}</button>}
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

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span>OD</span><div><strong>Diagbox++</strong><small>OpenDiag PSA</small></div></div>
        <nav>
          <p>Diagnostic</p>
          <NavButton active={view === "dashboard"} glyph="⌂" label="Tableau de bord" onClick={() => setView("dashboard")} />
          <NavButton active={view === "replay"} glyph="▷" label="Replay véhicule" onClick={() => setView("replay")} />
          <NavButton active={view === "sensors"} glyph="∿" label="Capteurs live" onClick={openPassiveSensors} />
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
            <span className="vehicle-chip">308 T9 <b>2018</b></span>
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
          {view === "ecus" && renderEcus()}
          {view === "dtcs" && renderDtcs()}
          {view === "discovery" && renderDiscovery()}
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
