import type { Dispatch, SetStateAction } from "react";

import { EmptyState } from "../components/ui";
import type { View } from "../navigation";
import type { PowertrainProfile } from "../sensorInventory";
import type { SensorInventoryRow } from "../types";

type InventoryCounts={measured:number;supported:number;missing:number;excluded:number};
type InventoryStatus="all"|"available"|"missing"|"excluded";
type SensorInventoryScreenProps={sensorInventoryRows:SensorInventoryRow[];inventoryCounts:InventoryCounts;injectionBusy:boolean;obdReadReady:boolean;setValidationFocusId:Dispatch<SetStateAction<string>>;readInjectionParameters:(destination?:View)=>Promise<void>;detectionBusy:boolean;detectionRemaining:number;startFullSensorDetection:(openSensors?:boolean,liveDataReads?:boolean)=>Promise<void>;setView:Dispatch<SetStateAction<View>>;focusedValidationRow:SensorInventoryRow|null;validationQueue:SensorInventoryRow[];activeIsFiat500:boolean;activeVehicleLabel:string;effectivePowertrainProfile:PowertrainProfile;setPowertrainProfile:Dispatch<SetStateAction<PowertrainProfile>>;powertrainProfile:PowertrainProfile;inventoryStatus:InventoryStatus;setInventoryStatus:Dispatch<SetStateAction<InventoryStatus>>;inventorySystems:string[];visibleInventoryRows:SensorInventoryRow[];inventoryPriorityOnly:boolean;setInventoryPriorityOnly:Dispatch<SetStateAction<boolean>>;inventorySystem:string;setInventorySystem:Dispatch<SetStateAction<string>>;inventorySearch:string;setInventorySearch:Dispatch<SetStateAction<string>>};

export function SensorInventoryScreen({
  sensorInventoryRows,
  inventoryCounts,
  injectionBusy,
  obdReadReady,
  setValidationFocusId,
  readInjectionParameters,
  detectionBusy,
  detectionRemaining,
  startFullSensorDetection,
  setView,
  focusedValidationRow,
  validationQueue,
  activeIsFiat500,
  activeVehicleLabel,
  effectivePowertrainProfile,
  setPowertrainProfile,
  powertrainProfile,
  inventoryStatus,
  setInventoryStatus,
  inventorySystems,
  visibleInventoryRows,
  inventoryPriorityOnly,
  setInventoryPriorityOnly,
  inventorySystem,
  setInventorySystem,
  inventorySearch,
  setInventorySearch
}: SensorInventoryScreenProps) {
    const applicableTotal = Math.max(1, sensorInventoryRows.length - inventoryCounts.excluded);
    const coveredCount = inventoryCounts.measured + inventoryCounts.supported;
    const coverage = Math.round(coveredCount / applicableTotal * 100);
    const actionFor = (row: SensorInventoryRow, emphasized = false) => {
      const className = emphasized ? "primary-button" : "ghost-button";
      if (["to_test", "supported"].includes(row.status)) {
        return <button className={className} disabled={injectionBusy || !obdReadReady} onClick={() => { setValidationFocusId(row.id); void readInjectionParameters("inventory"); }}>{injectionBusy ? "Lecture…" : "Tester maintenant en OBD"}</button>;
      }
      if (row.status === "to_observe") {
        return <button className={className} disabled={detectionBusy || detectionRemaining > 0} onClick={() => { setValidationFocusId(row.id); void startFullSensorDetection(false, false); }}>{detectionRemaining > 0 ? `${detectionRemaining} s` : "Observer le CAN 30 s"}</button>;
      }
      if (row.status === "to_decode") {
        return <button className={className} onClick={() => { setValidationFocusId(row.id); setView("discovery"); }}>Créer une capture annotée</button>;
      }
      if (row.status === "measured") {
        return <button className={className} onClick={() => setView(row.source === "OBD-II" ? "injection" : "studio")}>Voir la preuve</button>;
      }
      return null;
    };
    const focusIndex = focusedValidationRow ? validationQueue.findIndex((row) => row.id === focusedValidationRow.id) : -1;
    const nextValidationRow = validationQueue.length
      ? validationQueue[(Math.max(0, focusIndex) + 1) % validationQueue.length]
      : null;
    const validationMethod = focusedValidationRow?.status === "to_observe"
      ? { code: "CAN", title: "Observation passive", text: "Provoque uniquement la grandeur ciblée pendant la fenêtre de 30 secondes. La valeur doit évoluer dans le bon sens et revenir au repos." }
      : focusedValidationRow?.status === "to_decode"
        ? { code: activeIsFiat500 ? "FIAT" : "PSA", title: "Découverte annotée", text: "Répète trois fois la même action avec le même marqueur. Le post-traitement comparera automatiquement les fenêtres avant et après." }
        : { code: "OBD", title: "Lecture moteur normalisée", text: "Le calculateur indique d’abord les PID supportés, puis la valeur est lue et contrôlée avant d’être classée mesurée." };

    return (
      <div className="sensor-inventory-page">
        <section className="panel inventory-hero">
          <div className="inventory-hero-copy">
            <span className="eyebrow">Couverture diagnostic de {activeVehicleLabel}</span>
            <h2>{coverage}% des informations applicables couvertes</h2>
            <p>Le classement est recalculé à partir du dernier direct CAN et du dernier relevé OBD-II. Une ligne « à décoder » correspond à une donnée {activeIsFiat500 ? "Fiat documentée ou plausible" : "PSA plausible"}, pas à la preuve que le véhicule expose déjà sa valeur.</p>
            <div className="inventory-progress"><i style={{ width: `${coverage}%` }} /></div>
          </div>
          <label className="powertrain-selector">
            <span>Motorisation</span>
            <select value={effectivePowertrainProfile} disabled={activeIsFiat500} onChange={(event) => setPowertrainProfile(event.target.value as PowertrainProfile)}>
              <option value="unknown">Encore inconnue</option>
              <option value="gasoline">{activeIsFiat500 ? "Essence 1.2 8V" : "Essence THP / PureTech"}</option>
              <option value="diesel">Diesel BlueHDi</option>
            </select>
            <small>{activeIsFiat500 ? "Profil confirmé pour la Fiat 500 2010." : powertrainProfile === "unknown" ? "FAP, SCR et paramètres essence restent tous visibles." : "Les éléments incompatibles sont classés non applicables."}</small>
          </label>
        </section>

        <section className="inventory-summary-grid">
          <button className={inventoryStatus === "available" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "available" ? "all" : "available")}><i className="measured" /><span>Mesurés</span><strong>{inventoryCounts.measured}</strong><small>Valeur reçue</small></button>
          <button className={inventoryStatus === "missing" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "missing" ? "all" : "missing")}><i className="missing" /><span>À compléter</span><strong>{inventoryCounts.missing}</strong><small>Test ou décodage requis</small></button>
          <button className={inventoryStatus === "excluded" ? "active" : ""} onClick={() => setInventoryStatus(inventoryStatus === "excluded" ? "all" : "excluded")}><i className="excluded" /><span>Non applicables</span><strong>{inventoryCounts.excluded}</strong><small>Selon la motorisation</small></button>
          <div><span>Total catalogué</span><strong>{sensorInventoryRows.length}</strong><small>{inventorySystems.length - 1} systèmes</small></div>
        </section>

        <section className="panel validation-assistant">
          <div className="section-heading">
            <div><span className="eyebrow">Assistant de validation</span><h2>Une preuve à la fois</h2><p>L’outil choisit la méthode adaptée à la source et ne classe jamais un signal « validé » sur une simple supposition.</p></div>
            <span className={`status-pill ${validationQueue.length ? "neutral" : "good"}`}><i /> {validationQueue.length ? `${validationQueue.length} tests dans la file` : "File terminée"}</span>
          </div>
          {focusedValidationRow ? (
            <>
              <div className="validation-steps" aria-label="Étapes de validation">
                <div className="done"><span>1</span><strong>Cible choisie</strong><small>{focusedValidationRow.system}</small></div>
                <div className="active"><span>2</span><strong>Acquérir</strong><small>{validationMethod.title}</small></div>
                <div><span>3</span><strong>Contrôler</strong><small>Plage, réaction, cohérence</small></div>
                <div><span>4</span><strong>Classer</strong><small>Mesuré, plausible ou rejeté</small></div>
              </div>
              <div className="validation-focus-card">
                <div className="validation-method-code">{validationMethod.code}</div>
                <div className="validation-focus-copy">
                  <span>{focusedValidationRow.statusLabel} · priorité {focusedValidationRow.priority}</span>
                  <h3>{focusedValidationRow.label}</h3>
                  <p>{validationMethod.text}</p>
                  <code>{focusedValidationRow.reference ?? focusedValidationRow.source}</code>
                </div>
                <div className="validation-focus-actions">
                  {actionFor(focusedValidationRow, true)}
                  {nextValidationRow && <button className="ghost-button" onClick={() => setValidationFocusId(nextValidationRow.id)}>Passer au suivant</button>}
                </div>
              </div>
            </>
          ) : (
            <EmptyState title="Aucun test prioritaire" text="Toutes les informations testables de cette configuration disposent déjà d’une preuve." />
          )}
        </section>

        <section className="panel inventory-actions-panel">
          <div className="section-heading">
            <div><span className="eyebrow">Actualiser les preuves</span><h2>Tester la couverture réelle</h2><p>Les deux lectures sont séparées : le CAN passif n'émet rien; l'OBD-II envoie des requêtes de lecture au calculateur moteur.</p></div>
          </div>
          <div className="inventory-actions">
            <button className="inventory-action" onClick={() => void startFullSensorDetection(false, false)} disabled={detectionBusy || detectionRemaining > 0}>
              <span>CAN</span><div><strong>{detectionRemaining > 0 ? `Observation · ${detectionRemaining} s` : "Observer le CAN pendant 30 s"}</strong><small>Recherche les signaux diffusés spontanément</small></div>
            </button>
            <button className="inventory-action" onClick={() => void readInjectionParameters("inventory")} disabled={injectionBusy || !obdReadReady}>
              <span>OBD</span><div><strong>{injectionBusy ? "Lecture moteur en cours…" : "Tester les PID moteur"}</strong><small>{obdReadReady ? "6/14 validé · OBD 01/09 uniquement" : "Firmware principal compatible requis"}</small></div>
            </button>
            <button className="inventory-action" onClick={() => setView("discovery")}>
              <span>{activeIsFiat500 ? "FIAT" : "PSA"}</span><div><strong>Découvrir un paramètre constructeur</strong><small>Capture annotée et corrélation hors ligne</small></div>
            </button>
          </div>
          {!activeIsFiat500 && powertrainProfile === "unknown" && <p className="inline-alert">Sélectionne la motorisation exacte dès qu'elle est confirmée : cela évitera de compter l'AdBlue, le FAP diesel ou le cliquetis essence comme des manques.</p>}
        </section>

        <section className="panel inventory-list-panel">
          <div className="section-heading inventory-list-heading">
            <div><span className="eyebrow">{visibleInventoryRows.length} informations affichées</span><h2>Catalogue et état de découverte</h2></div>
            <label className="inventory-priority-toggle"><input type="checkbox" checked={inventoryPriorityOnly} onChange={(event) => setInventoryPriorityOnly(event.target.checked)} /><span>Priorité atelier uniquement</span></label>
          </div>
          <div className="inventory-toolbar">
            <div className="inventory-system-tabs">
              {inventorySystems.map((system) => <button className={inventorySystem === system ? "active" : ""} key={system} onClick={() => setInventorySystem(system)}>{system}</button>)}
            </div>
            <input value={inventorySearch} onChange={(event) => setInventorySearch(event.target.value)} placeholder="Rechercher injecteur, FAP, rétro, pneu…" aria-label="Rechercher dans l'inventaire" />
          </div>
          <div className="inventory-status-legend">
            <span><i className="measured" />Mesuré</span><span><i className="supported" />Supporté</span><span><i className="test" />À tester/observer</span><span><i className="decode" />À décoder</span><span><i className="unsupported" />Non exposé</span><span><i className="excluded" />Non applicable</span>
          </div>
          <div className="inventory-table">
            {visibleInventoryRows.map((row) => (
              <article className={`sensor-inventory-row status-${row.status}`} key={row.id}>
                <div className="inventory-row-state"><i /><span>{row.statusLabel}</span></div>
                <div className="inventory-row-main"><span>{row.system} · priorité {row.priority}{row.optional ? " · équipement optionnel" : ""}</span><strong>{row.label}</strong><p>{row.description}</p></div>
                <div className="inventory-row-source"><strong>{row.value ?? row.source}</strong><code>{row.reference ?? "—"}</code></div>
                <div className="inventory-row-action">{actionFor(row)}</div>
              </article>
            ))}
            {visibleInventoryRows.length === 0 && <EmptyState title="Aucun résultat" text="Modifie les filtres ou la recherche pour retrouver les paramètres masqués." />}
          </div>
        </section>
      </div>
    );
  }
