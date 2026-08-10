import type { CSSProperties, Dispatch, PointerEvent, RefObject, SetStateAction } from "react";

import { ExperimentalSignalsPanel } from "../components/ExperimentalSignalsPanel";
import { ReplayWarningIcon } from "../components/ReplayWarningIcon";
import type { View } from "../navigation";
import { STUDIO_COLUMNS, STUDIO_GRAPH_WINDOWS, STUDIO_ROW_HEIGHT, defaultStudioWidgets, replayGaugeCatalog, replayIndicatorCatalog, replayIndicatorState } from "../replay";
import type { CaptureStatus, DiagnosticVehicle, PassiveSensorSnapshot, ReplayGraphGeometry, ReplaySample, Status, StudioGraphWindowSeconds, StudioSensorStyle, StudioWidget, TransportCatalog, VehicleProfileSummary, VehicleVisualProfile } from "../types";

type StudioScreenProps={
 studioLiveSample:{point:ReplaySample;availableFields:string[]}|null; capture:CaptureStatus|null; captureName:string; setCaptureName:Dispatch<SetStateAction<string>>; transportConnectBusy:boolean;
 stopCapture:()=>Promise<void>; startCapture:(enableLiveDataReads?:boolean)=>Promise<void>; directPsaCompatible:boolean; activeVehicleLabel:string; activeIsFiat500:boolean; activeVehicleVisual:VehicleVisualProfile; passiveSensors:PassiveSensorSnapshot|null;
 studioGraphGeometries:Map<string,ReplayGraphGeometry>; setStudioGraphWindow:(id:string,windowSeconds:StudioGraphWindowSeconds)=>void; setView:Dispatch<SetStateAction<View>>;
 activeCommunicationProfile:VehicleProfileSummary|null; selectedDiagnosticVehicle:DiagnosticVehicle|null; activeCommunicationProfileKey:string; status:Status|null; selectedTransportId:string; setSelectedTransportId:Dispatch<SetStateAction<string>>; setTransportMessage:Dispatch<SetStateAction<string>>; transportCatalog:TransportCatalog|null; connectSelectedTransport:()=>Promise<void>; transportMessage:string;
 studioWidgetToAdd:string; setStudioWidgetToAdd:Dispatch<SetStateAction<string>>; addStudioWidget:()=>void; diagnosticReady:boolean; setError:Dispatch<SetStateAction<string>>; studioEditing:boolean; setStudioEditing:Dispatch<SetStateAction<boolean>>; setStudioWidgets:Dispatch<SetStateAction<StudioWidget[]>>; toggleStudioFullscreen:()=>Promise<void>; error:string; studioBoardRef:RefObject<HTMLDivElement|null>; studioWidgets:StudioWidget[];
 beginStudioInteraction:(event:PointerEvent,widget:StudioWidget,mode:"move"|"resize")=>void; setStudioSensorStyle:(id:string,kind:StudioSensorStyle)=>void; resizeStudioWidget:(id:string,delta:-1|1)=>void; removeStudioWidget:(id:string)=>void;
};

export function StudioScreen({
  studioLiveSample,
  capture,
  captureName,
  setCaptureName,
  transportConnectBusy,
  stopCapture,
  startCapture,
  directPsaCompatible,
  activeVehicleLabel,
  activeIsFiat500,
  activeVehicleVisual,
  passiveSensors,
  studioGraphGeometries,
  setStudioGraphWindow,
  setView,
  activeCommunicationProfile,
  selectedDiagnosticVehicle,
  activeCommunicationProfileKey,
  status,
  selectedTransportId,
  setSelectedTransportId,
  setTransportMessage,
  transportCatalog,
  connectSelectedTransport,
  transportMessage,
  studioWidgetToAdd,
  setStudioWidgetToAdd,
  addStudioWidget,
  diagnosticReady,
  setError,
  studioEditing,
  setStudioEditing,
  setStudioWidgets,
  toggleStudioFullscreen,
  error,
  studioBoardRef,
  studioWidgets,
  beginStudioInteraction,
  setStudioSensorStyle,
  resizeStudioWidget,
  removeStudioWidget
}: StudioScreenProps) {
    const point = studioLiveSample?.point ?? null;
    const liveAvailableFields = studioLiveSample?.availableFields ?? [];
    const gaugeDefinitions = replayGaugeCatalog.filter((definition) => !definition.rejected);
    const graphDefinitions = gaugeDefinitions.filter((definition) => !definition.status);
    const widgetTitle = (widget: StudioWidget) => {
      if (widget.kind === "gauge" || widget.kind === "graph" || widget.kind === "numeric" || widget.kind === "lamp") {
        return replayGaugeCatalog.find((definition) => definition.key === widget.key)?.label ?? "Capteur";
      }
      if (widget.kind === "indicator") {
        return replayIndicatorCatalog.find((definition) => definition.key === widget.key)?.label ?? "Témoin";
      }
      return { speed: "Vitesse", steering: "Volant", gear: "Rapport engagé", vehicle: "Véhicule", capture: "Enregistrement CAN" }[widget.kind];
    };

    const widgetContent = (widget: StudioWidget) => {
      if (widget.kind === "capture") {
        return (
          <div className={`studio-capture-widget ${capture?.active ? "recording" : ""}`}>
            <div className="studio-record-state"><i /><div><strong>{capture?.active ? "Direct + enregistrement en cours" : "Direct en attente"}</strong><small>{capture?.active ? capture.session_id : "Démarre la capture pour recevoir les trames en direct"}</small></div></div>
            <label>Nom de la session<input value={captureName} disabled={capture?.active} onChange={(event) => setCaptureName(event.target.value)} /></label>
            <button className={capture?.active ? "danger-button" : "primary-button"} disabled={transportConnectBusy} onClick={() => void (capture?.active ? stopCapture() : startCapture())}>{capture?.active ? "Arrêter et sauvegarder" : "Démarrer le direct"}</button>
            <div className="studio-capture-stats"><span>Direct 6/14 <strong>{(capture?.live_frame_count ?? capture?.frame_count ?? 0).toLocaleString("fr-FR")}</strong></span><span>Diag 3/8 <strong>{(capture?.diagnostic_frame_count ?? 0).toLocaleString("fr-FR")}</strong></span><span>Source <strong>{capture?.dual_can ? "Double CAN" : capture?.source ?? "—"}</strong></span></div>
          </div>
        );
      }
      if (!point) return <div className="studio-widget-empty">{!directPsaCompatible ? `Profil ${activeVehicleLabel} actif. Démarre le direct Live Data pour recevoir le CAN Fiat et les PID EOBD autorisés.` : "Démarre le direct pour recevoir les capteurs CAN."}</div>;
      if (widget.kind === "speed") {
        const speed = Math.max(0, point.speed_kph ?? 0);
        const ratio = Math.min(1, speed / 150);
        return (
          <div className="studio-speed-widget">
            <div className="studio-speed-dial" style={{ background: `conic-gradient(from 225deg, #62e39a 0deg ${ratio * 270}deg, #263039 ${ratio * 270}deg 270deg, transparent 270deg)` }}>
              <div><strong>{Math.round(speed)}</strong><span>km/h</span><small>{activeIsFiat500 ? "EOBD 01/0D" : "ABS roues"}</small></div>
            </div>
          </div>
        );
      }
      if (widget.kind === "steering") {
        const available = typeof point.steering_angle_deg === "number";
        const steering = point.steering_angle_deg ?? 0;
        const direction = Math.abs(steering) < 1 ? "centré" : steering < 0 ? "droite" : "gauche";
        return (
          <div className="studio-steering-widget">
            <img src={activeVehicleVisual.steeringImage} style={{ transform: `rotate(${available ? Math.max(-540, Math.min(540, -steering)) : 0}deg)` }} alt={activeVehicleVisual.steeringAlt} />
            <strong>{available ? `${Math.abs(steering).toFixed(1)}°` : "—"}</strong><span>{available ? direction : "à décoder"}</span>
          </div>
        );
      }
      if (widget.kind === "gear") {
        const available = typeof point.current_gear === "number" || Boolean(point.reverse);
        const label = point.reverse || point.current_gear === 9 ? "R" : typeof point.current_gear === "number" ? point.current_gear > 0 ? String(point.current_gear) : "N" : "—";
        const targetLabel = point.reverse || point.target_gear === 9 ? "R" : point.target_gear ?? "—";
        return (
          <div className={`studio-gear-widget ${point.gear_shift_active ? "shifting" : ""}`}>
            <strong>{label}</strong>
            <div>{[1, 2, 3, 4, 5, 6].map((gear) => <b key={gear} className={point.current_gear === gear ? "active" : point.target_gear === gear ? "target" : ""}>{gear}</b>)}</div>
            <span>{available ? `Cible ${targetLabel}` : "Boîte manuelle"}</span><small>{available ? point.gear_shift_active ? "Changement en cours" : "Rapport stabilisé" : "Rapport non exposé"}</small>
          </div>
        );
      }
      if (widget.kind === "vehicle") {
        const blinkOn = Math.floor((passiveSensors?.generated_at_us ?? 0) / 430_000) % 2 === 0;
        const left = blinkOn && ["left", "hazard"].includes(point.turn_signal ?? "off");
        const right = blinkOn && ["right", "hazard"].includes(point.turn_signal ?? "off");
        return (
          <div className="studio-vehicle-widget">
            <div className={`studio-light-beam left ${point.low_beam || point.high_beam ? "on" : ""}`} /><div className={`studio-light-beam right ${point.low_beam || point.high_beam ? "on" : ""}`} />
            <img src={activeVehicleVisual.topImage} alt={activeVehicleVisual.topAlt} />
            <i className={`studio-car-lamp front left ${left ? "on" : ""}`} /><i className={`studio-car-lamp front right ${right ? "on" : ""}`} />
            <i className={`studio-car-lamp rear left ${left ? "on" : ""}`} /><i className={`studio-car-lamp rear right ${right ? "on" : ""}`} />
            <span>{typeof point.low_beam === "boolean" ? point.low_beam ? "Feux ON" : "Feux OFF" : "Feux à décoder"} · {point.turn_signal ?? "clignotants à décoder"}</span>
          </div>
        );
      }
      if (widget.kind === "gauge") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key);
        if (!definition) return <div className="studio-widget-empty">Capteur inconnu.</div>;
        if (definition.rejected) return <div className="studio-widget-empty">Décodage rejeté pour ce véhicule. Consulte le rapport de validation.</div>;
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const logical = typeof raw === "boolean" ? raw : null;
        const ratio = definition.status ? logical ? 1 : 0 : numeric === null ? 0 : Math.max(0, Math.min(1, (numeric - definition.minimum) / (definition.maximum - definition.minimum)));
        const value = definition.status ? logical === null ? "—" : logical ? "Actif" : "Inactif" : numeric === 9 && ["current_gear", "target_gear"].includes(String(definition.key)) ? "R" : numeric?.toFixed(definition.precision ?? 0) ?? "—";
        return (
          <div className="studio-gauge-widget">
            <div style={{ background: `conic-gradient(${definition.color} 0deg ${ratio * 300}deg, #263039 ${ratio * 300}deg 300deg, transparent 300deg)` }}><div><strong>{value}</strong><span>{definition.unit}</span></div></div>
            <small>{definition.note}</small>
          </div>
        );
      }
      if (widget.kind === "numeric") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key);
        if (!definition) return <div className="studio-widget-empty">Capteur inconnu.</div>;
        if (definition.rejected) return <div className="studio-widget-empty">Décodage rejeté pour ce véhicule. Consulte le rapport de validation.</div>;
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const logical = typeof raw === "boolean" ? raw : null;
        const value = definition.status
          ? logical === null ? "—" : logical ? "ACTIF" : "INACTIF"
          : numeric === 9 && ["current_gear", "target_gear"].includes(String(definition.key)) ? "R" : numeric?.toFixed(definition.precision ?? 0) ?? "—";
        return (
          <div className="studio-numeric-widget" style={{ "--sensor-color": definition.color } as CSSProperties}>
            <i /><div><strong>{value}</strong><span>{definition.unit}</span></div><small>{definition.note}</small>
          </div>
        );
      }
      if (widget.kind === "lamp") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key && candidate.status);
        if (!definition) return <div className="studio-widget-empty">Ce capteur ne possède pas de mode voyant.</div>;
        const raw = point[definition.key];
        const active = typeof raw === "boolean" ? raw : typeof raw === "number" ? raw !== 0 : false;
        const available = liveAvailableFields.includes(String(definition.key));
        const icon = definition.key === "oil_pressure_switch" ? "oil" : "bulb";
        return (
          <div className={`studio-indicator-widget red ${active ? "active" : ""} ${!available ? "unavailable" : ""}`}>
            <div><ReplayWarningIcon kind={icon} /></div><strong>{available ? active ? "Allumé" : "Éteint" : "Signal absent"}</strong><small>{definition.note}</small>
          </div>
        );
      }
      if (widget.kind === "graph") {
        const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key);
        const geometry = studioGraphGeometries.get(widget.id);
        if (!definition || !geometry) return <div className="studio-widget-empty">Courbe indisponible.</div>;
        if (definition.rejected) return <div className="studio-widget-empty">Décodage rejeté sur cette Peugeot. Consulte le rapport de validation.</div>;
        const raw = point[definition.key];
        const numeric = typeof raw === "number" ? raw : null;
        const span = Math.max(.001, geometry.maximum - geometry.minimum);
        const markerY = numeric === null ? null : 172 - (numeric - geometry.minimum) / span * 164;
        return (
          <div className="studio-graph-widget">
            <div className="studio-graph-heading">
              <div><strong>{numeric?.toFixed(definition.precision ?? 0) ?? "—"}</strong><span>{definition.unit}</span></div>
              <label><span>Fenêtre</span><select value={widget.windowSeconds ?? 60} onChange={(event) => setStudioGraphWindow(widget.id, Number(event.target.value) as StudioGraphWindowSeconds)}>
                <option value="10">10 s</option><option value="30">30 s</option><option value="60">1 min</option><option value="300">5 min</option>
              </select></label>
            </div>
            <svg viewBox="0 0 900 180" preserveAspectRatio="none">
              <path className="chart-grid-line" d="M0 45H900M0 90H900M0 135H900" /><path className="chart-series-shadow" d={geometry.path} style={{ stroke: definition.color }} /><path className="chart-series" d={geometry.path} style={{ stroke: definition.color }} />
              {markerY !== null && <circle className="chart-marker" cx="900" cy={Math.max(8, Math.min(172, markerY))} r="6" style={{ fill: definition.color }} />}
            </svg>
          </div>
        );
      }
      if (widget.kind === "indicator") {
        const definition = replayIndicatorCatalog.find((candidate) => candidate.key === widget.key);
        if (!definition) return <div className="studio-widget-empty">Témoin inconnu.</div>;
        const state = replayIndicatorState(definition, point, { available_fields: liveAvailableFields });
        return (
          <div className={`studio-indicator-widget ${definition.color} ${state.active ? "active" : ""} ${!state.available ? "unavailable" : ""}`}>
            <div><ReplayWarningIcon kind={definition.icon} /></div><strong>{state.available ? state.active === null ? "État brut" : state.active ? "Allumé" : "Éteint" : "Signal absent"}</strong><small>{state.detail}</small>
          </div>
        );
      }
      return null;
    };

    return (
      <div className="studio-screen">
        <header className="studio-toolbar">
          <button className="studio-exit" onClick={() => setView("dashboard")}>← Menu</button>
          <div className="studio-brand"><span>OD</span><div><strong>Dashboard direct</strong><small>Disposition sauvegardée automatiquement</small></div></div>
          <button className={`studio-active-vehicle ${activeCommunicationProfile ? "loaded" : ""}`} disabled={capture?.active} onClick={() => setView(selectedDiagnosticVehicle ? "garage" : "identity")}><span>{selectedDiagnosticVehicle ? "VÉHICULE CHARGÉ" : "PROFIL COMMUNICATION"}</span><strong>{activeVehicleLabel}</strong><small>{selectedDiagnosticVehicle?.vin ?? activeCommunicationProfileKey ?? "Choisir une marque"}</small></button>
          <div className={`studio-live-source ${capture?.active ? "active" : ""}`}>
            <i /><div><strong>{capture?.active ? (capture.hybrid_obd_ready ? "CAN + OBD DIRECT" : capture.dual_can ? "DOUBLE CAN DIRECT" : "CAN DIRECT") : "DIRECT EN ATTENTE"}</strong><small>{capture?.active ? `${(capture.live_frame_count ?? capture.frame_count ?? 0).toLocaleString("fr-FR")} live · ${(capture.diagnostic_frame_count ?? 0).toLocaleString("fr-FR")} diag${typeof point?.engine_rpm === "number" ? ` · ${Math.round(point.engine_rpm)} tr/min` : ""}${typeof point?.battery_voltage_v === "number" ? ` · ${point.battery_voltage_v.toFixed(2)} V` : ""}` : "Clique sur Enregistrer pour démarrer"}</small></div>
          </div>
          <div className={`studio-esp-selector ${status?.gateway_verified || capture?.active ? "connected" : ""}`} title={capture?.active ? "Arrête la capture avant de changer d’ESP32" : undefined}>
            <i />
            <select aria-label="ESP32 à connecter" value={selectedTransportId} disabled={transportConnectBusy || capture?.active} onChange={(event) => { setSelectedTransportId(event.target.value); setTransportMessage(""); }}>
              <option value="">Choisir un ESP32…</option>
              <optgroup label="USB / Série">{(transportCatalog?.options ?? []).filter((option) => option.transport === "esp32_serial").map((option) => <option value={option.id} key={option.id}>{option.detected === false ? "○ " : "● "}{option.label}</option>)}</optgroup>
              <optgroup label="Wi-Fi">{(transportCatalog?.options ?? []).filter((option) => option.transport === "esp32_wifi").map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</optgroup>
            </select>
            <button disabled={!selectedTransportId || transportConnectBusy || capture?.active} onClick={() => void connectSelectedTransport()}>{transportConnectBusy ? "Connexion…" : "Connecter"}</button>
            {(transportMessage || status?.gateway_verified) && <small>{transportMessage || "ESP32 validé"}</small>}
          </div>
          <div className="studio-add-control">
            <select value={studioWidgetToAdd} onChange={(event) => setStudioWidgetToAdd(event.target.value)} aria-label="Widget à ajouter">
              <optgroup label="Instruments"><option value="speed">Vitesse</option><option value="steering">Volant</option><option value="gear">Rapport engagé</option><option value="vehicle">Véhicule</option><option value="capture">Enregistrement CAN</option></optgroup>
              <optgroup label="Jauges">{gaugeDefinitions.map((definition) => <option key={`g-${definition.key}`} value={`gauge:${definition.key}`}>{definition.label}</option>)}<option disabled>Consommation — diagnostic OBD requis</option></optgroup>
              <optgroup label="Graphes">{graphDefinitions.map((definition) => <option key={`c-${definition.key}`} value={`graph:${definition.key}`}>{definition.label}</option>)}</optgroup>
              <optgroup label="Valeurs numériques">{gaugeDefinitions.map((definition) => <option key={`n-${definition.key}`} value={`numeric:${definition.key}`}>{definition.label}</option>)}</optgroup>
              <optgroup label="Voyants capteur">{gaugeDefinitions.filter((definition) => definition.status).map((definition) => <option key={`l-${definition.key}`} value={`lamp:${definition.key}`}>{definition.label}</option>)}</optgroup>
              <optgroup label="Témoins">{replayIndicatorCatalog.map((definition) => <option key={`i-${definition.key}`} value={`indicator:${definition.key}`}>{definition.label}</option>)}</optgroup>
            </select>
            <button onClick={addStudioWidget}>+ Ajouter</button>
          </div>
          <button className={`studio-diagnostic ${diagnosticReady ? "ready" : ""}`} onClick={() => { setError(""); setView("ecus"); }}>ECU / Défauts</button>
          <button className={`studio-diagnostic studio-injection ${diagnosticReady ? "ready" : ""}`} onClick={() => { setError(""); setView("injection"); }}>Injection</button>
          <button className="studio-diagnostic studio-inventory" onClick={() => { setError(""); setView("inventory"); }}>Inventaire</button>
          <button className={capture?.active ? "studio-record active" : "studio-record"} disabled={transportConnectBusy} onClick={() => void (capture?.active ? stopCapture() : startCapture())}><i />{capture?.active ? `${capture.frame_count.toLocaleString("fr-FR")} · Sauvegarder` : "Enregistrer"}</button>
          <button className={studioEditing ? "studio-tool active" : "studio-tool"} onClick={() => setStudioEditing((editing) => !editing)}>{studioEditing ? "Verrouiller" : "Modifier"}</button>
          <button className="studio-tool" onClick={() => { if (window.confirm("Réinitialiser toute la disposition du dashboard ?")) setStudioWidgets(defaultStudioWidgets); }}>Réinitialiser</button>
          <button className="studio-tool" onClick={() => void toggleStudioFullscreen()}>Plein écran</button>
        </header>
        {error && <div className="studio-error"><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
        <div className="studio-live-area">
        <ExperimentalSignalsPanel point={point} />
        <div className={`studio-board ${studioEditing ? "editing" : "locked"}`} ref={studioBoardRef}>
          {studioWidgets.map((widget) => (
            <article
              className={`studio-widget studio-widget-${widget.kind}`}
              key={widget.id}
              style={{ left: `calc(${widget.x / STUDIO_COLUMNS * 100}% + 4px)`, top: widget.y * STUDIO_ROW_HEIGHT + 4, width: `calc(${widget.w / STUDIO_COLUMNS * 100}% - 8px)`, height: widget.h * STUDIO_ROW_HEIGHT - 8 }}
            >
              <header className="studio-widget-drag" onPointerDown={(event) => beginStudioInteraction(event, widget, "move")}>
                <strong>{widgetTitle(widget)}</strong>
                <div className="studio-widget-header-tools">
                  {["gauge", "graph", "numeric", "lamp"].includes(widget.kind) && <select
                    className="studio-widget-style-select"
                    aria-label={`Style d'affichage de ${widgetTitle(widget)}`}
                    value={widget.kind}
                    onPointerDown={(event) => event.stopPropagation()}
                    onChange={(event) => setStudioSensorStyle(widget.id, event.target.value as StudioSensorStyle)}
                  ><option value="gauge">Jauge</option>
                    {!replayGaugeCatalog.find((definition) => definition.key === widget.key)?.status && <option value="graph">Graphe</option>}
                    <option value="numeric">Numérique</option>
                    {replayGaugeCatalog.find((definition) => definition.key === widget.key)?.status && <option value="lamp">Voyant</option>}
                  </select>}
                  {studioEditing && <div className="studio-widget-actions">
                    <button title="Diminuer" aria-label={`Diminuer ${widgetTitle(widget)}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => resizeStudioWidget(widget.id, -1)}>−</button>
                    <button title="Agrandir" aria-label={`Agrandir ${widgetTitle(widget)}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => resizeStudioWidget(widget.id, 1)}>+</button>
                    <button title="Supprimer" aria-label={`Supprimer ${widgetTitle(widget)}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => removeStudioWidget(widget.id)}>×</button>
                  </div>}
                </div>
              </header>
              <div className="studio-widget-content">{widgetContent(widget)}</div>
              {studioEditing && <button className="studio-resize-handle" aria-label={`Redimensionner ${widgetTitle(widget)}`} onPointerDown={(event) => beginStudioInteraction(event, widget, "resize")}>⌟</button>}
            </article>
          ))}
          {studioWidgets.length === 0 && <div className="studio-empty-board"><strong>Dashboard vide</strong><span>Ajoute un instrument depuis la barre supérieure.</span></div>}
        </div>
        </div>
      </div>
    );
  }
