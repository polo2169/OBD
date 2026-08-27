import { EmptyState } from "../components/ui";
import type { View } from "../navigation";
import type {
  CaptureStatus,
  DiagnosticVehicle,
  MaintenanceRecord,
  MaintenanceRecordInput,
  Report,
  Status,
} from "../types";

type DashboardScreenProps = {
  status: Status | null;
  statusError: string;
  selectedVehicle: DiagnosticVehicle | null;
  diagnosticVehicles: DiagnosticVehicle[];
  vehicleSelectionBusy: boolean;
  report: Report | null;
  detectedEcuCount: number;
  dtcCount: number;
  capture: CaptureStatus | null;
  diagnosticReady: boolean;
  maintenanceRecords: MaintenanceRecord[];
  liveOdometerKm: number | null;
  onSelectVehicle: (vin: string) => Promise<void>;
  onAddMaintenance: (eventType: MaintenanceRecordInput["event_type"]) => void;
  onNavigate: (view: View) => void;
};

const dateLabel = (value?: string | null) => value
  ? new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString("fr-FR")
  : "Non renseignée";

const eventTypeLabel: Record<MaintenanceRecordInput["event_type"], string> = {
  maintenance: "Entretien",
  repair: "Réparation",
  diagnostic: "Diagnostic",
  inspection: "Contrôle",
  technical_inspection: "Contrôle technique",
  upgrade: "Modification",
  other: "Autre",
};

export function DashboardScreen({
  status,
  statusError,
  selectedVehicle,
  diagnosticVehicles,
  vehicleSelectionBusy,
  report,
  detectedEcuCount,
  dtcCount,
  capture,
  diagnosticReady,
  maintenanceRecords,
  liveOdometerKm,
  onSelectVehicle,
  onAddMaintenance,
  onNavigate,
}: DashboardScreenProps) {
  if (!selectedVehicle) {
    return (
      <section className="panel dashboard-vehicle-picker">
        <div>
          <span className="eyebrow">Garage</span>
          <h2>Sélectionne le véhicule à utiliser</h2>
          <p>L’entretien, les factures et les diagnostics seront toujours rattachés au VIN sélectionné.</p>
        </div>
        {diagnosticVehicles.length ? (
          <div className="dashboard-fleet-list">
            {diagnosticVehicles.map((vehicle) => (
              <button disabled={vehicleSelectionBusy || capture?.active} key={vehicle.vin} onClick={() => void onSelectVehicle(vehicle.vin)}>
                <span>{vehicle.manufacturer.slice(0, 2).toUpperCase()}</span>
                <div>
                  <strong>{vehicle.manufacturer} {vehicle.model}{vehicle.year ? ` · ${vehicle.year}` : ""}</strong>
                  <code>{vehicle.vin}</code>
                  <small>{vehicle.scan_count} diagnostic(s) enregistré(s)</small>
                </div>
                <b>Sélectionner →</b>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState title="Ton garage est vide" text="Ajoute un véhicule par lecture ou saisie de son VIN pour créer son dossier." />
        )}
        <button className="primary-button" onClick={() => onNavigate("garage")}>{diagnosticVehicles.length ? "Ouvrir le garage" : "Ajouter un véhicule"}</button>
      </section>
    );
  }

  const records = maintenanceRecords
    .filter((record) => record.vin === selectedVehicle.vin)
    .sort((left, right) => (right.performed_at || right.purchased_at || "").localeCompare(left.performed_at || left.purchased_at || ""));
  const recordedMileage = Math.max(0, ...records.map((record) => record.mileage_km ?? 0));
  const currentMileage = liveOdometerKm ?? (recordedMileage || null);
  const today = new Date().toISOString().slice(0, 10);
  const recommendations = records.flatMap((record) => record.recommendations
    .filter((recommendation) => recommendation.status === "open" || recommendation.status === "monitoring")
    .map((recommendation) => {
      const dueMileage = recommendation.due_mileage_km ?? (
        recommendation.recommended_at_km != null && recommendation.follow_up_after_km != null
          ? recommendation.recommended_at_km + recommendation.follow_up_after_km
          : null
      );
      const due = recommendation.status === "open" && (
        (dueMileage != null && currentMileage != null && currentMileage >= dueMileage)
        || (recommendation.due_date != null && recommendation.due_date <= today)
      );
      return { record, recommendation, dueMileage, due };
    }))
    .sort((left, right) => Number(right.due) - Number(left.due));
  const dueRecommendationCount = recommendations.filter((item) => item.due).length;
  const latestRecord = records[0] ?? null;

  return (
    <div className="vehicle-home">
      <section className="panel dashboard-vehicle-hero">
        <div className="dashboard-vehicle-main">
          <div className="garage-marque">{selectedVehicle.manufacturer.slice(0, 2).toUpperCase()}</div>
          <div>
            <span className="eyebrow">Véhicule actif</span>
            <h2>{selectedVehicle.manufacturer} {selectedVehicle.model}</h2>
            <p>{selectedVehicle.year ? `${selectedVehicle.year} · ` : ""}<code>{selectedVehicle.vin}</code></p>
          </div>
          <span className="status-pill good"><i /> Dossier sélectionné</span>
        </div>
        <div className="dashboard-vehicle-details">
          <div><span>Kilométrage connu</span><strong>{currentMileage == null ? "À renseigner" : `${Math.round(currentMileage).toLocaleString("fr-FR")} km`}</strong><small>{liveOdometerKm != null ? "Lecture véhicule" : "Dernière intervention"}</small></div>
          <div><span>Dernière activité</span><strong>{dateLabel(latestRecord?.performed_at || latestRecord?.purchased_at || selectedVehicle.last_seen)}</strong><small>{latestRecord?.title ?? "Dernier diagnostic ou identification"}</small></div>
          <div><span>Profil technique</span><strong>{selectedVehicle.vehicle_profile.replaceAll("_", " ")}</strong><small>VIN confirmé</small></div>
          <div><span>Garage</span><strong>{diagnosticVehicles.length} véhicule(s)</strong><small>Tu travailles sur {selectedVehicle.model}</small></div>
        </div>
        <div className="dashboard-vehicle-actions">
          <button className="primary-button" onClick={() => onNavigate("maintenance")}>Voir le carnet d’entretien</button>
          <button className="secondary-button" onClick={() => onNavigate("garage")}>Changer de véhicule</button>
        </div>
      </section>

      <section className="dashboard-summary-grid">
        <article className="dashboard-summary-card"><span>Interventions</span><strong>{records.length}</strong><small>entretiens, réparations et contrôles</small></article>
        <article className={`dashboard-summary-card ${dueRecommendationCount ? "attention" : ""}`}><span>Points à suivre</span><strong>{recommendations.length}</strong><small>{dueRecommendationCount ? `${dueRecommendationCount} échéance(s) atteinte(s)` : "aucune échéance dépassée"}</small></article>
        <article className={`dashboard-summary-card ${dtcCount ? "attention" : ""}`}><span>Défauts actifs</span><strong>{report ? dtcCount : "—"}</strong><small>{report ? `${detectedEcuCount} calculateur(s) détecté(s)` : `${selectedVehicle.scan_count} diagnostic(s) dans le dossier`}</small></article>
        <article className="dashboard-summary-card"><span>Connexion diagnostic</span><strong>{diagnosticReady ? "Prête" : "À connecter"}</strong><small>{status ? status.transport : (statusError || "backend indisponible")}</small></article>
      </section>

      <section className="dashboard-action-grid">
        <button onClick={() => onAddMaintenance("repair")}><span>＋</span><div><strong>Ajouter une réparation</strong><small>Facture, pièces, garage et date de pose</small></div><b>→</b></button>
        <button onClick={() => onAddMaintenance("maintenance")}><span>＋</span><div><strong>Ajouter un entretien</strong><small>Vidange, freins, pneus ou autre opération</small></div><b>→</b></button>
        <button onClick={() => onNavigate("ecus")}><span>ECU</span><div><strong>Lancer un diagnostic</strong><small>Lire les calculateurs et les défauts</small></div><b>→</b></button>
        <button onClick={() => onNavigate("sensors")}><span>∿</span><div><strong>Voir les données en direct</strong><small>Capteurs du véhicule et kilométrage</small></div><b>→</b></button>
      </section>

      <section className="dashboard-content-grid">
        <article className="panel dashboard-follow-up">
          <div className="section-heading">
            <div><span className="eyebrow">À suivre</span><h2>Recommandations en cours</h2><p>Les points signalés dans les factures, contrôles et diagnostics.</p></div>
            <button className="ghost-button" onClick={() => onNavigate("maintenance")}>Tout voir</button>
          </div>
          {recommendations.length ? (
            <div className="dashboard-follow-up-list">
              {recommendations.slice(0, 5).map(({ record, recommendation, dueMileage, due }, index) => (
                <button key={`${record.id}-${index}`} onClick={() => onNavigate("maintenance")}>
                  <i className={due ? "due" : recommendation.status} />
                  <div><strong>{recommendation.title}</strong><small>Signalé dans « {record.title} »</small></div>
                  <span>{due ? "À vérifier" : dueMileage != null ? `${dueMileage.toLocaleString("fr-FR")} km` : recommendation.status === "monitoring" ? "À surveiller" : "À faire"}</span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState title="Aucun point en attente" text="Les prochaines recommandations ajoutées au carnet apparaîtront ici." />
          )}
        </article>

        <article className="panel dashboard-recent-maintenance">
          <div className="section-heading">
            <div><span className="eyebrow">Historique</span><h2>Dernières interventions</h2><p>Les opérations les plus récentes du véhicule.</p></div>
            <button className="ghost-button" onClick={() => onNavigate("maintenance")}>Ouvrir le carnet</button>
          </div>
          {records.length ? (
            <div className="dashboard-recent-list">
              {records.slice(0, 5).map((record) => (
                <button key={record.id} onClick={() => onNavigate("maintenance")}>
                  <time>{dateLabel(record.performed_at || record.purchased_at)}</time>
                  <div><strong>{record.title}</strong><small>{eventTypeLabel[record.event_type]}{record.workshop ? ` · ${record.workshop}` : ""}</small></div>
                  <span>{record.mileage_km == null ? "—" : `${record.mileage_km.toLocaleString("fr-FR")} km`}</span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState title="Aucune intervention" text="Ajoute la première facture ou opération réalisée sur ce véhicule." action={<button className="primary-button" onClick={() => onAddMaintenance("maintenance")}>Ajouter un entretien</button>} />
          )}
        </article>
      </section>

      {capture?.active && <p className="inline-alert dashboard-capture-alert">Enregistrement en cours : {capture.name}. Le changement de véhicule est temporairement bloqué.</p>}
    </div>
  );
}
