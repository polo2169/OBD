import type { Dispatch, FormEventHandler, SetStateAction } from "react";

import type { OperatingModeState } from "../types";

type ModeChecks = {
  vehicle_stationary: boolean;
  ignition_on_engine_off: boolean;
  stable_battery_voltage: boolean;
  workshop_or_private_site: boolean;
};

type MaintenanceModeDialogProps = {
  open: boolean;
  operatingMode: OperatingModeState | null;
  selectedVin: string;
  checks: ModeChecks;
  setChecks: Dispatch<SetStateAction<ModeChecks>>;
  confirmation: string;
  setConfirmation: Dispatch<SetStateAction<string>>;
  busy: boolean;
  onClose: () => void;
  onSubmit: FormEventHandler<HTMLFormElement>;
};

export function MaintenanceModeDialog({ open, operatingMode, selectedVin, checks, setChecks, confirmation, setConfirmation, busy, onClose, onSubmit }: MaintenanceModeDialogProps) {
  if (!open) return null;

  return <div className="sensor-editor-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
    <form className="sensor-editor mode-switch-modal" onSubmit={onSubmit} onMouseDown={(event) => event.stopPropagation()}>
      <div className="section-heading">
        <div><span className="eyebrow">Security & Workflow</span><h2>Activer la maintenance contrôlée</h2><p>Cette autorisation reste en mémoire uniquement jusqu’au redémarrage du backend ou au retour manuel en lecture seule.</p></div>
        <button type="button" className="ghost-button" onClick={onClose} disabled={busy}>Fermer</button>
      </div>
      <div className="mode-readiness-grid">
        <div className={operatingMode?.can_tx_enabled ? "ready" : "blocked"}><span>Émission CAN</span><strong>{operatingMode?.can_tx_enabled ? "Configurée" : "Désactivée"}</strong></div>
        <div className={operatingMode?.gateway_ready ? "ready" : "blocked"}><span>Passerelle</span><strong>{operatingMode?.gateway_ready ? "Validée" : "Non validée"}</strong></div>
        <div className={selectedVin ? "ready" : "blocked"}><span>Véhicule</span><strong>{selectedVin || "VIN requis"}</strong></div>
      </div>
      {!operatingMode?.maintenance_available && <p className="inline-alert danger-alert">Mode actuellement indisponible : {operatingMode?.blockers.join(" · ") || "état serveur inconnu"}.</p>}
      <div className="mode-preconditions">
        <label><input type="checkbox" checked={checks.vehicle_stationary} onChange={(event) => setChecks((current) => ({ ...current, vehicle_stationary: event.target.checked }))} /><span><strong>Véhicule immobilisé</strong><small>Frein de stationnement appliqué</small></span></label>
        <label><input type="checkbox" checked={checks.ignition_on_engine_off} onChange={(event) => setChecks((current) => ({ ...current, ignition_on_engine_off: event.target.checked }))} /><span><strong>Contact mis, moteur arrêté</strong><small>Sauf instruction contraire du workflow métier</small></span></label>
        <label><input type="checkbox" checked={checks.stable_battery_voltage} onChange={(event) => setChecks((current) => ({ ...current, stable_battery_voltage: event.target.checked }))} /><span><strong>Tension batterie stable</strong><small>Alimentation adaptée aux opérations prévues</small></span></label>
        <label><input type="checkbox" checked={checks.workshop_or_private_site} onChange={(event) => setChecks((current) => ({ ...current, workshop_or_private_site: event.target.checked }))} /><span><strong>Atelier ou site privé</strong><small>Aucun usage sur route ouverte</small></span></label>
      </div>
      <label>Confirmation exacte<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="ACTIVER MAINTENANCE" /><small>Saisis ACTIVER MAINTENANCE</small></label>
      <p className="inline-alert">Ce changement n’active pas automatiquement l’effacement DTC, SecurityAccess ou les actionneurs. Chaque fonction garde son workflow dédié.</p>
      <div className="sensor-editor-actions">
        <button type="button" className="ghost-button" onClick={onClose} disabled={busy}>Annuler</button>
        <button type="submit" className="danger-button" disabled={busy || !operatingMode?.maintenance_available || !selectedVin || confirmation !== "ACTIVER MAINTENANCE" || !Object.values(checks).every(Boolean)}>{busy ? "Armement…" : "Activer la maintenance"}</button>
      </div>
    </form>
  </div>;
}
