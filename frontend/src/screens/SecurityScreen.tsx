import type { View } from "../navigation";
import type { OperatingModeState, Status } from "../types";

type SecurityScreenProps = {
  operatingMode: OperatingModeState | null;
  status: Status | null;
  modeSwitchBusy: boolean;
  labMode: boolean;
  onActivateReadOnly: () => Promise<void>;
  onOpenMaintenanceDialog: () => void;
  onNavigate: (view: View) => void;
};

export function SecurityScreen({
  operatingMode,
  status,
  modeSwitchBusy,
  labMode,
  onActivateReadOnly,
  onOpenMaintenanceDialog,
  onNavigate,
}: SecurityScreenProps) {
  const currentMode = operatingMode?.mode ?? (status?.read_only === false ? "maintenance" : "read_only");

  return (
    <div className="security-page">
      <section className="panel operating-mode-panel">
        <div className="section-heading">
          <div><span className="eyebrow">Mode global temporaire</span><h2>Choisir le niveau d’autorisation</h2><p>Le mode limite toutes les opérations du backend. Chaque fonction conserve ensuite ses propres verrous et confirmations.</p></div>
          <span className={`status-pill ${currentMode === "read_only" ? "good" : "bad"}`}><i /> {currentMode === "read_only" ? "Lecture seule" : "Maintenance contrôlée"}</span>
        </div>
        <div className="operating-mode-selector">
          <button className={currentMode === "read_only" ? "selected safe" : ""} onClick={() => void onActivateReadOnly()} disabled={modeSwitchBusy}>
            <span>MODE 1</span><strong>Lecture seule</strong><p>Identification, paramètres, défauts et Live Data. Aucune opération de maintenance.</p><small>Toujours disponible · retour immédiat</small>
          </button>
          <button className={currentMode === "maintenance" ? "selected maintenance" : ""} onClick={onOpenMaintenanceDialog} disabled={modeSwitchBusy || currentMode === "maintenance" || !operatingMode?.maintenance_available}>
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
      {labMode && <section className="panel lab-entry"><div><span className="eyebrow">Mode laboratoire explicite</span><h2>Outils protocolaires</h2><p>Cette zone reste séparée de l’usage normal et n’est visible qu’avec `lab=1`.</p></div><button className="danger-button" onClick={() => onNavigate("psa")}>Ouvrir le laboratoire PSA</button></section>}
    </div>
  );
}
