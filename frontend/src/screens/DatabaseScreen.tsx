import type {
  DiagnosticSensorCatalogEntry,
  Ecu,
  LiveSensorDefinition,
  MaintenanceCatalog,
  Report,
  VehicleProfileSummary,
} from "../types";
import type { View } from "../navigation";

type DatabaseScreenProps = {
  report: Report | null;
  vehicleProfiles: VehicleProfileSummary[];
  detectedEcus: Ecu[];
  diagnosticSensorCatalog: DiagnosticSensorCatalogEntry[];
  liveSensorDefinitions: LiveSensorDefinition[];
  maintenanceCatalog: MaintenanceCatalog | null;
  onNavigate: (view: View) => void;
  onOpenPassiveSensors: () => Promise<void>;
};

export function DatabaseScreen({
  report,
  vehicleProfiles,
  detectedEcus,
  diagnosticSensorCatalog,
  liveSensorDefinitions,
  maintenanceCatalog,
  onNavigate,
  onOpenPassiveSensors,
}: DatabaseScreenProps) {
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
        <button onClick={() => onNavigate("ecus")}><span>ECU</span><strong>Calculateurs et identifications</strong><p>{documentedDids} identifiant(s) actuellement lus sur le véhicule actif.</p><small>Adresses · familles · versions · séries</small></button>
        <button onClick={() => void onOpenPassiveSensors()}><span>DATA</span><strong>Registre des capteurs</strong><p>Sources CAN, OBD et définitions locales rattachées au VIN.</p><small>Unité · conversion · confiance · historique</small></button>
        <button onClick={() => onNavigate("dtcs")}><span>DTC</span><strong>Catalogue des défauts</strong><p>{report?.dtc_summary.total ?? 0} entrée(s) dans le dernier scan.</p><small>État · source · description</small></button>
        <button onClick={() => onNavigate("maintenance")}><span>WF</span><strong>Procédures métier</strong><p>{maintenanceCatalog?.service_count ?? 0} capacités classées, exécutables uniquement après validation.</p><small>Applicabilité · risque · maturité</small></button>
      </section>
      <section className="panel knowledge-lifecycle"><div className="section-heading"><div><span className="eyebrow">Cycle obligatoire</span><h2>Découvert → observé → validé → documenté → publié</h2><p>Une corrélation Learn ne devient jamais automatiquement un capteur officiel ni une commande exécutable.</p></div></div></section>
    </div>
  );
}
