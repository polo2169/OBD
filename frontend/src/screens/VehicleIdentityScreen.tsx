import type { Dispatch, SetStateAction } from "react";

import { EmptyState } from "../components/ui";
import { hexadecimal } from "../format";
import { LAB_MODE } from "../navigation";
import type { CaptureStatus, DiagnosticSensorSnapshot, DidValue, Ecu, Report, Status, VehicleIdentityResult, VehicleProfileSummary } from "../types";

type VehicleIdentityScreenProps={vehicleIdentity:VehicleIdentityResult|null;identityProfileKey:string;identityReadReady:boolean;capture:CaptureStatus|null;selectedIdentityProfile:VehicleProfileSummary|null;vehicleProfiles:VehicleProfileSummary[];setIdentityProfileKey:Dispatch<SetStateAction<string>>;setSelectedDiagnosticVin:Dispatch<SetStateAction<string>>;setVehicleIdentity:Dispatch<SetStateAction<VehicleIdentityResult|null>>;setInjectionSnapshot:Dispatch<SetStateAction<DiagnosticSensorSnapshot|null>>;setReport:Dispatch<SetStateAction<Report|null>>;setError:Dispatch<SetStateAction<string>>;vehicleManufacturers:string[];profilesForSelectedManufacturer:VehicleProfileSummary[];readVehicleIdentity:()=>Promise<void>;identityBusy:boolean;dualCanOperational:boolean;status:Status|null;liveObdReadOnly:boolean;readEngineObdDtcs:()=>Promise<void>;obdDtcBusy:boolean;obdDtcResult:Ecu|null;udsProbeEcuKey:string;setUdsProbeEcuKey:Dispatch<SetStateAction<string>>;setUdsProbeResult:Dispatch<SetStateAction<DidValue|null>>;testUdsPresence:()=>Promise<void>;udsProbeBusy:boolean;udsProbeResult:DidValue|null};

export function VehicleIdentityScreen({
  vehicleIdentity,
  identityProfileKey,
  identityReadReady,
  capture,
  selectedIdentityProfile,
  vehicleProfiles,
  setIdentityProfileKey,
  setSelectedDiagnosticVin,
  setVehicleIdentity,
  setInjectionSnapshot,
  setReport,
  setError,
  vehicleManufacturers,
  profilesForSelectedManufacturer,
  readVehicleIdentity,
  identityBusy,
  dualCanOperational,
  status,
  liveObdReadOnly,
  readEngineObdDtcs,
  obdDtcBusy,
  obdDtcResult,
  udsProbeEcuKey,
  setUdsProbeEcuKey,
  setUdsProbeResult,
  testUdsPresence,
  udsProbeBusy,
  udsProbeResult
}: VehicleIdentityScreenProps) {
    const displayedIdentity = vehicleIdentity?.vehicle_profile === identityProfileKey ? vehicleIdentity : null;
    const successfulFields = displayedIdentity?.fields.filter((field) => field.value && !field.error) ?? [];
    return (
      <div className="identity-page">
        <section className="panel identity-hero">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Identification multi-source enregistrée sur le PC</span>
              <h2>Lire le VIN sans modifier le véhicule</h2>
              <p>OpenDiag essaie les méthodes documentées dans l'ordre, valide le format du VIN et conserve les échanges OBD/UDS dans une trace JSONL.</p>
            </div>
            <span className={`status-pill ${identityReadReady ? "good" : "neutral"}`}><i /> {identityReadReady ? "Lecture prête" : capture?.active ? "Capture active" : "ESP32 à valider"}</span>
          </div>

          <div className="identity-launcher">
            <label>Marque
              <select
                value={selectedIdentityProfile?.manufacturer ?? ""}
                disabled={capture?.active}
                onChange={(event) => {
                  const next = vehicleProfiles.find((profile) => profile.manufacturer === event.target.value);
                  if (!next) return;
                  setIdentityProfileKey(next.key);
                  setSelectedDiagnosticVin("");
                  setVehicleIdentity(null);
                  setInjectionSnapshot(null);
                  setReport(null);
                  setError("");
                }}
              >
                {vehicleManufacturers.map((manufacturer) => <option value={manufacturer} key={manufacturer}>{manufacturer}</option>)}
              </select>
            </label>
            <label>Véhicule à identifier
              <select value={identityProfileKey} disabled={capture?.active} onChange={(event) => { setIdentityProfileKey(event.target.value); setSelectedDiagnosticVin(""); setVehicleIdentity(null); setInjectionSnapshot(null); setReport(null); setError(""); }}>
                {profilesForSelectedManufacturer.map((profile) => <option value={profile.key} key={profile.key}>{profile.model} · {profile.year ?? "année inconnue"}</option>)}
              </select>
            </label>
            <div className="identity-profile-summary">
              <span>{selectedIdentityProfile?.architecture ?? "Architecture à confirmer"}</span>
              <strong>{selectedIdentityProfile?.platform ?? "Plateforme inconnue"}</strong>
              <small>{selectedIdentityProfile?.identity_scope === "identity_only" ? "Identification seulement" : "Profil diagnostic complet"}</small>
            </div>
            <button className="primary-button" onClick={() => void readVehicleIdentity()} disabled={identityBusy || !identityReadReady || !selectedIdentityProfile}>
              {identityBusy ? "Lecture du véhicule…" : "Lire VIN + identité"}
            </button>
          </div>

          {!identityReadReady && <p className="inline-alert">{capture?.active && !dualCanOperational
            ? "Arrête et sauvegarde la capture avant cette lecture active."
            : status?.can_tx_enabled
              ? selectedIdentityProfile?.identity_scope === "identity_only" && !liveObdReadOnly
                ? "Ce profil utilise l’OBD normalisé : flashe le firmware principal qui annonce live_obd_read_only=true."
                : "Connecte l’ESP32 et vérifie la poignée de main du firmware diagnostic en lecture seule."
              : "CAN_TX_ENABLED doit autoriser les requêtes de lecture; les écritures restent bloquées."}</p>}
          {selectedIdentityProfile?.identity_scope === "identity_only" && <p className="inline-alert fiat-profile-note">Le profil Fiat est volontairement limité au VIN et aux informations OBD normalisées. Donne-moi ensuite l’année, la motorisation et si c’est une 500, 500X ou 500e pour construire le bon inventaire ECU.</p>}
        </section>

        {selectedIdentityProfile?.identity_scope === "identity_only" && <section className="panel">
          <div className="section-heading">
            <div><span className="eyebrow">Diagnostic hors inventaire complet</span><h2>Lecture DTC OBD générique</h2><p>Modes EOBD standards 03 (mémorisés) et 07 (en attente) sur le calculateur moteur — adresse et protocole confirmés, indépendant du verrou d’identification.</p></div>
            <button className="secondary-button" onClick={() => void readEngineObdDtcs()} disabled={obdDtcBusy || !identityReadReady}>{obdDtcBusy ? "Lecture…" : "Lire les DTC OBD (moteur)"}</button>
          </div>
          {obdDtcResult && (
            obdDtcResult.dtcs.length === 0 ? (
              <p className="inline-alert">Aucun code retourné.{obdDtcResult.dtc_error ? ` ${obdDtcResult.dtc_error}` : ""}</p>
            ) : (
              <div className="dtc-list">
                {obdDtcResult.dtcs.map((dtc) => (
                  <article className={`dtc-card ${dtc.state}`} key={`${dtc.raw_hex}-${dtc.state}`}>
                    <div className="dtc-code"><code>{dtc.code}</code></div>
                    <div className="dtc-description"><strong>{dtc.title ?? "Description spécifique inconnue"}</strong><p>{dtc.state_detail}</p></div>
                    <div className="dtc-meta"><span>{dtc.state_label}</span></div>
                  </article>
                ))}
              </div>
            )
          )}
        </section>}

        {selectedIdentityProfile?.identity_scope === "identity_only" && <section className="panel">
          <div className="section-heading">
            <div><span className="eyebrow">Prudence avant d’aller plus loin</span><h2>Test de présence UDS</h2><p>Une seule lecture DID standard (0xF186, session de diagnostic active) pour voir si le calculateur répond en UDS — sans supposer qu’il le fasse.</p></div>
          </div>
          <div className="dtc-clear-form">
            <label>Calculateur
              <select value={udsProbeEcuKey} onChange={(event) => { setUdsProbeEcuKey(event.target.value); setUdsProbeResult(null); }}>
                <option value="body_computer">Body Computer / BSI Fiat (0x7B0/0x7C0)</option>
                <option value="instrument_cluster">Combiné d'instruments Fiat (0x7B0/0x7C3)</option>
              </select>
            </label>
            <button className="secondary-button" onClick={() => void testUdsPresence()} disabled={udsProbeBusy || !identityReadReady}>{udsProbeBusy ? "Test…" : "Tester"}</button>
          </div>
          {udsProbeResult && (
            udsProbeResult.error ? (
              <p className="inline-alert">Pas de réponse UDS exploitable : {udsProbeResult.error}. Cohérent avec un silence total, une adresse fausse pour ce véhicule, ou un protocole KWP2000 non géré par ce firmware.</p>
            ) : (
              <p className="inline-alert">Réponse UDS reçue : session active = {String(udsProbeResult.value)}. Ce calculateur parle bien UDS à cette adresse.</p>
            )
          )}
        </section>}

        <section className="identity-layout">
          <article className={`panel vin-card ${displayedIdentity?.found ? "found" : ""}`}>
            <div className="section-heading"><div><span className="eyebrow">Vehicle Identification Number</span><h2>VIN</h2></div><span className={`status-pill ${displayedIdentity?.found ? "good" : "neutral"}`}><i /> {displayedIdentity?.found ? "Validé" : "Non lu"}</span></div>
            {displayedIdentity?.found ? (
              <>
                <strong className="vin-value">{displayedIdentity.vin}</strong>
                <div className="vin-metadata">
                  <div><span>WMI</span><strong>{displayedIdentity.wmi ?? "—"}</strong></div>
                  <div><span>Constructeur détecté</span><strong>{displayedIdentity.detected_manufacturer ?? "WMI non catalogué"}</strong></div>
                  <div><span>Correspondance profil</span><strong>{displayedIdentity.profile_match === true ? "Oui" : displayedIdentity.profile_match === false ? "Non" : "Non déterminée"}</strong></div>
                </div>
                <small className="identity-saved">Session {displayedIdentity.debug.session_id} · trace locale sauvegardée</small>
              </>
            ) : <EmptyState title="VIN pas encore lu" text="Sélectionne la Peugeot ou la Fiat, connecte l’ESP32 diagnostic, puis lance une lecture." />}
          </article>

          <article className="panel identity-methods-panel">
            <div className="section-heading"><div><span className="eyebrow">Ordre de repli contrôlé</span><h2>Méthodes prévues</h2></div></div>
            <div className="identity-method-list">
              {(selectedIdentityProfile?.vin_methods ?? []).map((method, index) => <div key={method}><span>{index + 1}</span><strong>{method}</strong></div>)}
            </div>
            {selectedIdentityProfile?.notes.slice(0, 3).map((note) => <p className="identity-note" key={note}>{note}</p>)}
          </article>
        </section>

        {displayedIdentity && (
          <>
            <section className="panel identity-attempts-panel">
              <div className="section-heading"><div><span className="eyebrow">{displayedIdentity.attempts.length} méthode(s) réellement interrogée(s)</span><h2>Preuves de lecture du VIN</h2></div><code>{displayedIdentity.transport}</code></div>
              <div className="identity-attempt-list">
                {displayedIdentity.attempts.map((attempt) => (
                  <article className={attempt.success ? "success" : "failed"} key={attempt.key}>
                    <i />
                    <div><span>{attempt.protocol.toUpperCase()} · {hexadecimal(attempt.request_id)} → {hexadecimal(attempt.response_id)}</span><strong>{attempt.label}</strong><small>{attempt.success ? `VIN ${attempt.vin}` : attempt.error ?? "Aucune réponse valide"}</small></div>
                    <div>{LAB_MODE && <code>{attempt.command_hex}</code>}<small>{attempt.confidence}</small>{attempt.source && <a href={attempt.source} target="_blank" rel="noreferrer">Source ↗</a>}</div>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel identity-fields-panel">
              <div className="section-heading"><div><span className="eyebrow">Informations complémentaires</span><h2>Logiciel, calibration et ECU</h2><p>{successfulFields.length} champ(s) décodé(s), les refus et absences restent visibles.</p></div></div>
              <div className="identity-field-grid">
                {displayedIdentity.fields.map((field) => (
                  <article className={field.error ? "field-error" : ""} key={field.key}>
                    <span>{field.protocol.toUpperCase()} · lecture d’identification</span>
                    <strong>{field.name}</strong>
                    <code>{field.error ?? field.value ?? "Réponse vide"}</code>
                    <small>{field.confidence}</small>
                  </article>
                ))}
              </div>
              {displayedIdentity.warnings.map((warning) => <p className="inline-alert" key={warning}>{warning}</p>)}
            </section>
          </>
        )}
      </div>
    );
  }
