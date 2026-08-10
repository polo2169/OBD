import type { Dispatch, SetStateAction } from "react";

import { TelecodingDetails } from "../components/TelecodingDetails";
import { hexadecimal } from "../format";
import type { DidValue, PassiveSensorSnapshot, PsaAdvancedAction, PsaAdvancedCatalog, PsaAdvancedEcu, PsaSeedKeyResult, Status } from "../types";

type LabChecks={vehicle_stationary:boolean;ignition_on_engine_off:boolean;stable_battery_voltage:boolean;workshop_or_private_site:boolean};
type LiveSafetyEvidence={speedKnown:boolean;stationary:boolean;rpmKnown:boolean;engineOff:boolean;batteryKnown:boolean;batteryStable:boolean;batteryValue:number|null};
type PsaSection="read"|"actions"|"expert";
type PsaAdvancedScreenProps={status:Status|null;psaCatalog:PsaAdvancedCatalog|null;diagnosticReady:boolean;psaVehicleCompatible:boolean;diagnosticGatewayVerified:boolean;psaLabChecksComplete:boolean;psaLabChecks:LabChecks;setPsaLabChecks:Dispatch<SetStateAction<LabChecks>>;psaSection:PsaSection;setPsaSection:Dispatch<SetStateAction<PsaSection>>;psaEcuKey:string;setPsaEcuKey:Dispatch<SetStateAction<string>>;setPsaDidResult:Dispatch<SetStateAction<DidValue|null>>;psaDid:string;setPsaDid:Dispatch<SetStateAction<string>>;readPsaDid:()=>Promise<void>;psaBusy:string;selectedPsaEcu:PsaAdvancedEcu|null;psaDidResult:DidValue|null;psaSeed:string;setPsaSeed:Dispatch<SetStateAction<string>>;psaApplicationKey:string;setPsaApplicationKey:Dispatch<SetStateAction<string>>;calculatePsaSeedKey:()=>Promise<void>;psaSeedResult:PsaSeedKeyResult|null;setPsaSeedResult:Dispatch<SetStateAction<PsaSeedKeyResult|null>>;effectivePsaLabChecks:LabChecks;liveSafetyEvidence:LiveSafetyEvidence;passiveSensors:PassiveSensorSnapshot|null;psaSelectedActionKey:string;setPsaSelectedActionKey:Dispatch<SetStateAction<string>>;setPsaConfirmation:Dispatch<SetStateAction<string>>;setPsaFeedback:Dispatch<SetStateAction<string>>;selectedPsaAction:PsaAdvancedAction|null;psaDurationMs:number;setPsaDurationMs:Dispatch<SetStateAction<number>>;psaConfirmation:string;executePsaAction:()=>Promise<void>;psaUnlockEcuKey:string;setPsaUnlockEcuKey:Dispatch<SetStateAction<string>>;setPsaUnlockApplicationKey:Dispatch<SetStateAction<string>>;setPsaUnlockConfirmation:Dispatch<SetStateAction<string>>;psaUnlockApplicationKey:string;psaUnlockEcu:PsaAdvancedEcu|null;psaUnlockConfirmation:string;unlockPsaConfiguration:()=>Promise<void>;psaFeedback:string};

export function PsaAdvancedScreen({
  status,
  psaCatalog,
  diagnosticReady,
  psaVehicleCompatible,
  diagnosticGatewayVerified,
  psaLabChecksComplete,
  psaLabChecks,
  setPsaLabChecks,
  psaSection,
  setPsaSection,
  psaEcuKey,
  setPsaEcuKey,
  setPsaDidResult,
  psaDid,
  setPsaDid,
  readPsaDid,
  psaBusy,
  selectedPsaEcu,
  psaDidResult,
  psaSeed,
  setPsaSeed,
  psaApplicationKey,
  setPsaApplicationKey,
  calculatePsaSeedKey,
  psaSeedResult,
  setPsaSeedResult,
  effectivePsaLabChecks,
  liveSafetyEvidence,
  passiveSensors,
  psaSelectedActionKey,
  setPsaSelectedActionKey,
  setPsaConfirmation,
  setPsaFeedback,
  selectedPsaAction,
  psaDurationMs,
  setPsaDurationMs,
  psaConfirmation,
  executePsaAction,
  psaUnlockEcuKey,
  setPsaUnlockEcuKey,
  setPsaUnlockApplicationKey,
  setPsaUnlockConfirmation,
  psaUnlockApplicationKey,
  psaUnlockEcu,
  psaUnlockConfirmation,
  unlockPsaConfiguration,
  psaFeedback
}: PsaAdvancedScreenProps) {
    const firmwarePolicy = String(status?.gateway_hello?.tx_policy ?? (status?.transport === "virtual" ? "virtual-psa-lab" : "non vérifié"));
    const psaFirmwareReady = status?.transport === "virtual" || status?.gateway_hello?.psa_lab === true;
    const labRuntimeReady = Boolean(
      psaCatalog?.enabled
      && psaCatalog.actuator_enabled
      && !psaCatalog.read_only
      && diagnosticReady
      && psaFirmwareReady,
    );
    const psaReadReady = diagnosticReady && psaVehicleCompatible;
    const activeAuthorizationSteps = [
      { label: "Passerelle", detail: diagnosticGatewayVerified ? "ESP32 authentifié" : "Connexion requise", complete: diagnosticGatewayVerified },
      { label: "Firmware", detail: psaFirmwareReady ? "Allowlist PSA lab" : "Profil PSA lab requis", complete: psaFirmwareReady },
      { label: "Backend", detail: psaCatalog?.actuator_enabled && !psaCatalog.read_only ? "Actions explicitement activées" : "Configuration verrouillée", complete: Boolean(psaCatalog?.actuator_enabled && !psaCatalog.read_only) },
      { label: "Véhicule", detail: !psaVehicleCompatible ? "Profil PSA requis" : psaLabChecksComplete ? "VIN et préconditions confirmés" : "Contrôles à terminer", complete: psaVehicleCompatible && psaLabChecksComplete },
    ];
    const activeAuthorizationProgress = activeAuthorizationSteps.filter((step) => step.complete).length;
    const activeAuthorizationReady = labRuntimeReady && psaVehicleCompatible && psaLabChecksComplete;
    const unlockableEcus = psaCatalog?.ecus.filter((ecu) => ["bsi", "telematics"].includes(ecu.key) && ecu.security_keys.length) ?? [];
    const updateLabCheck = (key: keyof typeof psaLabChecks, checked: boolean) => {
      setPsaLabChecks((current) => ({ ...current, [key]: checked }));
    };

    return (
      <div className="psa-advanced-page">
        <section className="panel psa-advanced-hero">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Inspiré d'arduino-psa-diag · intégration native OpenDiag</span>
              <h2>Passerelle PSA sans VCI Diagbox</h2>
              <p>Notre ESP32 transporte directement les échanges ISO-TP. Les lectures restent disponibles avec le firmware diagnostic; les commandes actives exigent le profil PSA lab à allowlist stricte.</p>
            </div>
            <span className={`status-pill ${psaCatalog?.enabled ? "good" : "neutral"}`}><i /> {psaCatalog?.enabled ? "Module chargé" : "Indisponible"}</span>
          </div>
          <div className="psa-readiness-grid">
            <article><span>Transport</span><strong>{status?.transport ?? "—"}</strong><small>{diagnosticGatewayVerified ? "Passerelle validée" : "Connexion requise"}</small></article>
            <article><span>Politique firmware</span><strong>{firmwarePolicy}</strong><small>{psaFirmwareReady ? "PSA lab reconnu" : "Lecture seule uniquement"}</small></article>
            <article><span>Lecture UDS</span><strong>{psaReadReady ? "Prête" : "Verrouillée"}</strong><small>{psaVehicleCompatible ? "Services 0x19 / 0x22 / 0x3E" : "Charge un véhicule PSA"}</small></article>
            <article><span>Actionneurs</span><strong>{labRuntimeReady ? "Armables" : "Verrouillés"}</strong><small>0x2F exact · temporisation ≤ 3 s</small></article>
          </div>
          {psaCatalog && <div className="psa-wiring-note"><strong>Réseaux OBD à vérifier avant branchement</strong><span>{psaCatalog.wiring.vehicle_can} · {psaCatalog.wiring.standard_obd}</span><p>{psaCatalog.wiring.warning}</p></div>}
        </section>

        <nav className="workspace-tabs" aria-label="Mode du diagnostic PSA">
          <button className={psaSection === "read" ? "active" : ""} onClick={() => setPsaSection("read")}><span>01</span><div><strong>Lecture sécurisée</strong><small>DID et identification</small></div></button>
          <button className={psaSection === "actions" ? "active danger" : ""} onClick={() => setPsaSection("actions")}><span>02</span><div><strong>Commandes actives</strong><small>Armement contrôlé</small></div></button>
          <button className={psaSection === "expert" ? "active" : ""} onClick={() => setPsaSection("expert")}><span>03</span><div><strong>Outils experts</strong><small>Seed/key et SecurityAccess</small></div></button>
        </nav>

        {psaSection === "read" && <section className="panel psa-zone-reader">
          <div className="section-heading">
            <div><span className="eyebrow">ReadDataByIdentifier · service 0x22</span><h2>Lire une zone brute BSI, NAC ou ECU</h2><p>Cette lecture accepte un DID PSA non encore catalogué et conserve sa réponse brute dans une trace locale.</p></div>
            <span className={`status-pill ${psaReadReady ? "good" : "neutral"}`}><i /> {psaReadReady ? "Lecture autorisée" : psaVehicleCompatible ? "CAN TX lecture requis" : "Mauvais véhicule actif"}</span>
          </div>
          <div className="psa-zone-form">
            <label>Calculateur<select value={psaEcuKey} onChange={(event) => { setPsaEcuKey(event.target.value); setPsaDidResult(null); }}>{psaCatalog?.ecus.map((ecu) => <option key={ecu.key} value={ecu.key}>{ecu.name}</option>)}</select></label>
            <label>DID hexadécimal<div className="psa-hex-input"><span>0x</span><input value={psaDid} onChange={(event) => setPsaDid(event.target.value.toUpperCase())} maxLength={6} /></div></label>
            <button className="primary-button" onClick={() => void readPsaDid()} disabled={psaBusy === "did" || !psaReadReady}>{psaBusy === "did" ? "Lecture…" : "Lire la zone"}</button>
          </div>
          <div className="psa-ecu-address"><span>{selectedPsaEcu?.family ?? "Famille inconnue"}</span><code>{hexadecimal(selectedPsaEcu?.request_id)} → {hexadecimal(selectedPsaEcu?.response_id)}</code><small>{selectedPsaEcu?.optional ? "Équipement optionnel" : "Calculateur attendu sur T9"}</small></div>
          {psaDidResult && <div className="psa-zone-result">
            <div><span>DID 0x{psaDidResult.did.toString(16).toUpperCase().padStart(4, "0")}</span><strong>{String(psaDidResult.value ?? "Réponse vide")}</strong></div>
            <code>{psaDidResult.raw_hex ?? "—"}</code>
            <small>{psaDidResult.codec} · {psaDidResult.confidence}</small>
            {psaDidResult.telecoding && <TelecodingDetails zone={psaDidResult.telecoding} />}
          </div>}
        </section>}

        {psaSection === "expert" && <section className="psa-two-column">
          <article className="panel psa-seed-panel">
            <div className="section-heading"><div><span className="eyebrow">Calcul local · aucune émission CAN</span><h2>Calculateur seed/key PSA</h2><p>Reproduit l'algorithme PSA public pour une seed de 4 octets et une clé application de 2 octets.</p></div></div>
            <div className="psa-seed-form">
              <label>Seed<input value={psaSeed} onChange={(event) => setPsaSeed(event.target.value.toUpperCase())} maxLength={8} /></label>
              <label>Clé application<input value={psaApplicationKey} onChange={(event) => setPsaApplicationKey(event.target.value.toUpperCase())} maxLength={4} /></label>
              <button className="secondary-button" onClick={() => void calculatePsaSeedKey()} disabled={psaBusy === "seed"}>{psaBusy === "seed" ? "Calcul…" : "Calculer hors ligne"}</button>
            </div>
            {psaSeedResult && <div className="psa-seed-result"><span>Réponse key</span><strong>{psaSeedResult.response_key_hex}</strong><small>Non transmise · source publique PSA seed/key</small></div>}
          </article>

          <article className="panel psa-keys-panel">
            <div className="section-heading"><div><span className="eyebrow">Variantes à confirmer par identification ECU</span><h2>Clés candidates documentées</h2></div></div>
            <div className="psa-key-list">
              {(psaCatalog?.ecus.filter((ecu) => ecu.security_keys.length) ?? []).map((ecu) => <div key={ecu.key}><span>{ecu.name}</span><div>{ecu.security_keys.map((candidate) => <button key={candidate.variant} onClick={() => { setPsaApplicationKey(candidate.key_hex); setPsaSeedResult(null); }}><strong>{candidate.variant}</strong><code>{candidate.key_hex}</code></button>)}</div></div>)}
            </div>
            <p className="inline-alert">Une clé candidate ne confirme pas la variante montée. Une identification erronée peut déclencher l'anti-bruteforce de l'ECU.</p>
          </article>
        </section>}

        {psaSection === "actions" && <>
        <section className="panel active-authorization-panel">
          <div className="authorization-heading">
            <div><span className="eyebrow">Autorisation temporaire · non mémorisée</span><h2>Préparer une commande active</h2><p>Une action ne devient exécutable que lorsque les quatre couches sont vertes. Une mesure CAN disponible ne peut pas être remplacée par une déclaration manuelle contradictoire.</p></div>
            <div className={`authorization-score ${activeAuthorizationReady ? "ready" : ""}`}><strong>{activeAuthorizationProgress}/4</strong><span>{activeAuthorizationReady ? "Prêt à armer" : "Verrouillé"}</span></div>
          </div>
          <div className="authorization-chain">
            {activeAuthorizationSteps.map((step, index) => <div className={step.complete ? "complete" : ""} key={step.label}><span>{index + 1}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div></div>)}
          </div>
          <div className="authorization-conditions">
            <label className={`${effectivePsaLabChecks.vehicle_stationary ? "complete" : ""} ${liveSafetyEvidence.speedKnown && !liveSafetyEvidence.stationary ? "blocked" : ""}`}>
              <input type="checkbox" disabled={liveSafetyEvidence.speedKnown} checked={effectivePsaLabChecks.vehicle_stationary} onChange={(event) => updateLabCheck("vehicle_stationary", event.target.checked)} />
              <span><strong>Véhicule immobilisé</strong><small>{liveSafetyEvidence.speedKnown ? liveSafetyEvidence.stationary ? "Mesuré sur 5 s : 0 km/h" : "Refusé : vitesse détectée" : "À confirmer manuellement"}</small></span>
            </label>
            <label className={`${effectivePsaLabChecks.ignition_on_engine_off ? "complete" : ""} ${liveSafetyEvidence.rpmKnown && !liveSafetyEvidence.engineOff ? "blocked" : ""}`}>
              <input type="checkbox" disabled={liveSafetyEvidence.rpmKnown} checked={effectivePsaLabChecks.ignition_on_engine_off} onChange={(event) => updateLabCheck("ignition_on_engine_off", event.target.checked)} />
              <span><strong>Contact mis, moteur arrêté</strong><small>{liveSafetyEvidence.rpmKnown ? liveSafetyEvidence.engineOff ? "Mesuré sur 5 s : régime nul" : "Refusé : moteur tournant" : "À confirmer manuellement"}</small></span>
            </label>
            <label className={`${effectivePsaLabChecks.stable_battery_voltage ? "complete" : ""} ${liveSafetyEvidence.batteryKnown && !liveSafetyEvidence.batteryStable ? "blocked" : ""}`}>
              <input type="checkbox" disabled={liveSafetyEvidence.batteryKnown} checked={effectivePsaLabChecks.stable_battery_voltage} onChange={(event) => updateLabCheck("stable_battery_voltage", event.target.checked)} />
              <span><strong>Tension batterie stable</strong><small>{liveSafetyEvidence.batteryKnown ? liveSafetyEvidence.batteryStable ? `Mesurée : ${liveSafetyEvidence.batteryValue?.toFixed(2)} V` : "Refusée : tension instable/hors plage" : "À confirmer manuellement"}</small></span>
            </label>
            <label className={effectivePsaLabChecks.workshop_or_private_site ? "complete" : ""}>
              <input type="checkbox" checked={psaLabChecks.workshop_or_private_site} onChange={(event) => updateLabCheck("workshop_or_private_site", event.target.checked)} />
              <span><strong>Atelier ou site privé</strong><small>Confirmation humaine obligatoire</small></span>
            </label>
          </div>
          {!passiveSensors?.active && <p className="authorization-hint">Pour automatiser vitesse, régime et tension, démarre le direct CAN avec la double passerelle. Sans télémétrie fraîche, ces trois conditions restent des confirmations manuelles transmises et journalisées.</p>}
        </section>

        <section className="panel psa-actions-panel">
          <div className="section-heading">
            <div><span className="eyebrow">InputOutputControlByIdentifier · service 0x2F</span><h2>Actionneurs nommés</h2><p>Aucun champ de trame libre : le backend et le firmware vérifient tous deux chaque payload exact.</p></div>
            <span className={`status-pill ${labRuntimeReady ? "good" : "neutral"}`}><i /> {labRuntimeReady ? "PSA lab prêt" : "Double verrou actif"}</span>
          </div>
          <div className="psa-action-grid">
            {psaCatalog?.actions.map((action) => (
              <article className={`${action.available ? "available" : "unknown"} ${psaSelectedActionKey === action.key ? "selected" : ""}`} key={action.key}>
                <header><span>{action.ecu_key.toUpperCase()}</span><i /></header>
                <h3>{action.name}</h3><p>{action.description}</p>
                <code>{action.start_payload_hex ?? "COMMANDE À IDENTIFIER"}</code>
                <span className={`validation-badge ${action.vehicle_confirmed ? "validated" : action.available ? "plausible" : "candidate"}`}>{action.vehicle_confirmed ? "Confirmé sur ce VIN" : action.available ? "Documenté · essai véhicule requis" : "Non documenté"}</span>
                {action.unavailable_reason && <small>{action.unavailable_reason}</small>}
                <button className="ghost-button" disabled={!action.available} onClick={() => { setPsaSelectedActionKey(action.key); setPsaConfirmation(""); setPsaFeedback(""); }}>{action.available ? "Préparer le test" : "Non disponible"}</button>
              </article>
            ))}
          </div>

          {selectedPsaAction && <div className="psa-action-gate">
            <div><span>Action préparée</span><strong>{selectedPsaAction.name}</strong><code>{selectedPsaAction.start_payload_hex}{selectedPsaAction.stop_payload_hex ? ` → arrêt ${selectedPsaAction.stop_payload_hex}` : ""}</code></div>
            {selectedPsaAction.timed && <label>Durée<input type="number" min={250} max={3000} step={250} value={psaDurationMs} onChange={(event) => setPsaDurationMs(Math.max(250, Math.min(3000, Number(event.target.value))))} /><span>ms</span></label>}
            <label className="psa-confirmation-field">Confirmation exacte<input value={psaConfirmation} onChange={(event) => setPsaConfirmation(event.target.value)} placeholder={selectedPsaAction.confirmation ?? ""} /><small>{selectedPsaAction.confirmation}</small></label>
            <button className="danger-button" onClick={() => void executePsaAction()} disabled={!activeAuthorizationReady || psaConfirmation !== selectedPsaAction.confirmation || psaBusy === "action"}>{psaBusy === "action" ? "Action en cours…" : "Exécuter puis arrêter"}</button>
          </div>}
        </section>
        </>}

        {psaSection === "expert" && <section className="panel psa-security-panel">
          <div className="section-heading"><div><span className="eyebrow">Verrous communs aux actions et à SecurityAccess</span><h2>Armement atelier</h2><p>Ces confirmations sont transmises avec l'opération; elles ne sont pas mémorisées.</p></div></div>
          <div className="psa-safety-checks">
            <label><input type="checkbox" disabled={liveSafetyEvidence.speedKnown} checked={effectivePsaLabChecks.vehicle_stationary} onChange={(event) => updateLabCheck("vehicle_stationary", event.target.checked)} /><span>Véhicule immobilisé</span></label>
            <label><input type="checkbox" disabled={liveSafetyEvidence.rpmKnown} checked={effectivePsaLabChecks.ignition_on_engine_off} onChange={(event) => updateLabCheck("ignition_on_engine_off", event.target.checked)} /><span>Contact mis, moteur arrêté</span></label>
            <label><input type="checkbox" disabled={liveSafetyEvidence.batteryKnown} checked={effectivePsaLabChecks.stable_battery_voltage} onChange={(event) => updateLabCheck("stable_battery_voltage", event.target.checked)} /><span>Tension batterie stable</span></label>
            <label><input type="checkbox" checked={psaLabChecks.workshop_or_private_site} onChange={(event) => updateLabCheck("workshop_or_private_site", event.target.checked)} /><span>Atelier ou site privé</span></label>
          </div>
          <div className="psa-unlock-row">
            <label>ECU<select value={psaUnlockEcuKey} onChange={(event) => { const key = event.target.value; const ecu = psaCatalog?.ecus.find((candidate) => candidate.key === key); setPsaUnlockEcuKey(key); setPsaUnlockApplicationKey(ecu?.security_keys[0]?.key_hex ?? ""); setPsaUnlockConfirmation(""); }}>{unlockableEcus.map((ecu) => <option value={ecu.key} key={ecu.key}>{ecu.name}</option>)}</select></label>
            <label>Clé<select value={psaUnlockApplicationKey} onChange={(event) => setPsaUnlockApplicationKey(event.target.value)}>{psaUnlockEcu?.security_keys.map((candidate) => <option value={candidate.key_hex} key={candidate.variant}>{candidate.variant} · {candidate.key_hex}</option>)}</select></label>
            <label>Confirmation<input value={psaUnlockConfirmation} onChange={(event) => setPsaUnlockConfirmation(event.target.value)} placeholder={`DEVERROUILLER ${psaUnlockEcuKey.toUpperCase()}`} /></label>
            <button className="danger-button" onClick={() => void unlockPsaConfiguration()} disabled={!psaCatalog?.security_access_enabled || !psaFirmwareReady || !psaLabChecksComplete || psaUnlockConfirmation !== `DEVERROUILLER ${psaUnlockEcuKey.toUpperCase()}` || psaBusy === "unlock"}>{psaBusy === "unlock" ? "Échange seed/key…" : "Déverrouiller sans écrire"}</button>
          </div>
          <p className="inline-alert">SecurityAccess est désactivé par défaut (`PSA_SECURITY_ACCESS_ENABLED=false`). Ce bouton referme immédiatement la session sans écrire. Le service `0x2E` n’est accessible que depuis l’atelier de télécodage avec sauvegarde et diff validé ; `0x31` et la programmation restent verrouillés.</p>
        </section>}

        {psaFeedback && <div className="psa-feedback"><strong>Opération terminée</strong><span>{psaFeedback}</span></div>}
      </div>
    );
  }
