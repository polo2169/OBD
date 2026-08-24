import { useState } from "react";

import { MaintenanceHistoryPanel } from "../components/MaintenanceHistoryPanel";
import { EmptyState } from "../components/ui";
import type {
  DiagnosticVehicle,
  MaintenanceCatalog,
  MaintenanceInvoiceAnalysis,
  MaintenanceMileageEstimate,
  MaintenanceRecord,
  MaintenanceRecordInput,
  MaintenanceService,
  OilLogEntry,
  OilLogEntryInput,
} from "../types";

type MaintenanceScreenProps = {
  catalog: MaintenanceCatalog | null;
  categories: string[];
  selectedCategory: string;
  services: MaintenanceService[];
  onCategoryChange: (category: string) => void;
  onUnavailableProcedure: () => void;
  oilLog: OilLogEntry[];
  liveOdometerKm: number | null;
  onRecordOilLogEntry: (entry: OilLogEntryInput) => Promise<void>;
  oilLogBusy: boolean;
  vehicle: DiagnosticVehicle | null;
  maintenanceRecords: MaintenanceRecord[];
  maintenanceRecordBusy: boolean;
  onCreateMaintenanceRecord: (entry: MaintenanceRecordInput, documents: File[]) => Promise<boolean>;
  onAddMaintenanceDocuments: (recordId: string, documents: File[]) => Promise<void>;
  onEstimateMaintenanceMileage: (vin: string, performedAt: string) => Promise<MaintenanceMileageEstimate | null>;
  onAnalyzeMaintenanceInvoice: (vin: string, document: File) => Promise<MaintenanceInvoiceAnalysis | null>;
};

function OilLogPanel({
  oilLog,
  liveOdometerKm,
  onRecordOilLogEntry,
  oilLogBusy,
}: Pick<MaintenanceScreenProps, "oilLog" | "liveOdometerKm" | "onRecordOilLogEntry" | "oilLogBusy">) {
  const [mileageKm, setMileageKm] = useState("");
  const [oilLevelNote, setOilLevelNote] = useState("");
  const [oilAddedL, setOilAddedL] = useState("");
  const [note, setNote] = useState("");

  const sorted = [...oilLog].sort((a, b) => b.mileage_km - a.mileage_km);
  const first = oilLog[0];
  const last = oilLog[oilLog.length - 1];
  const totalAdded = oilLog.reduce((sum, entry) => sum + (entry.oil_added_l ?? 0), 0);
  const distanceCovered = first && last && last.mileage_km > first.mileage_km ? last.mileage_km - first.mileage_km : null;

  async function handleSubmit() {
    const mileage = Number(mileageKm);
    if (!Number.isFinite(mileage) || mileage <= 0) return;
    await onRecordOilLogEntry({
      mileage_km: mileage,
      mileage_source: liveOdometerKm !== null && mileage === Math.round(liveOdometerKm) ? "can_signal" : "manual",
      oil_level_note: oilLevelNote.trim() || null,
      oil_added_l: oilAddedL.trim() ? Number(oilAddedL) : null,
      note: note.trim() || null,
    });
    setMileageKm("");
    setOilLevelNote("");
    setOilAddedL("");
    setNote("");
  }

  return (
    <section className="panel oil-log-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Carnet d'entretien</span>
          <h2>Kilométrage &amp; niveau d'huile</h2>
          <p>
            Kilométrage validé sur véhicule (0x552, BSI) ; le niveau d'huile n'a pas de source CAN fiable sur
            ce véhicule pour l'instant — saisie manuelle en attendant.
          </p>
        </div>
      </div>

      {totalAdded > 0 && distanceCovered && (
        <p className="inline-alert">
          {totalAdded.toFixed(2)} L d'appoint sur {distanceCovered.toLocaleString("fr-FR")} km depuis le premier relevé
          ({(totalAdded / (distanceCovered / 1000)).toFixed(2)} L/1000 km).
        </p>
      )}

      <div className="dtc-clear-form">
        <label>
          Kilométrage (km)
          <input
            type="number"
            min={0}
            value={mileageKm}
            onChange={(event) => setMileageKm(event.target.value)}
            placeholder={liveOdometerKm !== null ? String(Math.round(liveOdometerKm)) : "ex. 104975"}
          />
        </label>
        {liveOdometerKm !== null && (
          <button
            type="button"
            className="secondary-button"
            onClick={() => setMileageKm(String(Math.round(liveOdometerKm)))}
          >
            Utiliser le kilométrage CAN ({Math.round(liveOdometerKm).toLocaleString("fr-FR")} km)
          </button>
        )}
        <label>
          Niveau d'huile observé
          <input
            type="text"
            value={oilLevelNote}
            onChange={(event) => setOilLevelNote(event.target.value)}
            placeholder="ex. entre mini et maxi"
          />
        </label>
        <label>
          Appoint ajouté (L)
          <input
            type="number"
            min={0}
            step={0.1}
            value={oilAddedL}
            onChange={(event) => setOilAddedL(event.target.value)}
          />
        </label>
        <label>
          Note
          <input type="text" value={note} onChange={(event) => setNote(event.target.value)} placeholder="ex. avant vidange" />
        </label>
        <button
          className="primary-button"
          disabled={oilLogBusy || !mileageKm.trim()}
          onClick={() => void handleSubmit()}
        >
          {oilLogBusy ? "Enregistrement…" : "Ajouter au carnet"}
        </button>
      </div>

      {sorted.length === 0 ? (
        <EmptyState title="Carnet vide" text="Ajoute un premier relevé pour commencer le suivi." />
      ) : (
        <div className="maintenance-service-grid">
          {sorted.map((entry) => (
            <article key={entry.id}>
              <header>
                <span>{new Date(entry.recorded_at).toLocaleDateString("fr-FR")}</span>
                <b>{entry.mileage_km.toLocaleString("fr-FR")} km</b>
              </header>
              <h3>{entry.oil_level_note ?? "Niveau non renseigné"}</h3>
              {typeof entry.oil_added_l === "number" && <p>Appoint : {entry.oil_added_l} L</p>}
              {entry.note && <small>{entry.note}</small>}
              <footer>
                <span>{entry.mileage_source === "can_signal" ? "Kilométrage CAN" : "Kilométrage saisi"}</span>
              </footer>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export function MaintenanceScreen({
  catalog,
  categories,
  selectedCategory,
  services,
  onCategoryChange,
  onUnavailableProcedure,
  oilLog,
  liveOdometerKm,
  onRecordOilLogEntry,
  oilLogBusy,
  vehicle,
  maintenanceRecords,
  maintenanceRecordBusy,
  onCreateMaintenanceRecord,
  onAddMaintenanceDocuments,
  onEstimateMaintenanceMileage,
  onAnalyzeMaintenanceInvoice,
}: MaintenanceScreenProps) {
  if (!catalog) {
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
          <div><span className="eyebrow">{catalog.manufacturer} {catalog.model}</span><h2>{catalog.service_count} services référencés</h2><p>Le catalogue n'autorise jamais une trame tant que la procédure exacte et ses prérequis ne sont pas validés sur le véhicule.</p></div>
          <span className={`status-pill ${catalog.execution_enabled ? "good" : "neutral"}`}><i />{catalog.execution_enabled ? "Procédures validées disponibles" : "Catalogue sécurisé"}</span>
        </div>
        <div className="maintenance-protocol-grid">
          {catalog.protocol_coverage.map((protocol) => <article className={protocol.supported ? "supported" : "missing"} key={protocol.key}><strong>{protocol.name}</strong><span>{protocol.supported ? "Pris en charge" : "Matériel requis"}</span><p>{protocol.detail}</p></article>)}
        </div>
        {catalog.notes.map((note) => <p className="inline-alert" key={note}>{note}</p>)}
      </section>

      <MaintenanceHistoryPanel
        vehicle={vehicle}
        records={maintenanceRecords}
        liveOdometerKm={liveOdometerKm}
        busy={maintenanceRecordBusy}
        onCreate={onCreateMaintenanceRecord}
        onAddDocuments={onAddMaintenanceDocuments}
        onEstimateMileage={onEstimateMaintenanceMileage}
        onAnalyzeInvoice={onAnalyzeMaintenanceInvoice}
      />

      <OilLogPanel
        oilLog={oilLog}
        liveOdometerKm={liveOdometerKm}
        onRecordOilLogEntry={onRecordOilLogEntry}
        oilLogBusy={oilLogBusy}
      />

      <section className="panel maintenance-catalog-panel">
        <div className="section-heading"><div><span className="eyebrow">Matrice d'applicabilité</span><h2>Fonctions Fiat / Peugeot</h2></div></div>
        <div className="sensor-category-tabs">
          {categories.map((category) => <button className={selectedCategory === category ? "active" : ""} key={category} onClick={() => onCategoryChange(category)}>{category}</button>)}
        </div>
        <div className="maintenance-service-grid">
          {services.map((service) => (
            <article className={`${service.applicability} risk-${service.risk}`} key={service.key}>
              <header><span>{service.category}</span><b>{applicabilityLabel[service.applicability]}</b></header>
              <h3>{service.name}</h3>
              <p>{service.description}</p>
              <small>{service.reason}</small>
              <footer><span>{statusLabel[service.implementation_status]}</span><button className="secondary-button" disabled={!service.execution_enabled} onClick={onUnavailableProcedure}>{service.execution_enabled ? "Ouvrir la procédure" : "Verrouillé"}</button></footer>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
