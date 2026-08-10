import type { Dispatch, ReactNode, SetStateAction } from "react";

import { EmptyState } from "../components/ui";
import { formatDate, formatDuration } from "../format";
import type { CaptureStatus, DiscoverySession, OpendbcCatalog, TraceImportResult } from "../types";

type GpsTracking={state:"idle"|"requesting"|"active"|"unavailable"|"denied"|"error";accuracyM?:number;message?:string};
type DiscoveryScreenProps={traceImportBusy:boolean;importDiagnosticTrace:(file:File|undefined)=>Promise<void>;traceImportResult:TraceImportResult|null;capture:CaptureStatus|null;captureName:string;setCaptureName:Dispatch<SetStateAction<string>>;captureNote:string;setCaptureNote:Dispatch<SetStateAction<string>>;captureGpsEnabled:boolean;setCaptureGpsEnabled:Dispatch<SetStateAction<boolean>>;startCapture:(enableLiveDataReads?:boolean)=>Promise<void>;gpsTracking:GpsTracking;liveObdReadOnly:boolean;markerName:string;setMarkerName:Dispatch<SetStateAction<string>>;markerNote:string;setMarkerNote:Dispatch<SetStateAction<string>>;addMarker:(name?:string)=>Promise<void>;markerPresets:string[];stopCapture:()=>Promise<void>;opendbcCatalog:OpendbcCatalog|null;refreshSessions:()=>Promise<void>;sessions:DiscoverySession[];analysisBusy:string;analyzeSession:(sessionId:string,saved?:boolean)=>Promise<void>;analysisContent:ReactNode};

export function DiscoveryScreen({
  traceImportBusy,
  importDiagnosticTrace,
  traceImportResult,
  capture,
  captureName,
  setCaptureName,
  captureNote,
  setCaptureNote,
  captureGpsEnabled,
  setCaptureGpsEnabled,
  startCapture,
  gpsTracking,
  liveObdReadOnly,
  markerName,
  setMarkerName,
  markerNote,
  setMarkerNote,
  addMarker,
  markerPresets,
  stopCapture,
  opendbcCatalog,
  refreshSessions,
  sessions,
  analysisBusy,
  analyzeSession,
  analysisContent
}: DiscoveryScreenProps) {
    return (
      <>
        <section className="workflow-grid">
          <article><span>01</span><strong>Enregistrer</strong><p>Capturer le trafic CAN sans commande applicative.</p></article>
          <article><span>02</span><strong>Marquer</strong><p>Placer le marqueur juste avant l'action, toujours avec le même nom.</p></article>
          <article><span>03</span><strong>Analyser</strong><p>Comparer les fenêtres avant/après hors ligne.</p></article>
          <article><span>04</span><strong>Valider</strong><p>Confirmer sur plusieurs sessions avant intégration.</p></article>
        </section>

        <section className="panel trace-import-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Import & analyse hors véhicule</span>
              <h2>Importer une trace Diagbox</h2>
              <p>Reconstitue les échanges, recense les informations lues et isole les services actifs pour revue. Learn n’émet aucune trame vers la voiture.</p>
            </div>
            <label className={`secondary-button file-button ${traceImportBusy ? "disabled" : ""}`}>
              {traceImportBusy ? "Analyse…" : "Choisir une trace"}
              <input type="file" accept=".log,.txt,.csv,.jsonl" disabled={traceImportBusy} onChange={(event) => { void importDiagnosticTrace(event.target.files?.[0]); event.currentTarget.value = ""; }} />
            </label>
          </div>
          {traceImportResult && <div className="trace-import-result">
            <div className="diagnostic-preflight">
              <div><span>Trames CAN</span><strong>{traceImportResult.frame_count}</strong></div>
              <div><span>Échanges reconstruits</span><strong>{traceImportResult.exchange_count}</strong></div>
              <div><span>Informations observées</span><strong>{traceImportResult.observed_dids.length}</strong></div>
              <div><span>Services actifs isolés</span><strong>{traceImportResult.observed_actions.length}</strong></div>
            </div>
            {traceImportResult.observed_actions.length > 0 && <p className="inline-alert">{traceImportResult.observed_actions.length} commande(s) repérée(s), conservée(s) comme preuve non exécutable jusqu’à validation manuelle.</p>}
            <small>Import {traceImportResult.import_id} · {traceImportResult.unparsed_line_count} ligne(s) non interprétée(s)</small>
          </div>}
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
                <label className="gps-capture-option">
                  <input type="checkbox" checked={captureGpsEnabled} onChange={(event) => setCaptureGpsEnabled(event.target.checked)} />
                  <span><strong>Enregistrer le trajet GPS</strong><small>Position du navigateur, synchronisée avec le CAN</small></span>
                </label>
                <button className="primary-button record-button" onClick={() => void startCapture(false)}>Démarrer la capture passive</button>
              </div>
            ) : (
              <>
                <div className="live-capture">
                  <div><span>Session</span><strong>{capture.name || capture.session_id}</strong></div>
                  <div><span>Direct 6/14</span><strong>{(capture.live_frame_count ?? capture.frame_count).toLocaleString("fr-FR")}</strong></div>
                  <div><span>Diagnostic 3/8</span><strong>{(capture.diagnostic_frame_count ?? 0).toLocaleString("fr-FR")}</strong></div>
                  <div><span>Marqueurs</span><strong>{capture.marker_count}</strong></div>
                  <div><span>GPS</span><strong>{captureGpsEnabled
                    ? capture.gps_point_count
                      ? `${capture.gps_point_count.toLocaleString("fr-FR")} pts · ±${Math.round(capture.gps_last_accuracy_m ?? gpsTracking.accuracyM ?? 0)} m`
                      : gpsTracking.state === "requesting" ? "Autorisation…" : gpsTracking.state === "active" ? "Acquisition…" : "Indisponible"
                    : "Désactivé"}</strong></div>
                  <div><span>Mode</span><strong>{capture.dual_can ? liveObdReadOnly ? "6/14 OBD lecture + 3/8 diag" : "6/14 passif + 3/8 diag" : capture.strict_passive === true ? "Passif strict" : capture.strict_passive === false ? "Observation" : "Vérification…"}</strong></div>
                </div>
                {capture.error && <p className="inline-alert danger-alert">{capture.error}</p>}
                {captureGpsEnabled && gpsTracking.message && gpsTracking.state !== "active" && (
                  <p className="inline-alert">GPS : {gpsTracking.message}</p>
                )}
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
                <div className="session-stats"><span>{session.frame_count.toLocaleString("fr-FR")} trames</span>{Boolean(session.diagnostic_frame_count) && <span>{session.live_frame_count?.toLocaleString("fr-FR")} live / {session.diagnostic_frame_count?.toLocaleString("fr-FR")} diag</span>}<span>{session.marker_count} marqueurs</span></div>
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

        {analysisContent}
      </>
    );
  }
