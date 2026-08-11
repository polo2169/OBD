import type { Dispatch, SetStateAction } from "react";

import { TelecodingDetails } from "../components/TelecodingDetails";
import { TelecodingWorkspace } from "../components/TelecodingWorkspace";
import { EmptyState } from "../components/ui";
import { ECU_LIVE_CATALOG, LAB_MODE } from "../navigation";
import type { EcuLiveView, View } from "../navigation";
import type { ClearDtcResult, DidSweepResult, DidValue, Ecu, EcuResetResult, PassiveSensorSnapshot, PsaAdvancedCatalog, Report, Status } from "../types";

const SAFETY_CRITICAL_ECU_KEYS=new Set(["abs_esp","airbag","bsi","front_camera","power_steering"]);
type LabChecks={vehicle_stationary:boolean;ignition_on_engine_off:boolean;stable_battery_voltage:boolean;workshop_or_private_site:boolean};
type DtcClearChecks={vehicle_stationary:boolean;ignition_on_engine_off:boolean;stable_battery_voltage:boolean;report_saved:boolean};
type LiveSafetyEvidence={speedKnown:boolean;stationary:boolean;rpmKnown:boolean;engineOff:boolean;batteryKnown:boolean;batteryStable:boolean;batteryValue:number|null};
type EcuLiveScreenProps = {
  ecuKey: EcuLiveView;
  psaCatalog: PsaAdvancedCatalog | null;
  report: Report | null;
  ecuLiveReport: Ecu | null;
  passiveSensors: PassiveSensorSnapshot | null;
  psaVehicleCompatible: boolean;
  diagnosticReady: boolean;
  psaLabChecks: LabChecks;
  setPsaLabChecks: Dispatch<SetStateAction<LabChecks>>;
  ecuWatchValues: Record<string, DidValue>;
  readEcuLiveReport: (ecuKey: string) => Promise<void>;
  ecuLiveReportBusy: boolean;
  setView: Dispatch<SetStateAction<View>>;
  didSweepStart: string;
  setDidSweepStart: Dispatch<SetStateAction<string>>;
  didSweepEnd: string;
  setDidSweepEnd: Dispatch<SetStateAction<string>>;
  sweepSelectedEcuDids: (ecuKey?: string) => Promise<void>;
  didSweepBusy: boolean;
  didSweepResult: DidSweepResult | null;
  liveSafetyEvidence: LiveSafetyEvidence;
  effectivePsaLabChecks: LabChecks;
  ecuResetConfirmation: string;
  setEcuResetConfirmation: Dispatch<SetStateAction<string>>;
  resetSelectedEcu: (ecuKey: string) => Promise<void>;
  psaLabChecksComplete: boolean;
  ecuResetBusy: boolean;
  ecuResetResult: EcuResetResult | null;
  status: Status | null;
  dtcClearChecks: DtcClearChecks;
  setDtcClearChecks: Dispatch<SetStateAction<DtcClearChecks>>;
  dtcClearConfirmation: string;
  setDtcClearConfirmation: Dispatch<SetStateAction<string>>;
  clearSelectedEcuDtcs: (ecuKey?: string) => Promise<void>;
  dtcClearBusy: boolean;
  dtcClearResult: ClearDtcResult | null;
};

export function EcuLiveScreen({
  ecuKey,
  psaCatalog,
  report,
  ecuLiveReport,
  passiveSensors,
  psaVehicleCompatible,
  diagnosticReady,
  psaLabChecks,
  setPsaLabChecks,
  ecuWatchValues,
  readEcuLiveReport,
  ecuLiveReportBusy,
  setView,
  didSweepStart,
  setDidSweepStart,
  didSweepEnd,
  setDidSweepEnd,
  sweepSelectedEcuDids,
  didSweepBusy,
  didSweepResult,
  liveSafetyEvidence,
  effectivePsaLabChecks,
  ecuResetConfirmation,
  setEcuResetConfirmation,
  resetSelectedEcu,
  psaLabChecksComplete,
  ecuResetBusy,
  ecuResetResult,
  status,
  dtcClearChecks,
  setDtcClearChecks,
  dtcClearConfirmation,
  setDtcClearConfirmation,
  clearSelectedEcuDtcs,
  dtcClearBusy,
  dtcClearResult
}: EcuLiveScreenProps) {
    const catalog = ECU_LIVE_CATALOG[ecuKey];
    const psaEcuInfo = psaCatalog?.ecus.find((item) => item.key === ecuKey) ?? null;
    const scannedEcu = report?.ecus.find((item) => item.key === ecuKey) ?? null;
    const activeReport = ecuLiveReport?.key === ecuKey ? ecuLiveReport : null;
    const ecuInfo = activeReport ?? scannedEcu;
    const ecuDtcs = ecuInfo?.dtcs ?? [];
    const actionableDtcs = ecuDtcs.filter((item) => item.actionable);
    const notTestedDtcs = ecuDtcs.filter((item) => item.state === "not_tested");
    const identification = ecuInfo?.identification ?? [];
    const sparePartNumber = identification.find((item) => item.did === 0xF187 && !item.error);
    const psaZa = identification.find((item) => item.did === 0xF080 && !item.error);
    const psaZaRaw = String(psaZa?.raw_hex ?? "").replace(/[^0-9A-F]/gi, "").toUpperCase();
    const observedPsaReferences = ecuKey === "abs_esp" && psaZaRaw.length >= 24
      ? [psaZaRaw.slice(0, 10), psaZaRaw.slice(14, 24)].filter(
        (value, index, values) => value.length === 10 && !/^F+$/.test(value) && values.indexOf(value) === index,
      )
      : [];
    const liveSignals = (passiveSensors?.signals ?? []).filter(
      (signal) => psaEcuInfo?.family && signal.ecu_family === psaEcuInfo.family,
    );
    const zones = psaEcuInfo?.telecoding_zones ?? [];
    const watchReady = psaVehicleCompatible && diagnosticReady && zones.length > 0;
    const psaReadReady = psaVehicleCompatible && diagnosticReady;
    const updateLabCheck = (key: keyof typeof psaLabChecks, checked: boolean) => {
      setPsaLabChecks((current) => ({ ...current, [key]: checked }));
    };

    return (
      <div className="injection-page">
        <section className="panel injection-gate">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Lecture en direct · aucune commande d'actionneur</span>
              <h2>{catalog.name}</h2>
              <p>Signaux CAN décodés attribués à ce calculateur, complétés par une petite liste de zones UDS surveillées en continu. Lecture seule.</p>
            </div>
            <span className={`status-pill ${ecuInfo?.detected ? "good" : "neutral"}`}><i /> {ecuInfo?.detected ? (activeReport ? "Détecté · lecture directe" : "Détecté au dernier scan") : "Statut inconnu"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Famille / variante</span><strong>{psaEcuInfo?.family ?? "—"}{psaEcuInfo?.telecoding_variant ? ` · ${psaEcuInfo.telecoding_variant}` : ""}</strong></div>
            <div><span>Adressage diagnostic</span><strong>{psaEcuInfo?.request_id ? `0x${psaEcuInfo.request_id.toString(16).toUpperCase()} → 0x${psaEcuInfo.response_id?.toString(16).toUpperCase()}` : "Non documenté"}</strong></div>
            <div><span>Zones UDS connues</span><strong>{zones.length || "—"}</strong></div>
            <div><span>Surveillance UDS</span><strong>{watchReady ? "Active" : psaVehicleCompatible ? "En attente" : "Indisponible (non PSA)"}</strong></div>
          </div>
          {!psaVehicleCompatible && <p className="inline-alert">Le véhicule actif n’est pas un profil PSA compatible : seuls les signaux CAN décodés ci-dessous restent disponibles, pas la surveillance UDS.</p>}
        </section>

        <section className="injection-summary-grid">
          <article><span>Signaux CAN attribués</span><strong>{liveSignals.length}</strong><small>Décodage OpenDBC, catégorisé par calculateur</small></article>
          <article><span>Zones UDS surveillées</span><strong>{zones.length}</strong><small>Catalogue PyPSADiag connu pour {psaEcuInfo?.family ?? "cette famille"}</small></article>
          <article><span>Valeurs UDS reçues</span><strong>{Object.keys(ecuWatchValues).length}</strong><small>Depuis l’ouverture de cette page</small></article>
          <article><span>Défauts à traiter</span><strong>{actionableDtcs.length}</strong><small>{ecuDtcs.length} entrée(s) mémoire · {notTestedDtcs.length} test(s) non exécuté(s)</small></article>
        </section>

        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Identification UDS · F18x</span>
              <h2>Référence &amp; identification</h2>
              <p>Lecture directe de ce seul calculateur (pas un scan complet) : version logicielle, numéro de série, et référence pièce constructeur pour commander le bon échange standard.</p>
            </div>
            <button className="primary-button" onClick={() => void readEcuLiveReport(ecuKey)} disabled={ecuLiveReportBusy || !diagnosticReady}>{ecuLiveReportBusy ? "Lecture…" : "Lire les défauts et la référence"}</button>
          </div>
          {sparePartNumber && (
            <div className="psa-zone-result">
              <div><span>Référence pièce constructeur</span><strong>{String(sparePartNumber.value)}</strong></div>
              <code>DID 0xF187</code>
              <small>À communiquer telle quelle à un vendeur de pièces PSA pour l’échange standard.</small>
            </div>
          )}
          {observedPsaReferences.length > 0 && (
            <div className="psa-zone-result">
              <div><span>Références PSA extraites de la zone ZA</span><strong>{observedPsaReferences.join(" · ")}</strong></div>
              <code>F080 · {psaEcuInfo?.telecoding_variant ?? ecuInfo?.aliases.find((item) => item === "ESP90") ?? "variante à confirmer"}</code>
              <small>Pour cet ESP : Bosch ESP 9.0 / ESP90 identifié sur le véhicule. La valeur brute reste conservée ci-dessous.</small>
            </div>
          )}
          {identification.length > 0 ? (
            <div className="ecu-identification-list">
              {identification.filter((item) => !item.error).map((item) => (
                <article key={item.did}>
                  <span>{item.name}</span>
                  <strong>{String(item.value ?? "—")}</strong>
                  <small>{item.source ?? "Lecture véhicule"} · confiance {item.confidence}</small>
                </article>
              ))}
            </div>
          ) : (
            <p className="inline-alert">{diagnosticReady ? "Aucune identification lue pour l’instant — lance la lecture ci-dessus." : "Connecte l’ESP32 et valide la liaison diagnostic pour lire ce calculateur."}</p>
          )}
        </section>

        <section className="panel">
          <div className="section-heading">
            <div><span className="eyebrow">CAN passif décodé</span><h2>Signaux en direct</h2><p>{liveSignals.length ? "Rafraîchi automatiquement pendant une capture active." : "Démarre une capture (Live Data) pour voir les signaux attribués à ce calculateur."}</p></div>
            <button className="secondary-button" onClick={() => setView("sensors")}>Voir tous les signaux</button>
          </div>
          {liveSignals.length === 0 ? (
            <EmptyState title="Aucun signal attribué" text="Soit ce calculateur ne diffuse rien sur le bus observé, soit ses messages ne sont pas encore rattachés à sa famille dans le décodeur." />
          ) : (
            <div className="sensor-live-table">
              {liveSignals.map((signal) => (
                <article className={`sensor-live-row ${signal.confidence} ${signal.customized ? "customized" : ""}`} key={signal.key}>
                  <div className="sensor-live-name">
                    <span>{signal.category}{signal.essential ? " · essentiel" : ""}</span>
                    <strong>{signal.display_name}</strong>
                    <p>{signal.description}</p>
                  </div>
                  <div className="sensor-live-value">
                    <strong>{String(signal.value ?? "—")}</strong>
                    <span>{signal.unit || "sans unité"}</span>
                  </div>
                  <div className="sensor-live-source">
                    <code>CAN constructeur décodé</code>
                    <span>{signal.confidence === "validated" ? "Validé sur le véhicule" : "Définition OpenDBC à confirmer"}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="panel did-sweep-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">UDS 0x22 · zones connues</span>
              <h2>Surveillance des zones</h2>
              <p>{zones.length ? `Interroge en boucle (1 zone toutes les 1,2 s) les ${zones.length} zone(s) documentée(s) ou confirmée(s) sur ce véhicule pour ${psaEcuInfo?.telecoding_variant ?? psaEcuInfo?.family ?? "ce calculateur"}.` : "Aucune zone UDS documentée pour cette famille de calculateur — seul le balayage manuel ci-dessous peut en découvrir."}</p>
            </div>
          </div>
          {zones.length > 0 && (
            <div className="did-sweep-results">
              {zones.map((zone) => {
                const value = ecuWatchValues[zone.did];
                return (
                  <div className="did-sweep-hit" key={zone.did}>
                    <code>0x{zone.did}</code>
                    <span>{zone.name}</span>
                    <small>{value ? (value.error ?? value.raw_hex ?? String(value.value ?? "—")) : watchReady ? "En attente de lecture…" : "Surveillance inactive"}</small>
                    {value?.telecoding && <TelecodingDetails zone={value.telecoding} />}
                  </div>
                );
              })}
            </div>
          )}
          <p className="inline-alert">{ecuKey === "abs_esp"
            ? "Ces zones sont des données de configuration, pas des mesures analogiques. Pour l’ESP90, 0x2100 et 0x2101 sont décodables via PyPSADiag; 0x2102 et 0x2103 sont confirmées en lecture mais leur sens détaillé reste inconnu. L’écriture ESP demeure verrouillée tant que la clé application exacte n’est pas prouvée."
            : "Aucune zone connue ci-dessus ne doit être interprétée comme une mesure analogique sans définition explicite. Une réponse brute reste un candidat à confirmer, pas une valeur physique validée."}</p>
          <div className="did-sweep-form">
            <label>Début<input value={didSweepStart} onChange={(event) => setDidSweepStart(event.target.value)} placeholder="0000" /></label>
            <label>Fin<input value={didSweepEnd} onChange={(event) => setDidSweepEnd(event.target.value)} placeholder="01FF" /></label>
            <button className="secondary-button" onClick={() => void sweepSelectedEcuDids(ecuKey)} disabled={didSweepBusy || !psaVehicleCompatible}>{didSweepBusy ? "Balayage…" : "Lancer un balayage DID"}</button>
          </div>
          {didSweepResult && didSweepResult.ecu_key === ecuKey && (
            <div className="did-sweep-results">
              <p><strong>{didSweepResult.hits.length}</strong> réponse(s) exploitable(s) sur {didSweepResult.scanned_count} identifiant(s) testé(s) · {didSweepResult.unsupported_count} non supporté(s){didSweepResult.timeout_count > 0 && ` · ${didSweepResult.timeout_count} sans réponse`}</p>
              {didSweepResult.hits.length === 0 ? <p className="inline-alert">Aucun identifiant supplémentaire trouvé dans cette plage.</p> : didSweepResult.hits.map((hit) => (
                <div className="did-sweep-hit" key={hit.did}>
                  <code>0x{hit.did.toString(16).toUpperCase().padStart(4, "0")}</code>
                  <span>{hit.outcome === "positive" ? "Réponse positive" : `NRC 0x${hit.nrc?.toString(16).toUpperCase().padStart(2, "0")} ${hit.nrc_name ?? ""}`}</span>
                  <small>{hit.raw_hex ?? hit.response_hex ?? "—"}</small>
                  {hit.telecoding && <TelecodingDetails zone={hit.telecoding} />}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel dtc-clear-panel">
          <div className="section-heading">
            <div><span className="eyebrow">UDS 0x11 · redémarrage matériel</span><h2>Redémarrer ce calculateur</h2><p>Envoie un ECUReset (hardReset). Le calculateur redémarre et reste injoignable quelques secondes ; ses fonctions s’interrompent brièvement pendant le reboot.</p></div>
            <span className={`status-pill ${psaCatalog?.ecu_reset_enabled ? "warning" : "neutral"}`}><i /> {psaCatalog?.ecu_reset_enabled ? "Armé par configuration" : "Verrouillé"}</span>
          </div>
          <div className="dtc-clear-form">
            <div className="dtc-clear-checks">
              <label><input type="checkbox" disabled={liveSafetyEvidence.speedKnown} checked={effectivePsaLabChecks.vehicle_stationary} onChange={(event) => updateLabCheck("vehicle_stationary", event.target.checked)} /> Véhicule immobilisé</label>
              <label><input type="checkbox" disabled={liveSafetyEvidence.rpmKnown} checked={effectivePsaLabChecks.ignition_on_engine_off} onChange={(event) => updateLabCheck("ignition_on_engine_off", event.target.checked)} /> Contact mis, moteur arrêté</label>
              <label><input type="checkbox" disabled={liveSafetyEvidence.batteryKnown} checked={effectivePsaLabChecks.stable_battery_voltage} onChange={(event) => updateLabCheck("stable_battery_voltage", event.target.checked)} /> Tension batterie stable</label>
              <label><input type="checkbox" checked={effectivePsaLabChecks.workshop_or_private_site} onChange={(event) => updateLabCheck("workshop_or_private_site", event.target.checked)} /> Atelier ou site privé</label>
            </div>
            <label>Confirmation exacte<input value={ecuResetConfirmation} onChange={(event) => setEcuResetConfirmation(event.target.value)} placeholder={`REDEMARRER ${ecuKey.toUpperCase()}`} /></label>
            <button
              className="danger-button"
              onClick={() => void resetSelectedEcu(ecuKey)}
              disabled={!psaCatalog?.ecu_reset_enabled || !psaReadReady || !psaLabChecksComplete || ecuResetConfirmation !== `REDEMARRER ${ecuKey.toUpperCase()}` || ecuResetBusy}
            >{ecuResetBusy ? "Redémarrage…" : "Redémarrer ce calculateur"}</button>
          </div>
          {!psaCatalog?.ecu_reset_enabled && <p className="inline-alert">Verrou actif : `PSA_ECU_RESET_ENABLED=false`.</p>}
          {ecuResetResult && ecuResetResult.ecu_key === ecuKey && <div className={`regression-result ${ecuResetResult.reset ? "good" : "warning"}`}><strong>{ecuResetResult.reset ? "Commande envoyée" : "Échec"}</strong><span>{ecuResetResult.message}</span>{LAB_MODE && ecuResetResult.response_hex && <code>RX {ecuResetResult.response_hex}</code>}</div>}
        </section>

        <section className="panel dtc-clear-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Maintenance unitaire contrôlée</span><h2>Effacer la mémoire DTC de ce calculateur</h2><p>Le backend lit les défauts avant, exige un acquittement positif, puis relit immédiatement le même ECU pour vérifier.</p></div>
            <span className={`status-pill ${status?.dtc_clear_enabled ? "warning" : "neutral"}`}><i /> {status?.dtc_clear_enabled ? "Armé par configuration" : "Verrouillé"}</span>
          </div>
          <div className="dtc-clear-form">
            <div className="dtc-clear-checks">
              <label><input type="checkbox" checked={dtcClearChecks.vehicle_stationary} onChange={(event) => setDtcClearChecks((current) => ({ ...current, vehicle_stationary: event.target.checked }))} /> Véhicule immobilisé</label>
              <label><input type="checkbox" checked={dtcClearChecks.ignition_on_engine_off} onChange={(event) => setDtcClearChecks((current) => ({ ...current, ignition_on_engine_off: event.target.checked }))} /> Contact mis, moteur arrêté</label>
              <label><input type="checkbox" checked={dtcClearChecks.stable_battery_voltage} onChange={(event) => setDtcClearChecks((current) => ({ ...current, stable_battery_voltage: event.target.checked }))} /> Tension batterie stable</label>
              <label><input type="checkbox" checked={dtcClearChecks.report_saved} onChange={(event) => setDtcClearChecks((current) => ({ ...current, report_saved: event.target.checked }))} /> Rapport avant effacement sauvegardé</label>
            </div>
            <label>Confirmation exacte<input value={dtcClearConfirmation} onChange={(event) => setDtcClearConfirmation(event.target.value)} placeholder={`EFFACER ${ecuKey.toUpperCase()}`} /></label>
            <button
              className="danger-button"
              onClick={() => void clearSelectedEcuDtcs(ecuKey)}
              disabled={!status?.dtc_clear_enabled || dtcClearConfirmation !== `EFFACER ${ecuKey.toUpperCase()}` || !Object.values(dtcClearChecks).every(Boolean) || dtcClearBusy}
            >{dtcClearBusy ? "Lecture, effacement, contrôle…" : "Effacer cet ECU et vérifier"}</button>
          </div>
          {!status?.dtc_clear_enabled && <p className="inline-alert">Verrou actif : `DTC_CLEAR_ENABLED=false`.{SAFETY_CRITICAL_ECU_KEYS.has(ecuKey) && " Ce calculateur exige en plus `SAFETY_ECU_CLEAR_ENABLED=true`."}</p>}
          {status?.dtc_clear_enabled && SAFETY_CRITICAL_ECU_KEYS.has(ecuKey) && !status?.safety_ecu_clear_enabled && <p className="inline-alert">Ce calculateur est classé sensible : `SAFETY_ECU_CLEAR_ENABLED=true` requis en plus de `DTC_CLEAR_ENABLED`.</p>}
          {dtcClearResult && dtcClearResult.ecu_key === ecuKey && <div className={`regression-result ${dtcClearResult.verified ? "good" : "warning"}`}><strong>{dtcClearResult.verified ? "Effacement contrôlé" : "Effacement accepté, contrôle incomplet"}</strong><span>{dtcClearResult.message}</span><small>{dtcClearResult.before_dtcs.length} avant · {dtcClearResult.after_dtcs.length} après</small>{LAB_MODE && <code>TX {dtcClearResult.request_hex} / RX {dtcClearResult.response_hex ?? "—"}</code>}</div>}
        </section>

        {psaEcuInfo && (
          <TelecodingWorkspace
            ecuKey={ecuKey}
            readReady={psaReadReady}
            writeEnabled={Boolean(psaCatalog?.telecoding_write_enabled)}
            securityAccessEnabled={Boolean(psaCatalog?.security_access_enabled)}
            readOnly={psaCatalog?.read_only ?? true}
            labChecksComplete={psaLabChecksComplete}
            labChecks={psaLabChecks}
            effectiveLabChecks={effectivePsaLabChecks}
            lockedChecks={{
              vehicle_stationary: liveSafetyEvidence.speedKnown,
              ignition_on_engine_off: liveSafetyEvidence.rpmKnown,
              stable_battery_voltage: liveSafetyEvidence.batteryKnown,
            }}
            setLabChecks={setPsaLabChecks}
          />
        )}

        <section className="panel injection-dtc-panel">
          <div className="section-heading">
            <div><span className="eyebrow">{catalog.name}</span><h2>Défauts liés à ce calculateur</h2><p>{ecuInfo ? `${ecuDtcs.length} défaut(s) ${activeReport ? "lu(s) à l’instant" : "remonté(s) au dernier inventaire ECU"}.` : "Lance l’inventaire ECU ou le bouton « Lire les défauts et la référence » ci-dessus."}</p></div>
            <button className="secondary-button" onClick={() => setView("ecus")}>{report ? "Voir l'inventaire complet" : "Préparer le scan ECU"}</button>
          </div>
          {ecuDtcs.length > 0 ? <div className="injection-dtc-list">{ecuDtcs.map((dtc) => <article key={`${dtc.code}-${dtc.raw_hex}`}><code>{dtc.code}</code><div><strong>{dtc.title ?? "Défaut non décodé"}</strong><span>{dtc.status_labels.join(" · ") || `Statut ${dtc.status_hex}`}</span></div></article>)}</div> : <p className="injection-empty-dtc">{ecuInfo ? "Aucun DTC actif pour ce calculateur." : "Aucune lecture de ce calculateur dans cette session."}</p>}
        </section>
      </div>
    );
  }
