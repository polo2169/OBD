import React, { useEffect, useMemo, useState } from "react";
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

type SensorValue = {
  key: string;
  pid: number;
  name: string;
  value?: number | null;
  unit?: string | null;
  raw_hex?: string | null;
  error?: string | null;
};

type SensorSnapshot = {
  transport: string;
  request_id: number;
  response_id: number;
  supported_pids: number[];
  values: SensorValue[];
  errors: string[];
  debug: DebugSummary;
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

type View = "dashboard" | "sensors" | "ecus" | "dtcs" | "discovery";

const views: View[] = ["dashboard", "sensors", "ecus", "dtcs", "discovery"];

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
  sensors: {
    eyebrow: "OBD-II Mode 01",
    title: "Capteurs en direct",
    description: "Mesures normalisées, valeurs brutes et qualité de lecture.",
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
  const [sensors, setSensors] = useState<SensorSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [sensorBusy, setSensorBusy] = useState(false);
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

  useEffect(() => {
    api<Status>("/api/system/status")
      .then((payload) => {
        setStatus(payload);
        setStatusError("");
      })
      .catch((err) => setStatusError(err instanceof Error ? err.message : String(err)));
    refreshCapture();
    refreshSessions();
    api<OpendbcCatalog>("/api/learn/opendbc/catalog")
      .then(setOpendbcCatalog)
      .catch(() => setOpendbcCatalog(null));
  }, []);

  useEffect(() => {
    if (!capture?.active) return;
    const timer = window.setInterval(refreshCapture, 800);
    return () => window.clearInterval(timer);
  }, [capture?.active]);

  const detectedEcus = report?.ecus.filter((ecu) => ecu.detected) ?? [];
  const dtcs = useMemo(
    () => report?.ecus.flatMap((ecu) => ecu.dtcs.map((dtc) => ({ ecu, dtc }))) ?? [],
    [report],
  );
  const activeTitle = viewTitles[view];

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

  async function readSensors() {
    setSensorBusy(true);
    setError("");
    try {
      setSensors(await api<SensorSnapshot>("/api/sensors/snapshot", { method: "POST" }));
      setView("sensors");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSensorBusy(false);
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
            <strong>{report ? dtcs.length : "—"}</strong>
            <small>{status?.dtc_clear_enabled ? "effacement armé" : "effacement verrouillé"}</small>
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
            <button className="operation-card" onClick={scan} disabled={busy}>
              <span className="operation-icon">SCAN</span>
              <span>
                <strong>{busy ? "Scan en cours…" : "Scanner le véhicule"}</strong>
                <small>Inventaire ECU, identification et lecture DTC</small>
              </span>
              <b>→</b>
            </button>
            <button className="operation-card" onClick={readSensors} disabled={sensorBusy}>
              <span className="operation-icon">LIVE</span>
              <span>
                <strong>{sensorBusy ? "Lecture en cours…" : "Lire les capteurs"}</strong>
                <small>Régime, tension, températures et débit d'air</small>
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
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Mesures normalisées</span>
            <h2>Instantané capteurs</h2>
          </div>
          <button className="primary-button" onClick={readSensors} disabled={sensorBusy}>
            {sensorBusy ? "Lecture…" : "Actualiser"}
          </button>
        </div>
        {!sensors ? (
          <EmptyState
            title="Aucune mesure disponible"
            text="Lance une lecture pour interroger uniquement les PID OBD-II normalisés."
            action={<button className="primary-button" onClick={readSensors}>Lire les capteurs</button>}
          />
        ) : (
          <>
            <div className="sensor-grid">
              {sensors.values.map((sensor) => (
                <article className="sensor-card" key={sensor.key}>
                  <div><span>{sensor.name}</span><small>PID {hexadecimal(sensor.pid)}</small></div>
                  <strong className={sensor.error ? "value-error" : ""}>
                    {sensor.error ?? `${sensor.value ?? "—"} ${sensor.unit ?? ""}`}
                  </strong>
                  <small>{sensor.raw_hex ? `Brut ${sensor.raw_hex}` : "Valeur décodée"}</small>
                </article>
              ))}
            </div>
            <div className="footer-meta">
              <span>{sensors.supported_pids.length} PID annoncés</span>
              <span>{hexadecimal(sensors.request_id)} → {hexadecimal(sensors.response_id)}</span>
              <span>Trace {sensors.debug.session_id ?? "—"}</span>
            </div>
          </>
        )}
      </section>
    );
  }

  function renderEcus() {
    if (!report) {
      return (
        <section className="panel">
          <EmptyState
            title="Aucun inventaire calculateur"
            text="Le scan détecte moteur, ABS, BSI, airbag, caméra, direction assistée et équipements optionnels."
            action={<button className="primary-button" onClick={scan}>Scanner le véhicule</button>}
          />
        </section>
      );
    }
    return (
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">{detectedEcus.length} détectés sur {report.ecus.length}</span>
            <h2>Inventaire des calculateurs</h2>
          </div>
          <button className="secondary-button" onClick={scan} disabled={busy}>Relancer le scan</button>
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
    );
  }

  function renderDtcs() {
    return (
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Lecture UDS 0x19</span>
            <h2>Défauts mémorisés</h2>
          </div>
          <span className="locked-label">Effacement verrouillé</span>
        </div>
        {!report ? (
          <EmptyState
            title="Aucun rapport disponible"
            text="Effectue d'abord un scan pour lire les défauts de chaque calculateur."
            action={<button className="primary-button" onClick={scan}>Scanner le véhicule</button>}
          />
        ) : dtcs.length === 0 ? (
          <EmptyState title="Aucun DTC retourné" text="Les calculateurs interrogés n'ont remonté aucun défaut dans ce rapport." />
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
          <NavButton active={view === "sensors"} glyph="∿" label="Capteurs live" onClick={() => setView("sensors")} />
          <NavButton active={view === "ecus"} glyph="▦" label="Calculateurs" onClick={() => setView("ecus")} count={report ? detectedEcus.length : undefined} />
          <NavButton active={view === "dtcs"} glyph="!" label="Codes DTC" onClick={() => setView("dtcs")} count={report ? dtcs.length : undefined} />
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
