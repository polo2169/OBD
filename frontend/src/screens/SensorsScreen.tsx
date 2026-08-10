import type { Dispatch, FormEvent, SetStateAction } from "react";

import { EmptyState } from "../components/ui";
import { hexadecimal } from "../format";
import { LAB_MODE } from "../navigation";
import type { View } from "../navigation";
import type { PassiveCanSignal, PassiveSensorSnapshot } from "../types";

type SensorEditor={key:string;label:string;description:string;unit:string;factor:string;offset:string;customized:boolean};
type LiveSensorEditor={key?:string;sourceKey:string;label:string;description:string;category:string;unit:string;factor:string;offset:string};
type SensorsScreenProps={
 startFullSensorDetection:(openSensors?:boolean,liveDataReads?:boolean)=>Promise<void>; detectionBusy:boolean; detectionRemaining:number; passiveSensors:PassiveSensorSnapshot|null; liveObdReadOnly:boolean; createLiveSensor:()=>void; selectedDiagnosticVin:string; refreshPassiveSensors:(openView?:boolean)=>Promise<void>;
 sensorCategories:string[]; sensorCategory:string; setSensorCategory:Dispatch<SetStateAction<string>>; sensorSearch:string; setSensorSearch:Dispatch<SetStateAction<string>>; setView:Dispatch<SetStateAction<View>>; visiblePassiveSignals:PassiveCanSignal[]; editLiveSensor:(signal:PassiveCanSignal)=>void; editPassiveSensor:(signal:PassiveCanSignal)=>void;
 sensorEditor:SensorEditor|null; setSensorEditor:Dispatch<SetStateAction<SensorEditor|null>>; savePassiveSensorOverride:(event:FormEvent)=>Promise<void>; resetPassiveSensorOverride:()=>Promise<void>; sensorEditorBusy:boolean; liveSensorEditor:LiveSensorEditor|null; setLiveSensorEditor:Dispatch<SetStateAction<LiveSensorEditor|null>>; saveLiveSensor:(event:FormEvent)=>Promise<void>; archiveLiveSensor:()=>Promise<void>; liveSensorEditorBusy:boolean;
};

export function SensorsScreen({
  startFullSensorDetection,
  detectionBusy,
  detectionRemaining,
  passiveSensors,
  liveObdReadOnly,
  createLiveSensor,
  selectedDiagnosticVin,
  refreshPassiveSensors,
  sensorCategories,
  sensorCategory,
  setSensorCategory,
  sensorSearch,
  setSensorSearch,
  setView,
  visiblePassiveSignals,
  editLiveSensor,
  editPassiveSensor,
  sensorEditor,
  setSensorEditor,
  savePassiveSensorOverride,
  resetPassiveSensorOverride,
  sensorEditorBusy,
  liveSensorEditor,
  setLiveSensorEditor,
  saveLiveSensor,
  archiveLiveSensor,
  liveSensorEditorBusy
}: SensorsScreenProps) {
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
            <span className={`status-pill ${passiveSensors?.strict_passive || liveObdReadOnly ? "good" : "bad"}`}>
              <i /> {passiveSensors?.strict_passive
                ? "Passif strict · émission impossible"
                : liveObdReadOnly
                  ? "Capture passive · OBD 01/09 filtré"
                  : "Sécurité à vérifier"}
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
          <p className="inline-alert">
            <strong>Consommation :</strong> aucun débit fiable n'est diffusé passivement sur la capture actuelle. Utilise « Injection » pour tenter la lecture OBD moteur du débit carburant (PID 01-5E).
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
              {LAB_MODE && <div className="steering-sources">
                <code>{passiveSensors.steering.angle_source ?? "Angle indisponible"}</code>
                <code>{passiveSensors.steering.torque_source ?? "Couple indisponible"}</code>
              </div>}
              {passiveSensors.steering.warning && <p className="inline-alert">{passiveSensors.steering.warning}</p>}
            </>
          ) : (
            <EmptyState title="Volant non observé" text="Démarre une capture passive puis tourne doucement le volant à l'arrêt." />
          )}
        </section>

        <section className="panel passive-sensors-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Direct hybride · CAN passif + OBD normalisé</span>
              <h2>Tous les signaux décodés</h2>
              <p>{passiveSensors
                ? `${passiveSensors.decoded_signal_count} signaux live · ${passiveSensors.observed_message_count} messages OpenDBC · ${passiveSensors.frame_count.toLocaleString("fr-FR")} trames`
                : "En attente de la capture"}</p>
            </div>
            <div className="section-actions">
              <button className="ghost-button" onClick={createLiveSensor} disabled={!selectedDiagnosticVin || !passiveSensors?.signals.some((signal) => !signal.user_defined)}>Ajouter un capteur</button>
              <button className="secondary-button" onClick={() => refreshPassiveSensors()}>Actualiser</button>
            </div>
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
                      <span>{signal.category}{signal.essential ? " · essentiel" : ""}{signal.user_defined ? " · local au véhicule" : ""}</span>
                      <strong>{signal.display_name}</strong>
                      <p>{signal.description}</p>
                    </div>
                    <div className="sensor-live-value">
                      <strong>{String(signal.value ?? "—")}</strong>
                      <span>{signal.unit || "sans unité"}</span>
                  {LAB_MODE && signal.customized && <small>Source : {String(signal.raw_value ?? "—")} {signal.source_unit ?? ""}</small>}
                    </div>
                    <div className="sensor-live-source">
                      <code>{signal.user_defined ? "Capteur local dérivé" : signal.source === "obd" ? "Lecture OBD-II normalisée" : "CAN constructeur décodé"}</code>
                      <span>{signal.user_defined ? "Définition utilisateur observée" : signal.confidence === "standardized" ? "OBD-II normalisé" : signal.confidence === "validated" ? "Validé sur le véhicule" : signal.confidence === "vehicle_observed_candidate" ? "Trame Fiat observée · décodage à confirmer" : "Définition OpenDBC à confirmer"}</span>
                    </div>
                    {signal.user_defined ? <button className="ghost-button" onClick={() => editLiveSensor(signal)}>Modifier</button> : signal.source === "can" ? <button className="ghost-button" onClick={() => editPassiveSensor(signal)}>
                      {signal.customized ? "Modifier" : "Corriger"}
                    </button> : <span className="source-badge measured">OBD</span>}
                  </article>
                ))}
              </div>
              {visiblePassiveSignals.length === 0 && (
                <p className="inline-alert">Aucun signal ne correspond aux filtres.</p>
              )}
              <div className="footer-meta">
                <span>{visiblePassiveSignals.length} affichés</span>
                <span>{passiveSensors.strict_passive ? "Passif strict" : liveObdReadOnly ? "OBD 01/09 filtré" : "Mode à vérifier"}</span>
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
                <div><span className="eyebrow">Correction locale persistante</span><h2>Corriger un capteur</h2>{LAB_MODE && <code>{sensorEditor.key}</code>}</div>
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

        {liveSensorEditor && (
          <div className="sensor-editor-backdrop" role="presentation" onMouseDown={() => setLiveSensorEditor(null)}>
            <form className="sensor-editor" onSubmit={saveLiveSensor} onMouseDown={(event) => event.stopPropagation()}>
              <div className="section-heading">
                <div><span className="eyebrow">Registre Live Data · portée VIN</span><h2>{liveSensorEditor.key ? "Modifier le capteur" : "Ajouter un capteur"}</h2></div>
                <button type="button" className="ghost-button" onClick={() => setLiveSensorEditor(null)}>Fermer</button>
              </div>
              <label>Source physique<select value={liveSensorEditor.sourceKey} disabled={Boolean(liveSensorEditor.key)} onChange={(event) => {
                const source = passiveSensors?.signals.find((signal) => signal.key === event.target.value);
                setLiveSensorEditor({
                  ...liveSensorEditor,
                  sourceKey: event.target.value,
                  category: source?.category ?? liveSensorEditor.category,
                  unit: source?.unit ?? liveSensorEditor.unit,
                });
              }}>{passiveSensors?.signals.filter((signal) => !signal.user_defined).map((signal) => <option value={signal.key} key={signal.key}>{signal.display_name} · {signal.category}</option>)}</select></label>
              <label>Nom lisible<input required value={liveSensorEditor.label} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, label: event.target.value })} /></label>
              <label>Explication<textarea value={liveSensorEditor.description} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, description: event.target.value })} /></label>
              <div className="sensor-editor-grid">
                <label>Catégorie<input value={liveSensorEditor.category} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, category: event.target.value })} /></label>
                <label>Unité<input value={liveSensorEditor.unit} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, unit: event.target.value })} /></label>
                <label>Facteur<input type="number" step="any" value={liveSensorEditor.factor} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, factor: event.target.value })} /></label>
                <label>Offset<input type="number" step="any" value={liveSensorEditor.offset} onChange={(event) => setLiveSensorEditor({ ...liveSensorEditor, offset: event.target.value })} /></label>
              </div>
              <p className="inline-alert">Ce capteur est rattaché au VIN {selectedDiagnosticVin}. La suppression l’archive pour préserver les anciennes captures.</p>
              <div className="sensor-editor-actions">
                {liveSensorEditor.key && <button type="button" className="stop-button" onClick={() => void archiveLiveSensor()} disabled={liveSensorEditorBusy}>Supprimer</button>}
                <button type="submit" className="primary-button" disabled={liveSensorEditorBusy || !liveSensorEditor.label.trim()}>{liveSensorEditorBusy ? "Enregistrement…" : liveSensorEditor.key ? "Enregistrer" : "Ajouter au Live Data"}</button>
              </div>
            </form>
          </div>
        )}
      </div>
    );
  }
