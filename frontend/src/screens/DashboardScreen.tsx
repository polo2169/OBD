import type { View } from "../navigation";
import type { CaptureStatus, DiagnosticVehicle, Report, Status } from "../types";

type InventoryCounts = {
  measured: number;
  supported: number;
  excluded: number;
};

type DashboardScreenProps = {
  status: Status | null;
  statusError: string;
  activeVehicleLabel: string;
  selectedVehicle: DiagnosticVehicle | null;
  report: Report | null;
  detectedEcuCount: number;
  dtcCount: number;
  observedDtcCount: number;
  capture: CaptureStatus | null;
  validationQueueCount: number;
  diagnosticReady: boolean;
  inventoryRowCount: number;
  inventoryCounts: InventoryCounts;
  formatDuration: (milliseconds: number) => string;
  onNavigate: (view: View) => void;
};

export function DashboardScreen({
  status,
  statusError,
  activeVehicleLabel,
  selectedVehicle,
  report,
  detectedEcuCount,
  dtcCount,
  observedDtcCount,
  capture,
  validationQueueCount,
  diagnosticReady,
  inventoryRowCount,
  inventoryCounts,
  formatDuration,
  onNavigate,
}: DashboardScreenProps) {
  const applicableSensors = Math.max(1, inventoryRowCount - inventoryCounts.excluded);
  const sensorCoverage = Math.round(
    (inventoryCounts.measured + inventoryCounts.supported) / applicableSensors * 100,
  );

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
          <small>{selectedVehicle?.vin ?? "Lis le VIN pour créer le dossier"}</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Calculateurs</span>
          <strong>{report ? `${detectedEcuCount} / ${report.ecus.length}` : "—"}</strong>
          <small>{report ? "détectés au dernier scan" : "aucun scan effectué"}</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Défauts actifs</span>
          <strong>{report ? dtcCount : "—"}</strong>
          <small>{report ? `${report.dtc_summary.historical} historique(s) · ${observedDtcCount} relevé(s) à confirmer` : "aucun scan enregistré"}</small>
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
            <button className="journey-card observe" onClick={() => onNavigate("studio")}>
              <span className="journey-step">01</span>
              <div><small>Sans émission</small><h3>Observer en direct</h3><p>Compose ton cockpit, affiche les capteurs et enregistre un trajet.</p></div>
              <footer><span className={capture?.active ? "live" : ""}>{capture?.active ? "Enregistrement actif" : "Prêt à observer"}</span><b>→</b></footer>
            </button>
            <button className="journey-card validate" onClick={() => onNavigate("inventory")}>
              <span className="journey-step">02</span>
              <div><small>Preuves guidées</small><h3>Valider les capteurs</h3><p>Traite une information à la fois avec la bonne méthode de test.</p></div>
              <footer><span>{sensorCoverage}% couverts · {validationQueueCount} à traiter</span><b>→</b></footer>
            </button>
            <button className="journey-card diagnose" onClick={() => onNavigate("ecus")}>
              <span className="journey-step">03</span>
              <div><small>Lecture seule</small><h3>Diagnostiquer le véhicule</h3><p>Identifie les ECU, lis les défauts et exporte un rapport par VIN.</p></div>
              <footer><span className={diagnosticReady ? "ready" : ""}>{diagnosticReady ? "Liaison diagnostic prête" : "Connexion à vérifier"}</span><b>→</b></footer>
            </button>
          </div>
          <div className="dashboard-personalize">
            <div><strong>Un affichage adapté à ton usage</strong><span>Le dashboard direct reste entièrement déplaçable, redimensionnable et mémorisé.</span></div>
            <button className="secondary-button" onClick={() => onNavigate("studio")}>Personnaliser le direct</button>
          </div>
        </article>

        <article className="panel safety-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Garde-fous</span><h2>État de sécurité</h2></div>
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
            <button className="ghost-button" onClick={() => onNavigate("security")}>Voir le moteur de sécurité</button>
          </div>
          {!status && <p className="inline-alert danger-alert">Le backend n'est pas joignable. Aucune conclusion de sécurité ne doit être déduite.</p>}
        </article>
      </section>

      {report?.debug.session_id && (
        <section className="panel trace-strip">
          <div><span className="eyebrow">Dernière trace</span><strong>{report.debug.session_id}</strong></div>
          <div><span>Durée</span><b>{formatDuration(report.debug.duration_ms)}</b></div>
          <div><span>Événements</span><b>{report.debug.event_count}</b></div>
          <div><span>Ignorés</span><b>{report.debug.dropped_events}</b></div>
        </section>
      )}
    </>
  );
}
