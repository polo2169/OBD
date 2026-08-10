import type { Dispatch, SetStateAction } from "react";

import { TelecodingDetails } from "../components/TelecodingDetails";
import { hexadecimal } from "../format";
import { LAB_MODE } from "../navigation";
import type { View } from "../navigation";
import type { CaptureStatus, ClearDtcResult, DidSweepResult, Ecu, RegressionResult, Report, Status } from "../types";

type DtcClearChecks={vehicle_stationary:boolean;ignition_on_engine_off:boolean;stable_battery_voltage:boolean;report_saved:boolean};
type PassiveSubsystem={category:string;name:string;description:string;messages:string[];detected:boolean};
type EcusScreenProps={startFullSensorDetection:(openSensors?:boolean,liveDataReads?:boolean)=>Promise<void>;detectionBusy:boolean;detectionRemaining:number;passiveSubsystems:PassiveSubsystem[];diagnosticReady:boolean;dualCanOperational:boolean;capture:CaptureStatus|null;status:Status|null;diagnosticGatewayVerified:boolean;liveObdReadOnly:boolean;scan:()=>Promise<void>;busy:boolean;report:Report|null;detectedEcus:Ecu[];verifyDiagnosticRegression:(scanId?:string|null)=>Promise<void>;diagnosticRegressionBusy:boolean;diagnosticRegression:RegressionResult|null;selectedEcu:Ecu|null;setSelectedEcuKey:Dispatch<SetStateAction<string>>;openPassiveSensors:()=>Promise<void>;setView:Dispatch<SetStateAction<View>>;didSweepStart:string;setDidSweepStart:Dispatch<SetStateAction<string>>;didSweepEnd:string;setDidSweepEnd:Dispatch<SetStateAction<string>>;sweepSelectedEcuDids:(ecuKey?:string)=>Promise<void>;didSweepBusy:boolean;didSweepResult:DidSweepResult|null;dtcClearEcuKey:string;setDtcClearEcuKey:Dispatch<SetStateAction<string>>;setDtcClearConfirmation:Dispatch<SetStateAction<string>>;setDtcClearResult:Dispatch<SetStateAction<ClearDtcResult|null>>;dtcClearChecks:DtcClearChecks;setDtcClearChecks:Dispatch<SetStateAction<DtcClearChecks>>;dtcClearConfirmation:string;clearSelectedEcuDtcs:(ecuKey?:string)=>Promise<void>;dtcClearBusy:boolean;dtcClearResult:ClearDtcResult|null};

export function EcusScreen({
  startFullSensorDetection,
  detectionBusy,
  detectionRemaining,
  passiveSubsystems,
  diagnosticReady,
  dualCanOperational,
  capture,
  status,
  diagnosticGatewayVerified,
  liveObdReadOnly,
  scan,
  busy,
  report,
  detectedEcus,
  verifyDiagnosticRegression,
  diagnosticRegressionBusy,
  diagnosticRegression,
  selectedEcu,
  setSelectedEcuKey,
  openPassiveSensors,
  setView,
  didSweepStart,
  setDidSweepStart,
  didSweepEnd,
  setDidSweepEnd,
  sweepSelectedEcuDids,
  didSweepBusy,
  didSweepResult,
  dtcClearEcuKey,
  setDtcClearEcuKey,
  setDtcClearConfirmation,
  setDtcClearResult,
  dtcClearChecks,
  setDtcClearChecks,
  dtcClearConfirmation,
  clearSelectedEcuDtcs,
  dtcClearBusy,
  dtcClearResult
}: EcusScreenProps) {
    return (
      <div className="ecu-discovery-page">
        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Découverte passive · aucune émission</span>
              <h2>Systèmes observés sur le CAN</h2>
              <p>Présence déduite des messages diffusés; ce n'est pas encore une identification UDS du calculateur.</p>
            </div>
            <button className="secondary-button" onClick={() => startFullSensorDetection(false, false)} disabled={detectionBusy || detectionRemaining > 0}>
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
              <p>Cette étape ouvre une session de lecture, identifie les systèmes et relève leurs défauts, sans effacement ni télécodage.</p>
            </div>
            <span className={`status-pill ${diagnosticReady ? "good" : "neutral"}`}><i /> {diagnosticReady ? (dualCanOperational ? "Double CAN prêt" : "Prêt") : capture?.active ? "Capture active" : status?.can_tx_enabled ? "ESP32 à valider" : "Verrouillé"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Liaison ESP32</span><strong>{diagnosticGatewayVerified ? "Poignée de main validée" : "Connexion requise"}</strong></div>
            <div><span>Réseaux CAN</span><strong>{dualCanOperational ? liveObdReadOnly ? "6/14 OBD lecture + 3/8 diagnostic" : "6/14 live + 3/8 diagnostic" : status?.gateway_hello?.dual_can === true ? "Double CAN détecté" : "Interface unique"}</strong></div>
            <div><span>Firmware ESP32</span><strong>{status?.gateway_hello?.diagnostic_read_only === true || status?.transport === "virtual" ? "Lecture seule validée" : status?.can_tx_enabled ? "À confirmer" : "Listen-only"}</strong></div>
            <div><span>Requêtes CAN</span><strong>{status?.can_tx_enabled ? "UDS lecture uniquement" : "Bloquées"}</strong></div>
            <div><span>Effacement / télécodage</span><strong>{status?.dtc_clear_enabled ? "Maintenance armée" : "Toujours interdit"}</strong></div>
          </div>
          {diagnosticReady ? (
            <button className="primary-button full-scan-button" onClick={scan} disabled={busy}>{busy ? "Inventaire en cours…" : "Lancer l'inventaire ECU + DTC"}</button>
          ) : (
            <p className="inline-alert">{capture?.active && !dualCanOperational
              ? "La capture est active mais le MCP2515 diagnostic 3/8 n’est pas confirmé disponible."
              : status?.can_tx_enabled
                ? "Retourne au Dashboard direct, sélectionne l’ESP32 puis clique sur Connecter. La poignée de main doit confirmer le firmware diagnostic en lecture seule."
                : "Le backend est verrouillé en écoute passive. Un firmware diagnostic séparé et CAN_TX_ENABLED=true sont nécessaires pour les lectures UDS."}</p>
          )}
        </section>

        {report && (
          <section className="panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">{detectedEcus.length} détectés sur {report.ecus.length}</span>
                <h2>Diagnostic par calculateur</h2>
                <p>Sélectionne un système pour retrouver son état, son identification, ses défauts et les fonctions qui lui sont rattachées.</p>
              </div>
              <div className="section-actions">
                <button className="ghost-button" onClick={() => void verifyDiagnosticRegression()} disabled={!report.scan_id || diagnosticRegressionBusy}>{diagnosticRegressionBusy ? "Comparaison…" : "Vérifier la référence"}</button>
                <button className="secondary-button" onClick={scan} disabled={busy || !diagnosticReady}>Relancer le scan</button>
              </div>
            </div>
            {diagnosticRegression && <div className={`regression-result ${diagnosticRegression.connectivity_match ? "good" : "warning"}`}>
              <strong>{diagnosticRegression.connectivity_match ? "Couverture ECU conforme" : "Écart de couverture ECU"}</strong>
              <span>{diagnosticRegression.connectivity_match ? "Les 8 calculateurs, leurs adresses et leurs réponses de session correspondent à la référence réelle." : `${diagnosticRegression.differences.filter((item) => item.scope === "connectivity").length} différence(s) de communication.`}</span>
              <small>{diagnosticRegression.dtc_match ? "Mémoire DTC brute identique à la référence." : "Les DTC ont évolué : ce résultat peut être normal après une réparation ou un effacement."}</small>
            </div>}
            <div className="ecu-selector" role="tablist" aria-label="Calculateurs détectés">
              {detectedEcus.map((ecu) => <button
                type="button"
                role="tab"
                aria-selected={selectedEcu?.key === ecu.key}
                className={selectedEcu?.key === ecu.key ? "selected" : ""}
                onClick={() => setSelectedEcuKey(ecu.key)}
                key={ecu.key}
              >
                <i />
                <span>{ecu.name}</span>
                <small>{ecu.dtcs.filter((dtc) => dtc.state === "active").length || "OK"}</small>
              </button>)}
            </div>

            {selectedEcu && <div className="ecu-workspace">
              <header>
                <div>
                  <span className="eyebrow">{selectedEcu.family ?? selectedEcu.network}</span>
                  <h3>{selectedEcu.name}</h3>
                  <p>{selectedEcu.detected ? "Calculateur joignable lors du dernier diagnostic." : "Calculateur non joint lors du dernier diagnostic."}</p>
                </div>
                <span className={`status-pill ${selectedEcu.detected ? "good" : "neutral"}`}><i /> {selectedEcu.detected ? "Détecté" : "Absent"}</span>
              </header>
              <div className="ecu-workspace-summary">
                <div><span>Identification</span><strong>{selectedEcu.identification.filter((item) => !item.error).length} information(s)</strong><small>Versions, références et numéros disponibles</small></div>
                <div><span>Défauts actifs</span><strong>{selectedEcu.dtcs.filter((dtc) => dtc.state === "active").length}</strong><small>{selectedEcu.dtcs.length} entrée(s) lue(s) au total</small></div>
                <div><span>Communication</span><strong>{selectedEcu.active_session ? "Session diagnostic" : "Présence confirmée"}</strong><small>{selectedEcu.probe_method ? `Méthode ${selectedEcu.probe_method}` : selectedEcu.network}</small></div>
                <div><span>Tests fonctionnels</span><strong>Aucun test publié</strong><small>Une commande reste indisponible tant que son workflow n’est pas validé</small></div>
              </div>
              <div className="ecu-workspace-actions">
                <button className="secondary-button" onClick={() => void openPassiveSensors()}>Live Data</button>
                <button className="secondary-button" onClick={() => setView("dtcs")}>Défauts</button>
                <button className="secondary-button" onClick={() => setView("garage")}>Historique</button>
                <button className="secondary-button" onClick={() => setView("database")}>Documentation</button>
                <button className="ghost-button" onClick={() => setView("maintenance")}>Fonctions disponibles</button>
              </div>
              {selectedEcu.identification.some((item) => !item.error) ? <div className="ecu-identification-list">
                {selectedEcu.identification.filter((item) => !item.error).map((item) => <article key={item.did}>
                  <span>{item.name}</span>
                  <strong>{String(item.value ?? "—")}</strong>
                  <small>{item.source ?? "Lecture véhicule"} · confiance {item.confidence}</small>
                </article>)}
              </div> : <p className="inline-alert">Aucune version ni référence n’a encore été obtenue pour ce calculateur.</p>}
              {selectedEcu.identification.some((item) => item.error) && <p className="ecu-read-summary">{selectedEcu.identification.filter((item) => item.error).length} information(s) supplémentaire(s) non disponible(s) sur cette session.</p>}
              {LAB_MODE && <details className="ecu-technical-details">
                <summary>Preuves protocolaires · mode laboratoire</summary>
                <div><code>{hexadecimal(selectedEcu.request_id)} → {hexadecimal(selectedEcu.response_id)}</code><span>Adressage diagnostic</span><small>{selectedEcu.network}</small></div>
                {selectedEcu.probe_attempts?.map((attempt, index) => <div key={`${attempt.request_hex}-${index}`}><code>{attempt.request_hex}</code><span>{attempt.outcome}</span><small>{attempt.response_hex ?? attempt.error ?? "Aucune réponse"}</small></div>)}
              </details>}
              {(selectedEcu.did_sweep_range || selectedEcu.did_sweep_error) && <div className="did-sweep-panel">
                <div className="section-heading">
                  <div><span className="eyebrow">Recherche approfondie du dernier scan</span><h3>Balayage automatique {selectedEcu.did_sweep_range}</h3></div>
                </div>
                {selectedEcu.did_sweep_error ? (
                  <p className="inline-alert">{selectedEcu.did_sweep_error}</p>
                ) : selectedEcu.did_sweep_hits && selectedEcu.did_sweep_hits.length > 0 ? (
                  <div className="did-sweep-results">
                    <p><strong>{selectedEcu.did_sweep_hits.length}</strong> réponse(s) exploitable(s) trouvée(s) automatiquement.</p>
                    {selectedEcu.did_sweep_hits.map((hit) => (
                      <div className="did-sweep-hit" key={hit.did}>
                        <code>0x{hit.did.toString(16).toUpperCase().padStart(4, "0")}</code>
                        <span>{hit.outcome === "positive" ? "Réponse positive" : `NRC 0x${hit.nrc?.toString(16).toUpperCase().padStart(2, "0")} ${hit.nrc_name ?? ""}`}</span>
                        <small>{hit.raw_hex ?? hit.response_hex ?? "—"}</small>
                        {hit.telecoding && <TelecodingDetails zone={hit.telecoding} />}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="inline-alert">Aucun identifiant supplémentaire trouvé sur cette plage lors du dernier scan.</p>
                )}
              </div>}
              {LAB_MODE && <div className="did-sweep-panel">
                <div className="section-heading">
                  <div><span className="eyebrow">Exploration en lecture seule</span><h3>Balayage de DID (0x22)</h3><p>Envoie une lecture 0x22 pour chaque identifiant de la plage sur {selectedEcu.name}, afin de découvrir ceux réellement supportés au-delà de la liste standard.</p></div>
                </div>
                <div className="did-sweep-form">
                  <label>Début<input value={didSweepStart} onChange={(event) => setDidSweepStart(event.target.value)} placeholder="F180" /></label>
                  <label>Fin<input value={didSweepEnd} onChange={(event) => setDidSweepEnd(event.target.value)} placeholder="F1FF" /></label>
                  <button className="secondary-button" onClick={() => void sweepSelectedEcuDids()} disabled={didSweepBusy}>{didSweepBusy ? "Balayage…" : "Lancer le balayage"}</button>
                </div>
                {didSweepResult && didSweepResult.ecu_key === selectedEcu.key && <div className="did-sweep-results">
                  <p><strong>{didSweepResult.hits.length}</strong> réponse(s) exploitable(s) sur {didSweepResult.scanned_count} identifiant(s) testé(s) · {didSweepResult.unsupported_count} non supporté(s){didSweepResult.timeout_count > 0 && ` · ${didSweepResult.timeout_count} sans réponse`}</p>
                  {didSweepResult.hits.length === 0 ? <p className="inline-alert">Aucun identifiant supplémentaire trouvé dans cette plage.</p> : didSweepResult.hits.map((hit) => (
                    <div className="did-sweep-hit" key={hit.did}>
                      <code>0x{hit.did.toString(16).toUpperCase().padStart(4, "0")}</code>
                      <span>{hit.outcome === "positive" ? "Réponse positive" : `NRC 0x${hit.nrc?.toString(16).toUpperCase().padStart(2, "0")} ${hit.nrc_name ?? ""}`}</span>
                      <small>{hit.raw_hex ?? hit.response_hex ?? "—"}</small>
                      {hit.telecoding && <TelecodingDetails zone={hit.telecoding} />}
                    </div>
                  ))}
                </div>}
              </div>}
            </div>}

            <details className="ecu-inventory-details">
              <summary>Voir l’inventaire complet ({report.ecus.length} calculateurs configurés)</summary>
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
                      <button className="ghost-button" disabled={!ecu.detected} onClick={() => { setSelectedEcuKey(ecu.key); document.querySelector(".ecu-selector")?.scrollIntoView({ behavior: "smooth", block: "center" }); }}>Ouvrir</button>
                    </div>
                    <div className="tag-row">
                      <span>{ecu.optional ? "Optionnel" : "Attendu"}</span>
                      <span>{ecu.confidence}</span>
                      {ecu.dtcs.filter((dtc) => dtc.state === "active").length > 0 && <span className="warn-tag">{ecu.dtcs.filter((dtc) => dtc.state === "active").length} actif(s)</span>}
                      {ecu.dtcs.filter((dtc) => dtc.state === "historical").length > 0 && <span>{ecu.dtcs.filter((dtc) => dtc.state === "historical").length} historique(s)</span>}
                      {ecu.dtcs.filter((dtc) => dtc.state === "not_tested").length > 0 && <span>{ecu.dtcs.filter((dtc) => dtc.state === "not_tested").length} non testé(s)</span>}
                      {ecu.probe_method && <span>Réponse via {ecu.probe_method}</span>}
                      {ecu.active_session !== null && ecu.active_session !== undefined && <span>Session {hexadecimal(ecu.active_session)}</span>}
                    </div>
                    {LAB_MODE && ecu.identification.some((item) => item.error) && <details className="ecu-technical-details">
                      <summary>{ecu.identification.filter((item) => item.error).length} DID refusé(s), absent(s) ou non décodable(s)</summary>
                      {ecu.identification.filter((item) => item.error).map((item) => <div key={item.did}>
                        <code>{item.request_hex ?? `22${item.did.toString(16).toUpperCase()}`}</code>
                        <span>{item.error}</span>
                        <small>{item.response_hex ? `Réponse ${item.response_hex}` : "Aucune réponse"}</small>
                      </div>)}
                    </details>}
                    {LAB_MODE && ecu.probe_attempts && ecu.probe_attempts.length > 0 && <details className="ecu-technical-details">
                      <summary>Preuve de présence et échanges bruts</summary>
                      {ecu.probe_attempts.map((attempt, index) => <div key={`${attempt.request_hex}-${index}`}>
                        <code>{attempt.request_hex}</code>
                        <span>{attempt.outcome === "positive" ? "Réponse positive" : attempt.outcome === "negative_response" ? `NRC ${hexadecimal(attempt.nrc)}` : "Timeout"}</span>
                        <small>{attempt.response_hex ?? attempt.error ?? "Aucune réponse"}</small>
                      </div>)}
                      {ecu.dtc_request_hex && <div><code>{ecu.dtc_request_hex}</code><span>Lecture DTC</span><small>{ecu.dtc_response_hex ?? ecu.dtc_error ?? "Aucune réponse"}</small></div>}
                    </details>}
                    {(ecu.error || ecu.dtc_error) && <p className="inline-alert">{ecu.error ?? ecu.dtc_error}</p>}
                  </div>
                </article>
              ))}
              </div>
            </details>
          </section>
        )}

        {report && <section className="panel dtc-clear-panel">
          <div className="section-heading"><div><span className="eyebrow">Maintenance unitaire contrôlée</span><h2>Effacer la mémoire DTC d’un seul calculateur</h2><p>Le backend lit les défauts avant, exige un acquittement positif, puis relit immédiatement le même ECU.</p></div><span className={`status-pill ${status?.dtc_clear_enabled ? "warning" : "neutral"}`}><i /> {status?.dtc_clear_enabled ? "Armé par configuration" : "Verrouillé"}</span></div>
          <div className="dtc-clear-form">
            <label>Calculateur<select value={dtcClearEcuKey} onChange={(event) => { setDtcClearEcuKey(event.target.value); setDtcClearConfirmation(""); setDtcClearResult(null); }}><option value="">Choisir un ECU</option>{report.ecus.filter((ecu) => ecu.detected).map((ecu) => <option value={ecu.key} key={ecu.key}>{ecu.name} · {ecu.dtcs.length} entrée(s)</option>)}</select></label>
            <div className="dtc-clear-checks">
              <label><input type="checkbox" checked={dtcClearChecks.vehicle_stationary} onChange={(event) => setDtcClearChecks((current) => ({ ...current, vehicle_stationary: event.target.checked }))} /> Véhicule immobilisé</label>
              <label><input type="checkbox" checked={dtcClearChecks.ignition_on_engine_off} onChange={(event) => setDtcClearChecks((current) => ({ ...current, ignition_on_engine_off: event.target.checked }))} /> Contact mis, moteur arrêté</label>
              <label><input type="checkbox" checked={dtcClearChecks.stable_battery_voltage} onChange={(event) => setDtcClearChecks((current) => ({ ...current, stable_battery_voltage: event.target.checked }))} /> Tension batterie stable</label>
              <label><input type="checkbox" checked={dtcClearChecks.report_saved} onChange={(event) => setDtcClearChecks((current) => ({ ...current, report_saved: event.target.checked }))} /> Rapport avant effacement sauvegardé</label>
            </div>
            <label>Confirmation exacte<input value={dtcClearConfirmation} onChange={(event) => setDtcClearConfirmation(event.target.value)} placeholder={dtcClearEcuKey ? `EFFACER ${dtcClearEcuKey.toUpperCase()}` : "Choisir d’abord un ECU"} /></label>
            <button className="danger-button" onClick={() => void clearSelectedEcuDtcs()} disabled={!status?.dtc_clear_enabled || !dtcClearEcuKey || dtcClearConfirmation !== `EFFACER ${dtcClearEcuKey.toUpperCase()}` || !Object.values(dtcClearChecks).every(Boolean) || dtcClearBusy}>{dtcClearBusy ? "Lecture, effacement, contrôle…" : "Effacer cet ECU et vérifier"}</button>
          </div>
          {!status?.dtc_clear_enabled && <p className="inline-alert">Verrou actif : `DTC_CLEAR_ENABLED=false`. Les ECU ABS, BSI, airbag, direction et caméra exigent en plus `SAFETY_ECU_CLEAR_ENABLED=true`.</p>}
          {dtcClearResult && <div className={`regression-result ${dtcClearResult.verified ? "good" : "warning"}`}><strong>{dtcClearResult.verified ? "Effacement contrôlé" : "Effacement accepté, contrôle incomplet"}</strong><span>{dtcClearResult.message}</span><small>{dtcClearResult.before_dtcs.length} avant · {dtcClearResult.after_dtcs.length} après · preuve enregistrée dans le rapport</small>{LAB_MODE && <code>TX {dtcClearResult.request_hex} / RX {dtcClearResult.response_hex ?? "—"}</code>}</div>}
        </section>}
      </div>
    );
  }
