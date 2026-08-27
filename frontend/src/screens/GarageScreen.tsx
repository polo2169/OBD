import { EmptyState } from "../components/ui";
import type {
  CaptureStatus,
  DiagnosticVehicle,
  DiscoverySession,
  Report,
  VehicleTimelineEntry,
} from "../types";
import type { View } from "../navigation";

type GarageEventFilter = "all" | "diagnostic" | "capture" | "maintenance" | "identity";

type GarageScreenProps = {
  vehicleLinkedSessions: DiscoverySession[];
  vehicleTimeline: VehicleTimelineEntry[];
  report: Report | null;
  eventFilter: GarageEventFilter;
  selectedVehicle: DiagnosticVehicle | null;
  diagnosticVehicles: DiagnosticVehicle[];
  sessions: DiscoverySession[];
  selectedVin: string;
  vehicleSelectionBusy: boolean;
  capture: CaptureStatus | null;
  unassignedSessions: DiscoverySession[];
  activeVehicleLabel: string;
  sessionAssignmentBusy: string;
  formatIsoDate: (value?: string | null) => string;
  formatDuration: (milliseconds: number) => string;
  formatDate: (timestampUs?: number | null) => string;
  onSelectReport: (scanId: string) => Promise<void>;
  onLoadReplay: (sessionId: string, force?: boolean) => Promise<void>;
  onSelectIdentityProfile: (profile: string) => void;
  onAddVehicle: () => void;
  onNavigate: (view: View) => void;
  onSelectVehicle: (vin: string) => Promise<void>;
  onFilterChange: (filter: GarageEventFilter) => void;
  onAssignSessions: (sessionIds: string[]) => Promise<void>;
};

export function GarageScreen({
  vehicleLinkedSessions,
  vehicleTimeline,
  report,
  eventFilter,
  selectedVehicle,
  diagnosticVehicles,
  sessions,
  selectedVin,
  vehicleSelectionBusy,
  capture,
  unassignedSessions,
  activeVehicleLabel,
  sessionAssignmentBusy,
  formatIsoDate,
  formatDuration,
  formatDate,
  onSelectReport,
  onLoadReplay,
  onSelectIdentityProfile,
  onAddVehicle,
  onNavigate,
  onSelectVehicle,
  onFilterChange,
  onAssignSessions,
}: GarageScreenProps) {
  const totalCaptureMs = vehicleLinkedSessions.reduce((total, session) => total + session.duration_ms, 0);
  const lastActivity = vehicleTimeline[0];
  const currentHealth = report
    ? report.dtc_summary.active > 0
      ? { label: `${report.dtc_summary.active} défaut(s) actif(s)`, tone: "warning" }
      : { label: "Aucun défaut actif", tone: "good" }
    : { label: "Diagnostic à réaliser", tone: "neutral" };
  const filterOptions: Array<{ key: GarageEventFilter; label: string }> = [
    { key: "all", label: "Tout" },
    { key: "diagnostic", label: "Diagnostics" },
    { key: "capture", label: "Trajets & captures" },
    { key: "maintenance", label: "Entretien" },
    { key: "identity", label: "Identité" },
  ];

  const openTimelineEntry = async (entry: VehicleTimelineEntry) => {
    if (entry.scanId) {
      await onSelectReport(entry.scanId);
      onNavigate("dtcs");
    } else if (entry.sessionId) {
      await onLoadReplay(entry.sessionId);
      onNavigate("replay");
    } else if (entry.kind === "maintenance") {
      onNavigate("maintenance");
    } else {
      if (selectedVehicle) onSelectIdentityProfile(selectedVehicle.vehicle_profile);
      onNavigate("identity");
    }
  };

  return (
    <div className="garage-page">
      {selectedVehicle ? (
        <section className="panel garage-vehicle-hero">
          <div className="garage-vehicle-identity">
            <div className="garage-marque">{selectedVehicle.manufacturer.slice(0, 2).toUpperCase()}</div>
            <div><span className="eyebrow">Véhicule actuellement chargé</span><h2>{selectedVehicle.manufacturer} {selectedVehicle.model}</h2><code>{selectedVehicle.vin}</code></div>
            <span className="status-pill good"><i /> Dossier actif</span>
          </div>
          <div className="garage-health-grid">
            <article><span>État connu</span><strong className={currentHealth.tone}>{currentHealth.label}</strong><small>{report?.scanned_at ? `Scan du ${formatIsoDate(report.scanned_at)}` : "Aucun rapport chargé"}</small></article>
            <article><span>Suivi diagnostic</span><strong>{selectedVehicle.scan_count} rapport(s)</strong><small>Comparaison automatique avant / après</small></article>
            <article><span>Données routières</span><strong>{vehicleLinkedSessions.length} session(s)</strong><small>{formatDuration(totalCaptureMs)} enregistrées</small></article>
            <article><span>Dernière activité</span><strong>{lastActivity ? formatDate(lastActivity.timestampMs * 1000) : "—"}</strong><small>{lastActivity?.title ?? "Dossier récemment créé"}</small></article>
          </div>
          <div className="garage-quick-actions">
            <button className="primary-button" onClick={() => onNavigate("dashboard")}>Voir l’accueil du véhicule</button>
            <button className="secondary-button" onClick={() => onNavigate("maintenance")}>Entretien &amp; réparations</button>
            <button className="secondary-button" onClick={() => onNavigate("ecus")}>Lancer un diagnostic</button>
            <button className="ghost-button" onClick={() => { onSelectIdentityProfile(selectedVehicle.vehicle_profile); onNavigate("identity"); }}>Voir l’identité</button>
          </div>
        </section>
      ) : (
        <section className="panel"><EmptyState title="Aucun véhicule chargé" text="Lis le VIN pour créer un dossier véhicule fiable avant une capture ou un diagnostic." action={<button className="primary-button" onClick={onAddVehicle}>Identifier le véhicule</button>} /></section>
      )}

      <section className="garage-workspace">
        <aside className="panel garage-fleet-panel">
          <div className="section-heading"><div><span className="eyebrow">Garage local</span><h2>{diagnosticVehicles.length} véhicule(s)</h2><p>Un seul dossier est chargé à la fois.</p></div></div>
          <div className="garage-fleet-list">
            {diagnosticVehicles.map((vehicle) => {
              const linked = sessions.filter((session) => session.vin === vehicle.vin).length;
              const active = vehicle.vin === selectedVin;
              return <button className={active ? "active" : ""} disabled={vehicleSelectionBusy || capture?.active} onClick={() => void onSelectVehicle(vehicle.vin)} key={vehicle.vin}>
                <span>{vehicle.manufacturer.slice(0, 2).toUpperCase()}</span>
                <div><strong>{vehicle.manufacturer} {vehicle.model}</strong><code>{vehicle.vin}</code><small>{vehicle.scan_count} diagnostic(s) · {linked} capture(s)</small></div>
                <b>{active ? "CHARGÉ" : "Charger"}</b>
              </button>;
            })}
          </div>
          <button className="garage-add-vehicle" disabled={capture?.active} onClick={onAddVehicle}>＋ Ajouter par lecture VIN</button>
          {capture?.active && <p className="garage-lock-note">Le changement de véhicule est bloqué pendant l’enregistrement en cours.</p>}
        </aside>

        <section className="panel garage-timeline-panel">
          <div className="section-heading garage-timeline-heading">
            <div><span className="eyebrow">Historique consolidé</span><h2>Chronologie du véhicule</h2><p>Diagnostics, captures, entretiens et identité restent séparés des autres VIN.</p></div>
            <div className="garage-filter-tabs">{filterOptions.map((option) => <button className={eventFilter === option.key ? "active" : ""} onClick={() => onFilterChange(option.key)} key={option.key}>{option.label}</button>)}</div>
          </div>
          <div className="vehicle-timeline">
            {vehicleTimeline.map((entry) => <button className={`timeline-entry ${entry.kind} ${entry.severity ?? "neutral"}`} onClick={() => void openTimelineEntry(entry)} key={entry.id}>
              <time>{formatDate(entry.timestampMs * 1000)}</time>
              <i><span>{entry.kind === "diagnostic" ? "DTC" : entry.kind === "capture" ? "CAN" : entry.kind === "maintenance" ? "ENT" : "VIN"}</span></i>
              <div><strong>{entry.title}</strong><p>{entry.description}</p></div><span>{entry.badge}</span><b>→</b>
            </button>)}
            {!vehicleTimeline.length && <EmptyState title="Aucun événement dans cette vue" text="Change le filtre ou réalise une première opération sur le véhicule chargé." />}
          </div>
        </section>
      </section>

      {unassignedSessions.length > 0 && selectedVehicle && <section className="panel unassigned-sessions-panel">
        <div className="section-heading">
          <div><span className="eyebrow">À classer</span><h2>{unassignedSessions.length} ancienne(s) capture(s) sans VIN</h2><p>Les données ne sont jamais attribuées silencieusement. Confirme celles qui appartiennent à {activeVehicleLabel}.</p></div>
          <button className="secondary-button" disabled={Boolean(sessionAssignmentBusy)} onClick={() => {
            if (window.confirm(`Associer les ${unassignedSessions.length} captures sans VIN à ${activeVehicleLabel} ?`)) void onAssignSessions(unassignedSessions.map((session) => session.session_id));
          }}>{sessionAssignmentBusy === "bulk" ? "Classement…" : "Tout associer au véhicule actif"}</button>
        </div>
        <div className="unassigned-session-list">
          {unassignedSessions.slice(0, 8).map((session) => <article key={session.session_id}>
            <div><strong>{session.name}</strong><small>{formatDate(session.started_at_us)} · {session.frame_count.toLocaleString("fr-FR")} trames</small></div>
            <button className="ghost-button" disabled={Boolean(sessionAssignmentBusy)} onClick={() => void onAssignSessions([session.session_id])}>{sessionAssignmentBusy === session.session_id ? "Association…" : "Associer"}</button>
          </article>)}
          {unassignedSessions.length > 8 && <small>+ {unassignedSessions.length - 8} autres captures disponibles pour le classement global.</small>}
        </div>
      </section>}
    </div>
  );
}
