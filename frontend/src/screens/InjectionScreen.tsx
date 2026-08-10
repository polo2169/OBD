import type { Dispatch, SetStateAction } from "react";

import { LAB_MODE } from "../navigation";
import type { View } from "../navigation";
import type { CaptureStatus, ClearDtcResult, DiagnosticSensorCatalogEntry, DiagnosticSensorSnapshot, DiagnosticSensorValue, DtcValue, EcuResetResult, PsaAdvancedCatalog, Report, Status } from "../types";

type LabChecks={vehicle_stationary:boolean;ignition_on_engine_off:boolean;stable_battery_voltage:boolean;workshop_or_private_site:boolean};
type DtcClearChecks={vehicle_stationary:boolean;ignition_on_engine_off:boolean;stable_battery_voltage:boolean;report_saved:boolean};
type LiveSafetyEvidence={speedKnown:boolean;stationary:boolean;rpmKnown:boolean;engineOff:boolean;batteryKnown:boolean;batteryStable:boolean;batteryValue:number|null};
type InjectionScreenProps={diagnosticSensorCatalog:DiagnosticSensorCatalogEntry[];injectionSnapshot:DiagnosticSensorSnapshot|null;obdReadReady:boolean;capture:CaptureStatus|null;status:Status|null;diagnosticGatewayVerified:boolean;readInjectionParameters:(destination?:View)=>Promise<void>;injectionBusy:boolean;dualCanOperational:boolean;injectionGroups:Array<{group:string;sensors:DiagnosticSensorCatalogEntry[]}>;injectionValues:Map<string,DiagnosticSensorValue>;setView:Dispatch<SetStateAction<View>>;psaCatalog:PsaAdvancedCatalog|null;liveSafetyEvidence:LiveSafetyEvidence;effectivePsaLabChecks:LabChecks;setPsaLabChecks:Dispatch<SetStateAction<LabChecks>>;ecuResetConfirmation:string;setEcuResetConfirmation:Dispatch<SetStateAction<string>>;resetSelectedEcu:(ecuKey:string)=>Promise<void>;psaVehicleCompatible:boolean;diagnosticReady:boolean;psaLabChecksComplete:boolean;ecuResetBusy:boolean;ecuResetResult:EcuResetResult|null;dtcClearChecks:DtcClearChecks;setDtcClearChecks:Dispatch<SetStateAction<DtcClearChecks>>;dtcClearConfirmation:string;setDtcClearConfirmation:Dispatch<SetStateAction<string>>;clearSelectedEcuDtcs:(ecuKey?:string)=>Promise<void>;dtcClearBusy:boolean;dtcClearResult:ClearDtcResult|null;report:Report|null;engineDtcs:DtcValue[]};

export function InjectionScreen({
  diagnosticSensorCatalog,
  injectionSnapshot,
  obdReadReady,
  capture,
  status,
  diagnosticGatewayVerified,
  readInjectionParameters,
  injectionBusy,
  dualCanOperational,
  injectionGroups,
  injectionValues,
  setView,
  psaCatalog,
  liveSafetyEvidence,
  effectivePsaLabChecks,
  setPsaLabChecks,
  ecuResetConfirmation,
  setEcuResetConfirmation,
  resetSelectedEcu,
  psaVehicleCompatible,
  diagnosticReady,
  psaLabChecksComplete,
  ecuResetBusy,
  ecuResetResult,
  dtcClearChecks,
  setDtcClearChecks,
  dtcClearConfirmation,
  setDtcClearConfirmation,
  clearSelectedEcuDtcs,
  dtcClearBusy,
  dtcClearResult,
  report,
  engineDtcs
}: InjectionScreenProps) {
    const supportedCatalogCount = diagnosticSensorCatalog.filter((sensor) => injectionSnapshot?.supported_pids.includes(sensor.pid)).length;
    const measuredCount = injectionSnapshot?.values.filter((value) => value.value !== null && value.value !== undefined && !value.error).length ?? 0;
    const pressureInBar = (sensor: DiagnosticSensorCatalogEntry, value?: DiagnosticSensorValue) => {
      if (!["fuel_rail_gauge_pressure", "absolute_fuel_rail_pressure"].includes(sensor.key) || typeof value?.value !== "number") return null;
      return `${(value.value / 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} bar`;
    };
    const psaSpecificSensors = [
      ["Correction injecteur 1", "DID PSA à identifier"],
      ["Correction injecteur 2", "DID PSA à identifier"],
      ["Correction injecteur 3", "DID PSA à identifier"],
      ["Correction injecteur 4", "DID PSA à identifier"],
      ["Temps / quantité injectée", "DID PSA à identifier"],
      ["Consigne pression de rampe", "DID PSA à identifier"],
      ["Commande turbo / géométrie", "DID PSA à identifier"],
      ["Charge FAP / pression différentielle", "DID PSA à identifier"],
    ];

    return (
      <div className="injection-page">
        <section className="panel injection-gate">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Lecture active normalisée · aucune commande d'actionneur</span>
              <h2>Relevé moteur et injection</h2>
              <p>Interroge uniquement les PID OBD-II supportés par le calculateur moteur. Aucune écriture, adaptation ou commande d'injecteur.</p>
            </div>
            <span className={`status-pill ${obdReadReady ? "good" : "neutral"}`}><i /> {obdReadReady ? "Prêt" : capture?.active ? "Capture active" : status?.can_tx_enabled ? "Firmware 6/14 à valider" : "Verrouillé"}</span>
          </div>
          <div className="diagnostic-preflight">
            <div><span>Liaison ESP32</span><strong>{diagnosticGatewayVerified ? "Validée" : "Connexion requise"}</strong></div>
            <div><span>Calculateur interrogé</span><strong>Calculateur moteur principal</strong></div>
            <div><span>Mode diagnostic</span><strong>OBD-II 01 · lecture seule</strong></div>
            <div><span>Réseau utilisé</span><strong>{obdReadReady ? "6/14 · OBD 01/09 filtré" : "6/14 indisponible"}</strong></div>
          </div>
          {obdReadReady ? (
            <button className="primary-button full-scan-button" onClick={() => void readInjectionParameters()} disabled={injectionBusy}>{injectionBusy ? "Lecture en cours…" : injectionSnapshot ? "Actualiser les paramètres d'injection" : "Lire les paramètres d'injection"}</button>
          ) : (
            <p className="inline-alert">{capture?.active && !dualCanOperational
              ? "Cette passerelle ne confirme pas deux contrôleurs CAN disponibles simultanément."
              : status?.can_tx_enabled
                ? "Connecte puis flashe le firmware principal compatible OBD 01/09 sur 6/14."
                : "Le backend est actuellement en écoute passive stricte; les requêtes OBD-II restent bloquées."}</p>
          )}
        </section>

        <section className="injection-summary-grid">
          <article><span>PID catalogués</span><strong>{diagnosticSensorCatalog.length || "—"}</strong><small>Mode 01 normalisé</small></article>
          <article><span>PID supportés</span><strong>{injectionSnapshot ? supportedCatalogCount : "—"}</strong><small>Déclarés par cet ECU</small></article>
          <article><span>Valeurs reçues</span><strong>{injectionSnapshot ? measuredCount : "—"}</strong><small>Dernier relevé</small></article>
          <article><span>Voyant / DTC émissions</span><strong>{injectionSnapshot?.mil_on === false ? `Éteint · ${injectionSnapshot.emissions_dtc_count ?? 0} DTC` : injectionSnapshot?.mil_on === true ? `Allumé · ${injectionSnapshot.emissions_dtc_count ?? 0} DTC` : "—"}</strong><small>Mode 01 · PID 01, sans effacement</small></article>
          <article><span>Trace locale</span><strong>{injectionSnapshot?.debug.session_id ? "Sauvegardée" : "—"}</strong><small>{injectionSnapshot?.debug.session_id ?? "Après la première lecture"}</small></article>
        </section>

        {injectionGroups.map(({ group, sensors }) => (
          <section className="panel injection-group" key={group}>
            <div className="section-heading">
              <div><span className="eyebrow">Injection · {group}</span><h2>{group}</h2></div>
              <span className="injection-group-count">{injectionSnapshot ? sensors.filter((sensor) => injectionSnapshot.supported_pids.includes(sensor.pid)).length : 0} / {sensors.length} supportés</span>
            </div>
            <div className="injection-sensor-grid">
              {sensors.map((sensor) => {
                const supported = Boolean(injectionSnapshot?.supported_pids.includes(sensor.pid));
                const value = injectionValues.get(sensor.key);
                const available = typeof value?.value === "number" && !value.error;
                const barValue = pressureInBar(sensor, value);
                return (
                  <article className={`${supported ? "supported" : ""} ${available ? "available" : ""}`} key={sensor.key}>
                    <header><span>PID 0x{sensor.pid.toString(16).toUpperCase().padStart(2, "0")}</span><i /></header>
                    <h3>{sensor.name}</h3>
                    <div className="injection-value">
                      <strong>{available ? Number(value?.value).toLocaleString("fr-FR", { maximumFractionDigits: 3 }) : "—"}</strong>
                      <span>{available ? value?.unit ?? sensor.unit : injectionSnapshot ? supported ? value?.error ?? "Réponse invalide" : "Non exposé par l'ECU" : "À lire"}</span>
                      {barValue && <small>{barValue}</small>}
                    </div>
                    <p>{sensor.description}</p>
                    <footer><span>{available ? "Mesuré" : supported ? "Support déclaré" : "Indisponible"}</span>{LAB_MODE && value?.raw_hex && <code>{value.raw_hex}</code>}</footer>
                  </article>
                );
              })}
            </div>
          </section>
        ))}

        <section className="panel psa-injection-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Données constructeur Peugeot / PSA</span>
              <h2>Paramètres avancés à cartographier</h2>
              <p>Ces valeurs ne sont pas des PID OBD universels. Elles nécessitent les DID exacts du calculateur d'injection de cette 308.</p>
            </div>
            <button className="secondary-button" onClick={() => setView("discovery")}>Ouvrir la découverte</button>
          </div>
          <div className="psa-specific-grid">
            {psaSpecificSensors.map(([name, state]) => <article key={name}><i /><div><strong>{name}</strong><span>{state}</span></div></article>)}
          </div>
          <p className="inline-alert">Les « corrections injecteurs » ne sont pas les corrections de richesse OBD B1/B2. Elles seront affichées cylindre par cylindre seulement après identification et validation des DID PSA, moteur tournant dans des conditions maîtrisées.</p>
        </section>

        <section className="panel dtc-clear-panel">
          <div className="section-heading">
            <div><span className="eyebrow">UDS 0x11 · redémarrage matériel</span><h2>Redémarrer le calculateur moteur</h2><p>Envoie un ECUReset (hardReset). Le calculateur redémarre et reste injoignable quelques secondes ; le moteur doit être arrêté avant d’envoyer cette commande.</p></div>
            <span className={`status-pill ${psaCatalog?.ecu_reset_enabled ? "warning" : "neutral"}`}><i /> {psaCatalog?.ecu_reset_enabled ? "Armé par configuration" : "Verrouillé"}</span>
          </div>
          <div className="dtc-clear-form">
            <div className="dtc-clear-checks">
              <label><input type="checkbox" disabled={liveSafetyEvidence.speedKnown} checked={effectivePsaLabChecks.vehicle_stationary} onChange={(event) => setPsaLabChecks((current) => ({ ...current, vehicle_stationary: event.target.checked }))} /> Véhicule immobilisé</label>
              <label><input type="checkbox" disabled={liveSafetyEvidence.rpmKnown} checked={effectivePsaLabChecks.ignition_on_engine_off} onChange={(event) => setPsaLabChecks((current) => ({ ...current, ignition_on_engine_off: event.target.checked }))} /> Contact mis, moteur arrêté</label>
              <label><input type="checkbox" disabled={liveSafetyEvidence.batteryKnown} checked={effectivePsaLabChecks.stable_battery_voltage} onChange={(event) => setPsaLabChecks((current) => ({ ...current, stable_battery_voltage: event.target.checked }))} /> Tension batterie stable</label>
              <label><input type="checkbox" checked={effectivePsaLabChecks.workshop_or_private_site} onChange={(event) => setPsaLabChecks((current) => ({ ...current, workshop_or_private_site: event.target.checked }))} /> Atelier ou site privé</label>
            </div>
            <label>Confirmation exacte<input value={ecuResetConfirmation} onChange={(event) => setEcuResetConfirmation(event.target.value)} placeholder="REDEMARRER ENGINE" /></label>
            <button
              className="danger-button"
              onClick={() => void resetSelectedEcu("engine")}
              disabled={!psaCatalog?.ecu_reset_enabled || !psaVehicleCompatible || !diagnosticReady || !psaLabChecksComplete || ecuResetConfirmation !== "REDEMARRER ENGINE" || ecuResetBusy}
            >{ecuResetBusy ? "Redémarrage…" : "Redémarrer le calculateur moteur"}</button>
          </div>
          {!psaCatalog?.ecu_reset_enabled && <p className="inline-alert">Verrou actif : `PSA_ECU_RESET_ENABLED=false`.</p>}
          {ecuResetResult && ecuResetResult.ecu_key === "engine" && <div className={`regression-result ${ecuResetResult.reset ? "good" : "warning"}`}><strong>{ecuResetResult.reset ? "Commande envoyée" : "Échec"}</strong><span>{ecuResetResult.message}</span>{LAB_MODE && ecuResetResult.response_hex && <code>RX {ecuResetResult.response_hex}</code>}</div>}
        </section>

        <section className="panel dtc-clear-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Maintenance unitaire contrôlée</span><h2>Effacer la mémoire DTC du calculateur moteur</h2><p>Le backend lit les défauts avant, exige un acquittement positif, puis relit immédiatement le même ECU pour vérifier.</p></div>
            <span className={`status-pill ${status?.dtc_clear_enabled ? "warning" : "neutral"}`}><i /> {status?.dtc_clear_enabled ? "Armé par configuration" : "Verrouillé"}</span>
          </div>
          <div className="dtc-clear-form">
            <div className="dtc-clear-checks">
              <label><input type="checkbox" checked={dtcClearChecks.vehicle_stationary} onChange={(event) => setDtcClearChecks((current) => ({ ...current, vehicle_stationary: event.target.checked }))} /> Véhicule immobilisé</label>
              <label><input type="checkbox" checked={dtcClearChecks.ignition_on_engine_off} onChange={(event) => setDtcClearChecks((current) => ({ ...current, ignition_on_engine_off: event.target.checked }))} /> Contact mis, moteur arrêté</label>
              <label><input type="checkbox" checked={dtcClearChecks.stable_battery_voltage} onChange={(event) => setDtcClearChecks((current) => ({ ...current, stable_battery_voltage: event.target.checked }))} /> Tension batterie stable</label>
              <label><input type="checkbox" checked={dtcClearChecks.report_saved} onChange={(event) => setDtcClearChecks((current) => ({ ...current, report_saved: event.target.checked }))} /> Rapport avant effacement sauvegardé</label>
            </div>
            <label>Confirmation exacte<input value={dtcClearConfirmation} onChange={(event) => setDtcClearConfirmation(event.target.value)} placeholder="EFFACER ENGINE" /></label>
            <button
              className="danger-button"
              onClick={() => void clearSelectedEcuDtcs("engine")}
              disabled={!status?.dtc_clear_enabled || dtcClearConfirmation !== "EFFACER ENGINE" || !Object.values(dtcClearChecks).every(Boolean) || dtcClearBusy}
            >{dtcClearBusy ? "Lecture, effacement, contrôle…" : "Effacer cet ECU et vérifier"}</button>
          </div>
          {!status?.dtc_clear_enabled && <p className="inline-alert">Verrou actif : `DTC_CLEAR_ENABLED=false`.</p>}
          {dtcClearResult && dtcClearResult.ecu_key === "engine" && <div className={`regression-result ${dtcClearResult.verified ? "good" : "warning"}`}><strong>{dtcClearResult.verified ? "Effacement contrôlé" : "Effacement accepté, contrôle incomplet"}</strong><span>{dtcClearResult.message}</span><small>{dtcClearResult.before_dtcs.length} avant · {dtcClearResult.after_dtcs.length} après</small>{LAB_MODE && <code>TX {dtcClearResult.request_hex} / RX {dtcClearResult.response_hex ?? "—"}</code>}</div>}
        </section>

        <section className="panel injection-dtc-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Calculateur moteur / injection</span><h2>Défauts liés au moteur</h2><p>{report ? `${engineDtcs.length} défaut(s) remonté(s) au dernier inventaire ECU.` : "Lance l’inventaire ECU pour lire la mémoire de défauts du calculateur moteur."}</p></div>
            <button className="secondary-button" onClick={() => setView("ecus")}>{report ? "Voir l'inventaire" : "Préparer le scan ECU"}</button>
          </div>
          {engineDtcs.length > 0 ? <div className="injection-dtc-list">{engineDtcs.map((dtc) => <article key={`${dtc.code}-${dtc.raw_hex}`}><code>{dtc.code}</code><div><strong>{dtc.title ?? "Défaut injection non décodé"}</strong><span>{dtc.status_labels.join(" · ") || `Statut ${dtc.status_hex}`}</span></div></article>)}</div> : <p className="injection-empty-dtc">{report ? "Aucun DTC moteur remonté lors du dernier scan." : "Aucune lecture du calculateur moteur dans cette session."}</p>}
        </section>
      </div>
    );
  }
