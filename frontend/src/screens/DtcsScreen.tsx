import type { Dispatch, SetStateAction } from "react";

import { API_BASE } from "../api";
import { EmptyState } from "../components/ui";
import { formatDate, formatIsoDate } from "../format";
import { LAB_MODE } from "../navigation";
import type { CaptureStatus, DiagnosticReportSummary, DiagnosticVehicle, DtcChange, DtcSnapshotResult, DtcValue, Ecu, ObservedDtc, Report, Status } from "../types";

type DtcFilter=DtcValue["state"]|"all";
type DtcsScreenProps={report:Report|null;refreshDiagnosticHistory:(preferredVin?:string,preferredProfile?:string)=>Promise<void>;selectedDiagnosticVin:string;selectDiagnosticVehicle:(vin:string)=>Promise<void>;diagnosticVehicles:DiagnosticVehicle[];selectDiagnosticReport:(scanId:string)=>Promise<void>;diagnosticReportHistory:DiagnosticReportSummary[];selectedDiagnosticVehicle:DiagnosticVehicle|null;observedDtcs:ObservedDtc[];extendedProbeEnabled:boolean;setExtendedProbeEnabled:Dispatch<SetStateAction<boolean>>;scan:()=>Promise<void>;busy:boolean;diagnosticReady:boolean;capture:CaptureStatus|null;status:Status|null;dtcFilter:DtcFilter;setDtcFilter:Dispatch<SetStateAction<DtcFilter>>;detectedEcus:Ecu[];visibleDtcs:Array<{ecu:Ecu;dtc:DtcValue}>;dtcSnapshotResults:Record<string,DtcSnapshotResult>;readDtcSnapshot:(ecuKey:string,dtc:DtcValue)=>Promise<void>;dtcSnapshotBusy:string};

export function DtcsScreen({
  report,
  refreshDiagnosticHistory,
  selectedDiagnosticVin,
  selectDiagnosticVehicle,
  diagnosticVehicles,
  selectDiagnosticReport,
  diagnosticReportHistory,
  selectedDiagnosticVehicle,
  observedDtcs,
  extendedProbeEnabled,
  setExtendedProbeEnabled,
  scan,
  busy,
  diagnosticReady,
  capture,
  status,
  dtcFilter,
  setDtcFilter,
  detectedEcus,
  visibleDtcs,
  dtcSnapshotResults,
  readDtcSnapshot,
  dtcSnapshotBusy
}: DtcsScreenProps) {
    const filterLabels: Array<{ key: DtcValue["state"] | "all"; label: string; count: number }> = [
      { key: "active", label: "Actifs", count: report?.dtc_summary.active ?? 0 },
      { key: "historical", label: "Historiques", count: report?.dtc_summary.historical ?? 0 },
      { key: "not_tested", label: "Non testés", count: report?.dtc_summary.not_tested ?? 0 },
      { key: "all", label: "Tous", count: report?.dtc_summary.total ?? 0 },
    ];
    const renderChanges = (changes: DtcChange[], kind: "appeared" | "resolved" | "changed") => changes.map((change) => (
      <article className={`comparison-change ${kind}`} key={`${kind}-${change.ecu_key}-${change.raw_hex}`}>
        <code>{change.code}</code>
        <div>
          <strong>{change.title ?? "Description spécifique inconnue"}</strong>
          <span>{change.ecu_name}</span>
        </div>
        <small>{kind === "appeared"
          ? `Apparu · ${change.after_state ?? "—"}`
          : kind === "resolved"
            ? `Disparu · ${change.before_state ?? "—"}`
            : `${change.before_state ?? "—"} → ${change.after_state ?? "—"}`}</small>
      </article>
    ));
    return (
      <div className="dtc-page">
        <section className="panel diagnostic-history-toolbar">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Historique par véhicule</span>
              <h2>Rapports enregistrés automatiquement</h2>
              <p>Chaque diagnostic est conservé localement sous son VIN, sans mélanger Peugeot et Fiat.</p>
            </div>
            <button className="ghost-button" onClick={() => void refreshDiagnosticHistory(selectedDiagnosticVin || undefined)}>Actualiser</button>
          </div>
          <div className="diagnostic-history-controls">
            <label>Véhicule
              <select value={selectedDiagnosticVin} onChange={(event) => void selectDiagnosticVehicle(event.target.value)}>
                {!diagnosticVehicles.length && <option value="">Aucun VIN enregistré</option>}
                {diagnosticVehicles.map((vehicle) => <option value={vehicle.vin} key={vehicle.vin}>{vehicle.manufacturer} {vehicle.model} · {vehicle.vin}</option>)}
              </select>
            </label>
            <label>Diagnostic
              <select value={report?.scan_id ?? ""} onChange={(event) => void selectDiagnosticReport(event.target.value)} disabled={!diagnosticReportHistory.length}>
                {!diagnosticReportHistory.length && <option value="">Aucun diagnostic</option>}
                {diagnosticReportHistory.map((item) => <option value={item.scan_id} key={item.scan_id}>{formatIsoDate(item.scanned_at)} · {item.dtc_summary.active} actif(s)</option>)}
              </select>
            </label>
            <div className="diagnostic-history-identity">
              <span>VIN sélectionné</span>
              <strong>{selectedDiagnosticVehicle?.vin ?? report?.vin ?? "Non identifié"}</strong>
              <small>{selectedDiagnosticVehicle ? `${selectedDiagnosticVehicle.manufacturer} ${selectedDiagnosticVehicle.model} · ${selectedDiagnosticVehicle.scan_count} scan(s)` : "Lis d’abord l’identité du véhicule"}</small>
            </div>
            <div className="diagnostic-export-actions">
              {report?.scan_id ? <>
                <a className="secondary-button" href={`${API_BASE}/api/diagnostic/reports/${encodeURIComponent(report.scan_id)}/export?format=html`} target="_blank" rel="noreferrer">Rapport HTML</a>
                <a className="ghost-button" href={`${API_BASE}/api/diagnostic/reports/${encodeURIComponent(report.scan_id)}/export?format=json`} target="_blank" rel="noreferrer">JSON brut</a>
              </> : <span>Aucun rapport à exporter</span>}
            </div>
          </div>
        </section>

        {observedDtcs.length > 0 && (
          <section className="panel observed-dtc-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Constat enregistré sur ce véhicule</span>
                <h2>Défauts relevés</h2>
                <p>Ces codes restent visibles après redémarrage, indépendamment d'un nouveau scan.</p>
              </div>
              <span className="candidate-count">{observedDtcs.length} sauvegardés</span>
            </div>
            <div className="dtc-list">
              {observedDtcs.map((dtc) => (
                <article className="dtc-card observed" key={`${dtc.code}-${dtc.ecu_key ?? "unknown"}`}>
                  <div className="dtc-code"><code>{dtc.code}</code><span>{dtc.ecu_name}</span></div>
                  <div className="dtc-description">
                    <strong>{dtc.title ?? "Description spécifique inconnue"}</strong>
                    <p>{dtc.note ?? "Code relevé manuellement; état UDS non fourni."}</p>
                    <div className="tag-row">
                      <span className="warn-tag">À confirmer par lecture UDS</span>
                      <span>Statut UDS inconnu</span>
                      {dtc.catalogs.slice(0, 3).map((catalog) => <span key={catalog}>{catalog}</span>)}
                      {dtc.catalogs.length > 3 && <span>+{dtc.catalogs.length - 3} catalogues</span>}
                    </div>
                  </div>
                  <div className="dtc-meta">
                    <span>Constat local</span>
                    <small>{dtc.recorded_at ? formatDate(new Date(dtc.recorded_at).getTime() * 1000) : "Date inconnue"}</small>
                  </div>
                </article>
              ))}
            </div>
            <p className="inline-alert">Un code seul ne confirme ni que le défaut est actuellement actif, ni sa cause mécanique. Un prochain scan UDS permettra d'ajouter le calculateur, le sous-type et l'état exact.</p>
          </section>
        )}

        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Lecture UDS 0x19</span>
              <h2>Dernier scan des calculateurs</h2>
              {report && <p>{report.manufacturer} {report.model} · {report.vin ?? "VIN non rattaché"} · {formatIsoDate(report.scanned_at)}</p>}
            </div>
            <div className="section-actions">
              <label className="extended-probe-toggle" title="Ajoute un balayage DID sur les calculateurs moteur et télématique (0x0000-0x01FF, identifiants non documentés) ainsi que sur la caméra/CVM et le radar avant (0x2100-0x21FF, zones de télécodage). Rallonge le scan.">
                <input type="checkbox" checked={extendedProbeEnabled} onChange={(event) => setExtendedProbeEnabled(event.target.checked)} /> Recherche approfondie (injection, GPS, caméra, radar)
              </label>
              <span className="locked-label">Effacement verrouillé</span>
              <button className="secondary-button" onClick={scan} disabled={busy || !diagnosticReady}>{busy ? "Scan…" : "Nouveau scan"}</button>
            </div>
          </div>
          {!report ? (
            <EmptyState
              title={diagnosticReady ? "Aucun rapport de scan disponible" : "Diagnostic actif non prêt"}
              text={diagnosticReady
                ? "Lance un scan pour vérifier les défauts présents et récupérer leur état UDS."
                : capture?.active
                  ? "Arrête la capture CAN avant d’interroger les calculateurs."
                  : status?.can_tx_enabled
                    ? "Valide d’abord la connexion ESP32 diagnostic depuis le Dashboard direct."
                    : "La lecture DTC nécessite un firmware diagnostic et des requêtes UDS en lecture seule."}
              action={<button className="primary-button" disabled={!diagnosticReady} onClick={scan}>{diagnosticReady ? "Scanner le véhicule" : "Connexion diagnostic requise"}</button>}
            />
          ) : (
            <>
              <div className="dtc-summary-grid">
                <button className={dtcFilter === "active" ? "active" : ""} onClick={() => setDtcFilter("active")}><span>Défauts actifs</span><strong>{report.dtc_summary.active}</strong><small>À traiter maintenant</small></button>
                <button className={dtcFilter === "historical" ? "active" : ""} onClick={() => setDtcFilter("historical")}><span>Historiques</span><strong>{report.dtc_summary.historical}</strong><small>Mémorisés, non actuels</small></button>
                <button className={dtcFilter === "not_tested" ? "active" : ""} onClick={() => setDtcFilter("not_tested")}><span>Tests non exécutés</span><strong>{report.dtc_summary.not_tested}</strong><small>Pas des pannes confirmées</small></button>
                <div><span>ECU affectés</span><strong>{report.dtc_summary.affected_ecus}</strong><small>{detectedEcus.length}/{report.ecus.length} ECU détectés</small></div>
              </div>
              <div className="dtc-filter-tabs">
                {filterLabels.map((filter) => <button className={dtcFilter === filter.key ? "active" : ""} onClick={() => setDtcFilter(filter.key)} key={filter.key}>{filter.label}<span>{filter.count}</span></button>)}
              </div>
              {dtcFilter === "not_tested" && <p className="dtc-technical-note"><strong>Information technique, pas une panne :</strong> le calculateur indique que le moniteur n’a pas encore terminé ou exécuté son test depuis l’effacement ou le cycle courant.</p>}
              {visibleDtcs.length === 0 ? (
                <EmptyState
                  title={dtcFilter === "active" ? "Aucun défaut actif" : `Aucun élément dans « ${filterLabels.find((item) => item.key === dtcFilter)?.label ?? dtcFilter} »`}
                  text={dtcFilter === "active" ? "Ce scan ne contient aucune panne confirmée comme présente au moment de la lecture." : "Change de filtre pour consulter les autres états UDS."}
                />
              ) : <div className="dtc-list">
                {visibleDtcs.map(({ ecu, dtc }) => {
                  const snapshotKey = `${ecu.key}-${dtc.raw_hex}`;
                  const snapshot = dtcSnapshotResults[snapshotKey];
                  return (
                  <article className={`dtc-card ${dtc.state}`} key={`${ecu.key}-${dtc.raw_hex}-${dtc.status_hex}`}>
                    <div className="dtc-code"><code>{dtc.code}</code><span>{ecu.name}</span></div>
                    <div className="dtc-description">
                      <strong>{dtc.title ?? "Description spécifique inconnue"}</strong>
                      <p>{dtc.state_detail}</p>
                      <div className="tag-row"><span className={`dtc-state-tag ${dtc.state}`}>{dtc.state_label}</span>{dtc.status_labels.map((label) => <span key={label}>{label}</span>)}</div>
                      {LAB_MODE && <>
                        {dtc.failure_type_label && <small>Type de défaut : {dtc.failure_type_label} (0x{dtc.failure_type.toString(16).toUpperCase().padStart(2, "0")})</small>}
                        <button className="ghost-button" onClick={() => void readDtcSnapshot(ecu.key, dtc)} disabled={dtcSnapshotBusy === snapshotKey}>{dtcSnapshotBusy === snapshotKey ? "Lecture…" : "Lire la trame gelée (0x19/0x04)"}</button>
                        {snapshot && (snapshot.error
                          ? <p className="inline-alert">{snapshot.error}</p>
                          : <div className="dtc-snapshot-result">
                              <span>Enregistrement {snapshot.snapshot_record_number ?? "—"} · {snapshot.identifier_count ?? 0} identifiant(s)</span>
                              <code>{snapshot.raw_data_hex || "Aucune donnée"}</code>
                            </div>)}
                      </>}
                    </div>
                    <div className="dtc-meta">
                      <span>{dtc.state_label}</span>
                      {LAB_MODE && <code>Statut 0x{dtc.status_hex}</code>}
                      <small>{dtc.catalogs.join(", ") || "Catalogue inconnu"}</small>
                    </div>
                  </article>
                  );
                })}
              </div>}
            </>
          )}
        </section>

        {report?.comparison && (
          <section className="panel diagnostic-comparison">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Comparaison automatique avant / après</span>
                <h2>Évolution depuis le diagnostic précédent</h2>
                <p>Comparaison limitée aux {report.comparison.comparable_ecus.length} ECU dont la lecture DTC a réussi dans les deux scans.</p>
              </div>
              <span className="candidate-count">{report.comparison.appeared.length + report.comparison.resolved.length + report.comparison.changed.length} changement(s)</span>
            </div>
            {report.comparison.appeared.length + report.comparison.resolved.length + report.comparison.changed.length === 0 ? (
              <EmptyState title="Aucune évolution significative" text={`${report.comparison.unchanged} défaut(s) actif(s) ou historique(s) inchangé(s). Les états « non testé » ne sont pas interprétés comme des pannes.`} />
            ) : <div className="comparison-list">
              {renderChanges(report.comparison.appeared, "appeared")}
              {renderChanges(report.comparison.changed, "changed")}
              {renderChanges(report.comparison.resolved, "resolved")}
            </div>}
            {report.comparison.excluded_ecus.length > 0 && <p className="comparison-coverage">ECU exclus faute de lecture comparable : {report.comparison.excluded_ecus.join(", ")}.</p>}
          </section>
        )}
      </div>
    );
  }
