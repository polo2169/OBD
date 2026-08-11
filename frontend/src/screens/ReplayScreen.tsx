import type { Dispatch, SetStateAction } from "react";

import { API_BASE } from "../api";
import { ExperimentalSignalsPanel } from "../components/ExperimentalSignalsPanel";
import { ReplayWarningIcon } from "../components/ReplayWarningIcon";
import { EmptyState } from "../components/ui";
import { formatDate, formatDuration, formatReplayTime } from "../format";
import type { View } from "../navigation";
import {
  FIAT_500_HANDBOOK_URL, PEUGEOT_308_HANDBOOK_URL, cruiseModeLabel, cruiseXvvStateLabel, laneAssistStatusLabel,
  replayGaugeCatalog, replayIndicatorCatalog, replayIndicatorState, vehicleVisualForProfile,
} from "../replay";
import type {
  DiagnosticVehicle,
  DiscoverySession,
  ReplayData,
  ReplayGaugeDefinition,
  ReplayGraphGeometry,
  ReplayIndicatorDefinition,
  ReplaySample,
  ReplayValidation,
  RouteGeometry,
} from "../types";

type ReplayScreenProps = {
  sessions: DiscoverySession[]; selectedDiagnosticVin: string; replay: ReplayData | null;
  replaySessionId: string; replayBusy: boolean; loadReplay: (sessionId: string, force?: boolean) => Promise<void>;
  activeVehicleLabel: string; setView: Dispatch<SetStateAction<View>>; currentReplayPoint: ReplaySample | null;
  currentRouteGeometry: RouteGeometry; currentReplayIndex: number; replayTimeMs: number;
  selectedReplayGaugeKeys: string[]; selectedReplayGraphKeys: string[]; selectedReplayIndicatorKeys: string[];
  replayValidation: ReplayValidation | null; selectedDiagnosticVehicle: DiagnosticVehicle | null;
  sessionAssignmentBusy: string; assignSessionsToActiveVehicle: (sessionIds: string[]) => Promise<void>;
  setSignalManualValidation: (key: string, validated: boolean) => Promise<void>; clearSignalManualValidation: (key: string) => Promise<void>; signalValidationBusy: string;
  replayIndicatorToAdd: string; setReplayIndicatorToAdd: Dispatch<SetStateAction<string>>; addReplayIndicator: () => void;
  setSelectedReplayIndicatorKeys: Dispatch<SetStateAction<string[]>>; removeReplayIndicator: (key: string) => void;
  replayGaugeToAdd: string; setReplayGaugeToAdd: Dispatch<SetStateAction<string>>; addReplayGauge: () => void;
  setSelectedReplayGaugeKeys: Dispatch<SetStateAction<string[]>>; removeReplayGauge: (key: string) => void;
  replayGraphToAdd: string; setReplayGraphToAdd: Dispatch<SetStateAction<string>>; addReplayGraph: () => void;
  setSelectedReplayGraphKeys: Dispatch<SetStateAction<string[]>>; currentReplayGraphGeometries: Map<string, ReplayGraphGeometry>; removeReplayGraph: (key: string) => void;
  seekReplay: (timeMs: number) => void; setReplayPlaying: Dispatch<SetStateAction<boolean>>; replayPlaying: boolean; replayRate: number; setReplayRate: Dispatch<SetStateAction<number>>;
};

export function ReplayScreen({
  sessions,
  selectedDiagnosticVin,
  replay,
  replaySessionId,
  replayBusy,
  loadReplay,
  activeVehicleLabel,
  setView,
  currentReplayPoint,
  currentRouteGeometry,
  currentReplayIndex,
  replayTimeMs,
  selectedReplayGaugeKeys,
  selectedReplayGraphKeys,
  selectedReplayIndicatorKeys,
  replayValidation,
  selectedDiagnosticVehicle,
  sessionAssignmentBusy,
  assignSessionsToActiveVehicle,
  setSignalManualValidation,
  clearSignalManualValidation,
  signalValidationBusy,
  replayIndicatorToAdd,
  setReplayIndicatorToAdd,
  addReplayIndicator,
  setSelectedReplayIndicatorKeys,
  removeReplayIndicator,
  replayGaugeToAdd,
  setReplayGaugeToAdd,
  addReplayGauge,
  setSelectedReplayGaugeKeys,
  removeReplayGauge,
  replayGraphToAdd,
  setReplayGraphToAdd,
  addReplayGraph,
  setSelectedReplayGraphKeys,
  currentReplayGraphGeometries,
  removeReplayGraph,
  seekReplay,
  setReplayPlaying,
  replayPlaying,
  replayRate,
  setReplayRate
}: ReplayScreenProps) {
    const playableSessions = sessions.filter((session) => session.frame_count > 0 && (
      !selectedDiagnosticVin || !session.vin || session.vin === selectedDiagnosticVin
    ));
    const activeVehicleReplays = playableSessions.filter((session) => session.vin === selectedDiagnosticVin);
    const unassignedReplays = playableSessions.filter((session) => !session.vin);
    const selector = (
      <section className="panel replay-selector">
        <div>
          <span className="eyebrow">Source du replay</span>
          <strong>{replay?.name ?? "Choisir un enregistrement CAN"}</strong>
          <small>{replay
            ? `${replay.frame_count.toLocaleString("fr-FR")} trames · ${formatDuration(replay.duration_ms)} · ${(replay.source_size_bytes / 1024 / 1024).toFixed(1)} Mio`
            : "Le premier chargement prépare un cache de post-traitement sur le PC."}</small>
        </div>
        <select
          aria-label="Session à rejouer"
          value={replaySessionId}
          disabled={replayBusy || playableSessions.length === 0}
          onChange={(event) => void loadReplay(event.target.value)}
        >
          {!replaySessionId && <option value="">Sélectionner une session</option>}
          {activeVehicleReplays.length > 0 && <optgroup label={activeVehicleLabel}>{activeVehicleReplays.map((session) => (
            <option key={session.session_id} value={session.session_id}>{formatDate(session.started_at_us)} · {session.name}</option>
          ))}</optgroup>}
          {unassignedReplays.length > 0 && <optgroup label="Anciennes captures sans VIN">{unassignedReplays.map((session) => (
            <option key={session.session_id} value={session.session_id}>{formatDate(session.started_at_us)} · {session.name}</option>
          ))}</optgroup>}
        </select>
        <button
          className="ghost-button"
          disabled={!replaySessionId || replayBusy}
          onClick={() => void loadReplay(replaySessionId, true)}
        >
          Recalculer
        </button>
      </section>
    );

    if (playableSessions.length === 0 && !replayBusy) {
      return <>{selector}<section className="panel"><EmptyState title="Aucun trajet enregistré" text="Enregistre d'abord une session CAN, puis reviens ici pour la rejouer." action={<button className="primary-button" onClick={() => setView("discovery")}>Ouvrir l'enregistrement</button>} /></section></>;
    }
    if (replayBusy || !replay || !currentReplayPoint) {
      return <>{selector}<section className="panel replay-loading"><EmptyState title="Préparation du trajet…" text="Décodage CAN, échantillonnage temporel et reconstruction locale de la trajectoire. La capture originale reste intacte." /></section></>;
    }
    const replayIsFiat500 = replay.vehicle_profile === "fiat_500_generic";
    const replayVisual = vehicleVisualForProfile(replay.vehicle_profile);
    const replayProfileCompatible = !replay.vehicle_profile || replayIsFiat500 || replay.vehicle_profile.startsWith("peugeot_") || replay.vehicle_profile.startsWith("psa_");
    if (!replayProfileCompatible) {
      return <>{selector}<section className="panel"><EmptyState title={`Replay visuel indisponible pour ${replay.vehicle}`} text="La capture est correctement classée sous ce VIN, mais le décodeur dynamique Fiat n’est pas encore validé. Le fichier CAN brut reste conservé et analysable sans afficher de fausses valeurs Peugeot." action={<button className="secondary-button" onClick={() => setView("discovery")}>Ouvrir l’analyse brute</button>} /></section></>;
    }

    const point = currentReplayPoint;
    const coordinate = currentRouteGeometry.coordinates[currentReplayIndex] ?? { x: 380, y: 235 };
    const progress = replay.duration_ms ? replayTimeMs / replay.duration_ms : 0;
    const speed = Math.max(0, point.speed_kph ?? 0);
    const rpm = Math.max(0, point.engine_rpm ?? 0);
    const currentGearLabel = point.reverse || point.current_gear === 9 ? "R" : typeof point.current_gear === "number" ? point.current_gear > 0 ? String(point.current_gear) : "N" : "—";
    const targetGearLabel = point.reverse || point.target_gear === 9 ? "R" : (point.target_gear ?? 0) > 0 ? String(point.target_gear) : "—";
    const steeringAvailable = typeof point.steering_angle_deg === "number";
    const steering = point.steering_angle_deg ?? 0;
    const acceleratorAvailable = typeof point.accelerator_pct === "number";
    const accelerator = Math.max(0, Math.min(100, point.accelerator_pct ?? 0));
    const brakeAvailable = typeof point.brake_active === "boolean";
    const blinkOn = Math.floor(replayTimeMs / 430) % 2 === 0;
    const leftIndicator = blinkOn && ["left", "hazard"].includes(point.turn_signal ?? "off");
    const rightIndicator = blinkOn && ["right", "hazard"].includes(point.turn_signal ?? "off");
    const indicatorLabel = point.turn_signal === "left"
      ? "Gauche"
      : point.turn_signal === "right"
        ? "Droite"
        : point.turn_signal === "hazard" ? "Détresse" : "Arrêt";
    const laneDeparture = point.lane_departure === 1 ? "right" : point.lane_departure === 2 ? "left" : "none";
    const laneDepartureEventCount = replay.events.filter((event) => event.kind === "adas").length;
    const speedGaugeAngle = Math.min(270, speed / Math.max(140, replay.max_speed_kph) * 270);
    const replayDate = new Date(replay.start_timestamp_us / 1000);
    const roadConfirmed = replay.route_method === "driver_confirmed_osrm";
    const yawReconstructed = replay.route_method === "dead_reckoning_speed_yaw";
    const gpsFused = replay.route_method === "gps_can_fusion";
    const gpsMeasured = replay.route_method === "browser_gps" || gpsFused || roadConfirmed;
    const gpsAnchored = replay.route_method === "dead_reckoning_gps_anchor";
    const openStreetMapUrl = point.latitude !== null && point.latitude !== undefined && point.longitude !== null && point.longitude !== undefined
      ? `https://www.openstreetmap.org/?mlat=${point.latitude}&mlon=${point.longitude}#map=16/${point.latitude}/${point.longitude}`
      : "";
    const steeringDirection = Math.abs(steering) < 1 ? "centré" : steering < 0 ? "droite" : "gauche";
    const availableGaugeDefinitions = replayGaugeCatalog.filter((definition) =>
      replay.available_fields.includes(definition.key)
      && !definition.rejected
      && replay.field_quality[String(definition.key)] !== "rejected_on_vehicle"
    );
    const selectedGaugeDefinitions = selectedReplayGaugeKeys
      .map((key) => availableGaugeDefinitions.find((definition) => definition.key === key))
      .filter((definition): definition is ReplayGaugeDefinition => definition !== undefined);
    const addableGaugeDefinitions = availableGaugeDefinitions.filter((definition) => !selectedReplayGaugeKeys.includes(definition.key));
    const availableGraphDefinitions = availableGaugeDefinitions.filter((definition) => !definition.status);
    const selectedGraphDefinitions = selectedReplayGraphKeys
      .map((key) => availableGraphDefinitions.find((definition) => definition.key === key))
      .filter((definition): definition is ReplayGaugeDefinition => definition !== undefined);
    const addableGraphDefinitions = availableGraphDefinitions.filter((definition) => !selectedReplayGraphKeys.includes(definition.key));
    const selectedIndicatorDefinitions = selectedReplayIndicatorKeys
      .map((key) => replayIndicatorCatalog.find((definition) => definition.key === key))
      .filter((definition): definition is ReplayIndicatorDefinition => definition !== undefined);
    const addableIndicatorDefinitions = replayIndicatorCatalog.filter((definition) => !selectedReplayIndicatorKeys.includes(definition.key));
    const validationByKey = new Map((replayValidation?.signals ?? []).map((item) => [item.key, item]));
    const unavailableValidationCount = (replayValidation?.signals ?? []).filter((item) => item.status === "unavailable").length;
    const candidateValidationCount = replayValidation
      ? replayValidation.signal_count - replayValidation.validated_count - replayValidation.plausible_count - replayValidation.suspicious_count - unavailableValidationCount
      : 0;

    return (
      <div className="replay-page">
        {selector}
        {replay.vin && replay.vin !== selectedDiagnosticVin && <p className="inline-alert danger-alert">Ce replay appartient au VIN {replay.vin}, différent du véhicule actif. Recharge le bon véhicule depuis le Garage.</p>}
        {!replay.vin && selectedDiagnosticVehicle && <div className="replay-assignment-strip"><div><strong>Capture non classée</strong><span>Associe-la à {activeVehicleLabel} pour l’intégrer à sa chronologie.</span></div><button className="secondary-button" disabled={Boolean(sessionAssignmentBusy)} onClick={() => void assignSessionsToActiveVehicle([replay.session_id])}>{sessionAssignmentBusy === replay.session_id ? "Association…" : "Associer au véhicule actif"}</button></div>}

        <section className="replay-summary-grid">
          <article><span>{roadConfirmed ? "Distance routière" : gpsMeasured ? "Distance GPS" : "Distance reconstruite"}</span><strong>{replay.distance_km.toFixed(2)} <small>km</small></strong></article>
          <article><span>Vitesse maximale</span><strong>{replay.max_speed_kph.toFixed(1)} <small>km/h</small></strong></article>
          <article><span>Vitesse moyenne roulante</span><strong>{replay.average_moving_speed_kph.toFixed(1)} <small>km/h</small></strong></article>
          <article><span>Début des données</span><strong>{replayDate.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</strong></article>
        </section>

        <section className="panel fuel-consumption-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Estimation trajet</span>
              <h2>Consommation</h2>
              <p>Calculée à partir du niveau de carburant filtré (flotteur), sur ce trajet uniquement — pas un débitmètre instantané.</p>
            </div>
          </div>
          {typeof replay.estimated_fuel_consumption_l_100km === "number" ? (
            <div className="fuel-consumption-value">
              <strong>{replay.estimated_fuel_consumption_l_100km.toFixed(1)}</strong>
              <span>L/100km · estimation</span>
            </div>
          ) : (
            <p className="inline-alert">{replay.fuel_consumption_note ?? "Estimation non calculable sur cette capture."}</p>
          )}
          {typeof replay.estimated_fuel_consumption_l_100km === "number" && replay.fuel_consumption_note && (
            <p className="fuel-consumption-note">{replay.fuel_consumption_note}</p>
          )}
        </section>

        <ExperimentalSignalsPanel
          point={point}
          validation={replayValidation}
          onValidate={(key, validated) => void setSignalManualValidation(key, validated)}
          onClear={(key) => void clearSignalManualValidation(key)}
          busyKey={signalValidationBusy}
        />

        {replayValidation && (
          <section className="panel replay-validation-panel">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Contrôle de cohérence de la capture</span>
                <h2>Validation des capteurs, jauges et rapports</h2>
                <p>Preuves croisées moteur, injection, freinage, roues, direction et détection des mesures absentes ou invalides.</p>
              </div>
              <span className={`source-badge ${replayValidation.suspicious_count ? "suspicious" : "measured"}`}>{replayValidation.suspicious_count ? `${replayValidation.suspicious_count} à vérifier` : "Aucune incohérence forte"}</span>
            </div>
            <div className="validation-summary-grid">
              <article><span>Validés</span><strong>{replayValidation.validated_count}</strong><small>Preuve croisée ou test véhicule</small></article>
              <article><span>Plausibles</span><strong>{replayValidation.plausible_count}</strong><small>Plage cohérente, étalon absent</small></article>
              <article><span>À confirmer</span><strong>{candidateValidationCount}</strong><small>Candidat sans preuve suffisante</small></article>
              <article><span>Suspects</span><strong>{replayValidation.suspicious_count}</strong><small>Incohérence ou hors plage</small></article>
              <article><span>Indisponibles</span><strong>{unavailableValidationCount}</strong><small>Non mesuré sur le CAN passif</small></article>
            </div>
            <details className="validation-details">
              <summary>Voir le détail des {replayValidation.signal_count} signaux</summary>
              <div className="validation-signal-list">
                {replayValidation.signals.map((signal) => (
                  <article className={signal.status} key={signal.key}>
                    <span className={`validation-badge ${signal.status}`}>{signal.status === "validated" ? "Validé" : signal.status === "plausible" ? "Plausible" : signal.status === "suspicious" ? "Suspect" : signal.status === "unavailable" ? "Indisponible" : "À confirmer"}</span>
                    <div><strong>{signal.label}</strong><code>{signal.key}</code>{signal.evidence.map((line) => <p key={line}>{line}</p>)}</div>
                    <small>{signal.sample_count.toLocaleString("fr-FR")} valeurs · {signal.transitions} transitions{signal.minimum !== null && signal.minimum !== undefined ? ` · ${signal.minimum}…${signal.maximum}` : ""}</small>
                    {signal.status !== "unavailable" && (
                      <div className="validation-manual-actions">
                        {signal.manual_validation === true ? (
                          <>
                            <span className="manual-validation-tag confirmed">Confirmé manuellement</span>
                            <button className="ghost-button" disabled={signalValidationBusy === signal.key} onClick={() => void clearSignalManualValidation(signal.key)}>Retirer</button>
                          </>
                        ) : signal.manual_validation === false ? (
                          <>
                            <span className="manual-validation-tag rejected">Invalidé manuellement</span>
                            <button className="ghost-button" disabled={signalValidationBusy === signal.key} onClick={() => void clearSignalManualValidation(signal.key)}>Retirer</button>
                          </>
                        ) : (
                          <>
                            <button className="secondary-button" disabled={signalValidationBusy === signal.key} onClick={() => void setSignalManualValidation(signal.key, true)}>{signalValidationBusy === signal.key ? "…" : "Confirmer ce signal"}</button>
                            <button className="ghost-button" disabled={signalValidationBusy === signal.key} onClick={() => void setSignalManualValidation(signal.key, false)}>Marquer invalide</button>
                          </>
                        )}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </details>
          </section>
        )}

        <section className="replay-hero-grid">
          <article className="panel replay-map-panel">
            <div className="section-heading replay-map-heading">
              <div>
                <span className="eyebrow">Carte de mouvement</span>
                <h2>{roadConfirmed ? "Parcours routier confirmé" : gpsFused ? "Parcours réel avec virages CAN" : gpsMeasured ? "Trajet GPS enregistré" : gpsAnchored ? "Trajectoire ancrée par GPS" : yawReconstructed ? "Trajectoire CAN par lacet ESP" : "Trajectoire locale reconstruite"}</h2>
                <p>{roadConfirmed
                  ? "Francazal → Portet → A64 → périphérique extérieur A620 → Rangueil · progression synchronisée par la vitesse CAN"
                  : gpsFused
                  ? `${replay.gps_point_count.toLocaleString("fr-FR")} positions GPS · virages reconstruits par vitesse et volant puis recalés sur le GPS`
                  : gpsMeasured ? `${replay.gps_point_count.toLocaleString("fr-FR")} positions synchronisées avec les trames CAN`
                  : gpsAnchored ? "Une position absolue + déplacement estimé par vitesse et volant" : "Vitesse ABS + angle du volant · origine et orientation arbitraires"}</p>
              </div>
              <div className="replay-map-actions">
                <span className={`source-badge ${gpsMeasured ? "measured" : "estimated"}`}>{roadConfirmed ? "Route confirmée" : gpsFused ? "GPS + CAN" : gpsMeasured ? "GPS réel" : gpsAnchored ? "GPS ancré" : yawReconstructed ? "Lacet ESP" : "GPS absent"}</span>
                {replay.gps_available && <a className="ghost-button" href={`${API_BASE}/api/learn/replay/${encodeURIComponent(replay.session_id)}/route.geojson`} download={`${replay.session_id}.geojson`}>Exporter GeoJSON</a>}
                {openStreetMapUrl && <a className="ghost-button" href={openStreetMapUrl} target="_blank" rel="noreferrer">Voir sur OSM</a>}
              </div>
            </div>
            <div className="route-map">
              <svg viewBox="0 0 760 470" role="img" aria-label={roadConfirmed ? "Trajet routier confirmé par le conducteur" : gpsMeasured ? "Trajet mesuré par GPS" : "Trajectoire reconstruite sans trace GPS complète"}>
                <defs>
                  <pattern id="map-grid" width="30" height="30" patternUnits="userSpaceOnUse">
                    <path d="M 30 0 L 0 0 0 30" className="map-grid-line" fill="none" />
                  </pattern>
                  <filter id="route-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                  </filter>
                </defs>
                {currentRouteGeometry.mapTiles.length
                  ? currentRouteGeometry.mapTiles.map((tile) => (
                    <image key={tile.key} href={tile.href} x={tile.x} y={tile.y} width="256" height="256" className="osm-tile" />
                  ))
                  : <rect width="760" height="470" fill="url(#map-grid)" />}
                {!currentRouteGeometry.mapTiles.length && !replay.gps_available && <>
                  <path className="france-silhouette" d="M333 36 L409 54 466 91 489 139 527 174 506 221 521 262 478 295 456 352 404 405 357 438 314 405 264 386 231 342 196 319 207 266 184 218 215 174 221 121 273 96 292 55 Z" />
                  <path className="france-corsica" d="M529 350 C544 358 548 382 536 401 C525 388 520 367 529 350 Z" />
                  <text x="380" y="240" className="map-watermark">FRANCE · POSITION ABSOLUE INDISPONIBLE</text>
                </>}
                <path d={currentRouteGeometry.path} className="route-shadow" />
                <path d={currentRouteGeometry.path} className="route-trace" pathLength={100} />
                <path
                  d={currentRouteGeometry.path}
                  className="route-progress"
                  pathLength={100}
                  strokeDasharray="100"
                  strokeDashoffset={100 - progress * 100}
                  filter="url(#route-glow)"
                />
                {currentRouteGeometry.gpsCoordinates.map((gpsPoint, index) => <g key={`gps-${index}`} className="gps-fix">
                  <circle cx={gpsPoint.x} cy={gpsPoint.y} r={gpsPoint.accuracyPx} className="gps-accuracy" />
                  <circle cx={gpsPoint.x} cy={gpsPoint.y} r="3.5" className="gps-fix-center" />
                </g>)}
                <circle cx={currentRouteGeometry.coordinates[0]?.x} cy={currentRouteGeometry.coordinates[0]?.y} r="5" className="route-start" />
                <image
                  href={replayVisual.topImage}
                  x={coordinate.x - 26}
                  y={coordinate.y - 26}
                  width="52"
                  height="52"
                  transform={`rotate(${point.heading_deg + (replayVisual.frontAtTop ? 0 : 180)} ${coordinate.x} ${coordinate.y})`}
                  className="map-car"
                />
                <circle cx={coordinate.x} cy={coordinate.y} r="3" className="map-car-center" />
              </svg>
              {currentRouteGeometry.mapTiles.length > 0 && <div className="osm-attribution">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors</div>}
              <div className="map-readout">
                <span><i className="measured-dot" />Vitesse mesurée <strong>{speed.toFixed(1)} km/h</strong></span>
                <span><i className={gpsMeasured ? "measured-dot" : "estimated-dot"} />Cap {roadConfirmed ? "routier" : gpsFused ? "CAN recalé" : gpsMeasured ? "GPS" : "estimé"} <strong>{point.heading_deg.toFixed(0)}°</strong></span>
                <span>Distance <strong>{(point.distance_m / 1000).toFixed(2)} km</strong></span>
                {point.latitude !== null && point.latitude !== undefined && point.longitude !== null && point.longitude !== undefined && (
                  <span>Coordonnées <strong>{point.latitude.toFixed(6)}, {point.longitude.toFixed(6)}</strong></span>
                )}
                {point.gps_accuracy_m !== null && point.gps_accuracy_m !== undefined && <span>Précision <strong>±{Math.round(point.gps_accuracy_m)} m</strong></span>}
              </div>
            </div>
          </article>

          <article className="panel vehicle-panel">
            <div className="section-heading">
              <div><span className="eyebrow">État carrosserie</span><h2>{replayVisual.label} vue du dessus</h2></div>
              <span className="source-badge candidate">{replayIsFiat500 ? "EOBD + CAN Fiat" : "CAN décodé"}</span>
            </div>
            <div className="vehicle-stage">
              <div className={`headlight-cone left ${point.low_beam || point.high_beam ? "on" : ""} ${point.high_beam ? "high" : ""}`} />
              <div className={`headlight-cone right ${point.low_beam || point.high_beam ? "on" : ""} ${point.high_beam ? "high" : ""}`} />
              <img src={replayVisual.topImage} alt={replayVisual.topAlt} className="vehicle-image" style={{ transform: replayVisual.frontAtTop ? "none" : "rotate(180deg)" }} />
              <span className="vehicle-mirror left" aria-label="Rétroviseur gauche visible"><i /></span>
              <span className="vehicle-mirror right" aria-label="Rétroviseur droit visible"><i /></span>
              <i className={`vehicle-lamp front left indicator ${leftIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp front right indicator ${rightIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp rear left indicator ${leftIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp rear right indicator ${rightIndicator ? "on" : ""}`} />
              <i className={`vehicle-lamp rear left brake ${point.brake_active ? "on" : ""}`} />
              <i className={`vehicle-lamp rear right brake ${point.brake_active ? "on" : ""}`} />
            </div>
            <div className="vehicle-state-strip">
              <span className={point.low_beam ? "active" : ""}>Croisement</span>
              <span className={point.high_beam ? "blue-active" : ""}>Route</span>
              <span className={point.turn_signal !== "off" ? "amber-active" : ""}>Cligno {indicatorLabel}</span>
              <span className={point.brake_active ? "red-active" : ""}>Frein</span>
            </div>
            <div className="mirror-status-strip">
              <div><span className="mirror-preview left"><i /></span><p><strong>Rétroviseur gauche</strong><small>Visible · rabattement CAN indisponible</small></p></div>
              <div><span className="mirror-preview right"><i /></span><p><strong>Rétroviseur droit</strong><small>Visible · rabattement CAN indisponible</small></p></div>
            </div>
          </article>
        </section>

        <section className="cockpit-grid">
          <article className="panel instrument-panel">
            <div className="section-heading"><div><span className="eyebrow">Combiné</span><h2>Instruments conducteur</h2></div><span className="source-badge candidate">{replayIsFiat500 ? "EOBD normalisé" : "OpenDBC candidat"}</span></div>
            <div className="instrument-layout">
              <div className="speed-gauge-wrap">
                <div
                  className="speed-gauge"
                  style={{ background: `conic-gradient(from 225deg, #62e39a 0deg ${speedGaugeAngle}deg, #263039 ${speedGaugeAngle}deg 270deg, transparent 270deg)` }}
                >
                  <div><strong>{Math.round(speed)}</strong><span>km/h</span><small>{replayIsFiat500 ? "EOBD 01/0D" : "ABS roues"}</small></div>
                </div>
              </div>
              <div className="engine-readouts">
                <div><span>Régime moteur</span><strong>{Math.round(rpm).toLocaleString("fr-FR")} <small>tr/min</small></strong><i><b style={{ width: `${Math.min(100, rpm / 6000 * 100)}%` }} /></i></div>
                  {replayIsFiat500 ? <>
                    <div><span>Charge moteur</span><strong>{typeof point.engine_load_pct === "number" ? point.engine_load_pct.toFixed(1) : "—"} <small>%</small></strong></div>
                    <div><span>Pression collecteur</span><strong>{typeof point.manifold_pressure_kpa === "number" ? point.manifold_pressure_kpa.toFixed(0) : "—"} <small>kPa</small></strong></div>
                    <div><span>Position papillon</span><strong>{typeof point.throttle_position_pct === "number" ? point.throttle_position_pct.toFixed(1) : typeof point.fiat_throttle_candidate_pct === "number" ? point.fiat_throttle_candidate_pct.toFixed(1) : "—"} <small>%</small></strong></div>
                    <div><span>Air d'admission</span><strong>{typeof point.intake_air_temperature_c === "number" ? point.intake_air_temperature_c.toFixed(0) : "—"} <small>°C</small></strong></div>
                    <div><span>Débit d'air</span><strong>{typeof point.mass_air_flow_g_s === "number" ? point.mass_air_flow_g_s.toFixed(2) : "—"} <small>g/s</small></strong></div>
                    <div><span>Pédale accélérateur</span><strong>{typeof point.accelerator_pct === "number" ? point.accelerator_pct.toFixed(1) : "—"} <small>%</small></strong></div>
                    <div><span>Tension batterie</span><strong>{typeof point.battery_voltage_v === "number" ? point.battery_voltage_v.toFixed(2) : "—"} <small>V</small></strong></div>
                    <div><span>Température moteur</span><strong>{typeof point.coolant_temperature_c === "number" ? point.coolant_temperature_c.toFixed(0) : "—"} <small>°C</small></strong></div>
                  </> : <>
                    <div><span>Couple moteur</span><strong>{typeof point.engine_torque_nm === "number" ? point.engine_torque_nm.toFixed(0) : "—"} <small>Nm</small></strong></div>
                    <div><span>Accélération long.</span><strong>{typeof point.longitudinal_accel_ms2 === "number" ? point.longitudinal_accel_ms2.toFixed(2) : "—"} <small>m/s²</small></strong></div>
                    <div><span>Accélération lat.</span><strong>{typeof point.lateral_accel_ms2 === "number" ? point.lateral_accel_ms2.toFixed(2) : "—"} <small>m/s²</small></strong></div>
                    <div><span>Vitesse de lacet</span><strong>{typeof point.yaw_rate_deg_s === "number" ? point.yaw_rate_deg_s.toFixed(1) : "—"} <small>°/s</small></strong></div>
                  </>}
                <div className={`gear-readout ${point.gear_shift_active ? "shifting" : ""}`}>
                  <span>Rapport engagé</span>
                  <strong>{currentGearLabel}</strong>
                  <div className="gear-scale">
                    {[1, 2, 3, 4, 5, 6].map((gear) => <b key={gear} className={point.current_gear === gear ? "active" : point.target_gear === gear ? "target" : ""}>{gear}</b>)}
                  </div>
                  <small>{typeof point.current_gear === "number" || point.reverse ? `Cible ${targetGearLabel} · ${point.gear_shift_active ? "changement en cours" : "rapport stabilisé"}` : "Rapport non exposé pour cette session"}</small>
                </div>
              </div>
              <div className="driver-inputs">
                <div className="steering-wheel-block">
                  <img src={replayVisual.steeringImage} style={{ transform: `rotate(${steeringAvailable ? Math.max(-540, Math.min(540, -steering)) : 0}deg)` }} alt={replayVisual.steeringAlt} />
                  <strong>{steeringAvailable ? `${Math.abs(steering).toFixed(1)}°` : "—"}</strong><span>{steeringAvailable ? `angle volant · ${steeringDirection}` : "angle volant non décodé"}</span>
                </div>
                <div className="pedal-stack">
                  <div><span>Accélérateur</span><i><b style={{ height: `${acceleratorAvailable ? accelerator : 0}%` }} /></i><strong>{acceleratorAvailable ? `${accelerator.toFixed(0)}%` : "—"}</strong></div>
                  <div className={point.brake_active ? "pressed" : ""}><span>Frein</span><i><b style={{ height: point.brake_active ? "100%" : "0%" }} /></i><strong>{brakeAvailable ? point.brake_active ? "ON" : "OFF" : "—"}</strong></div>
                </div>
              </div>
            </div>
          </article>

          <article className="panel adas-panel">
            {replayIsFiat500 ? <>
              <div className="section-heading"><div><span className="eyebrow">Reconstruction Fiat</span><h2>Qualité du trajet</h2></div><span className="source-badge candidate">Pas de valeur inventée</span></div>
              <div className="route-capability-card">
                <strong>{replay.gps_available ? "Trajectoire GPS disponible" : steeringAvailable || typeof point.yaw_rate_deg_s === "number" ? "Trajectoire CAN estimable" : "Cap non observable sans GPS"}</strong>
                <p>La vitesse et le régime viennent de l’EOBD/du CAN Fiat. Les virages utilisent le GPS du navigateur tant que l’angle volant ou le lacet Fiat ne sont pas décodés.</p>
              </div>
              <div className="adas-state-grid">
                <div><span>Vitesse EOBD</span><strong>{typeof point.speed_kph === "number" ? "Mesurée" : "Absente"}</strong><small>Mode 01 · PID 0D</small></div>
                <div><span>Angle volant</span><strong>{steeringAvailable ? `${steering.toFixed(1)}°` : "À décoder"}</strong><small>Capteur ESP optionnel selon équipement</small></div>
                <div><span>Vitesse de lacet</span><strong>{typeof point.yaw_rate_deg_s === "number" ? `${point.yaw_rate_deg_s.toFixed(1)}°/s` : "À décoder"}</strong><small>Disponible seulement avec le bloc ESP/capteur combiné</small></div>
                <div><span>GPS navigateur</span><strong>{replay.gps_available ? `${replay.gps_point_count} points` : "Absent"}</strong><small>Source privilégiée pour cette première version Fiat</small></div>
              </div>
            </> : <>
              <div className="section-heading"><div><span className="eyebrow">Aides à la conduite</span><h2>Lecture ADAS</h2></div><span className="source-badge measured">0x3F2 couple R2 observé</span></div>
              <div className={`lane-visual departure-${laneDeparture}`}>
                <i className="lane-line left" /><i className="lane-line right" />
                <span className="lane-car">▲</span>
                <b>{point.lane_departure ? "Alerte de ligne" : "Voie stable"}</b>
              </div>
              <div className="adas-state-grid">
                <div className={`lka-validation-card${point.lane_assist_status === 6 ? " state-danger" : point.lane_assist_status === 5 ? " state-warning" : ""}`}>
                  <div className="lka-validation-heading">
                    <span>Maintien dans la voie — LANE_KEEP_ASSIST</span>
                    <strong className={point.lane_assist_status === 4 ? "success-text" : point.lane_assist_status === 5 || point.lane_assist_status === 6 ? "warning-text" : ""}>
                      {laneAssistStatusLabel(point.lane_assist_status)}
                    </strong>
                  </div>
                  <div className="lka-candidate-grid">
                    <div className={`lka-candidate-indicator${point.lane_assist_status === 4 ? " active" : ""}${point.lane_assist_status === 5 || point.lane_assist_status === 6 ? " alert" : ""}`}>
                      <span>État STATUS</span>
                      <strong>{point.lane_assist_status ?? "—"}</strong>
                      <small>0-7 · 4 = actif · 5 = défaut · 6 = collision</small>
                    </div>
                    <div className={`lka-candidate-indicator${point.lane_departure ? " alert" : ""}`}>
                      <span>Franchissement</span>
                      <strong>{point.lane_departure === 1 ? "Droite" : point.lane_departure === 2 ? "Gauche" : point.lane_departure ? `Brut ${point.lane_departure}` : "Aucun"}</strong>
                      <small>LANE_DEPARTURE · alerte de ligne</small>
                    </div>
                    <div className={`lka-candidate-indicator${point.lka_active ? " active" : ""}`}>
                      <span>État déclaré</span>
                      <strong>{point.lka_active ? "Actif" : "Non actif"}</strong>
                      <small>Dérivée de STATUS = 4</small>
                    </div>
                    <div className="lka-candidate-indicator">
                      <span>Mode LXA</span>
                      <strong>{point.lka_mode === 0 ? "LKA" : point.lka_mode === 1 ? "LPA" : "—"}</strong>
                      <small>LXA_ACTIVATION · sélecteur, pas état actif</small>
                    </div>
                    <div className={`lka-candidate-indicator${point.lka_torque_command_raw ? " active" : ""}`}>
                      <span>Commande couple R2</span>
                      <strong>{typeof point.lka_torque_command_raw === "number" ? `${point.lka_torque_command_raw > 0 ? "+" : ""}${point.lka_torque_command_raw} raw` : "—"}</strong>
                      <small>0x3F2 · signé 11 bits · échelle physique inconnue</small>
                    </div>
                    <div className="lka-candidate-indicator">
                      <span>Consigne colonne</span>
                      <strong>{typeof point.lka_angle_setpoint_deg === "number" ? `${point.lka_angle_setpoint_deg.toFixed(1)}°` : "—"}</strong>
                      <small>SET_ANGLE · facteur {point.lka_torque_factor_raw ?? "—"}</small>
                    </div>
                  </div>
                  <div className="lka-validation-footer">
                    <span>Franchissements enregistrés dans la session <strong>{laneDepartureEventCount}</strong></span>
                    <span>API véhicule <strong>couple R2/EVO</strong> · angle observé nul</span>
                  </div>
                </div>
                <div className="cruise-validation-card">
                  <div className="cruise-validation-heading">
                    <span>Régulateur — états directs et commandes déduites</span>
                    <strong className={point.cruise_activation_request ? "success-text" : ""}>
                      {point.cruise_activation_request ? "RVV actif" : cruiseModeLabel(point.cruise_mode_raw)}
                    </strong>
                  </div>
                  <div className="cruise-candidate-grid">
                    <div className={`cruise-candidate-indicator${point.cruise_on ? " active" : ""}`}>
                      <span>Mode sélectionné</span>
                      <strong>{cruiseModeLabel(point.cruise_mode_raw)}</strong>
                      <small>0x50E · octet 7 bits 5-6</small>
                    </div>
                    <div className={`cruise-candidate-indicator${point.cruise_activation_request ? " active" : ""}`}>
                      <span>Consigne</span>
                      <strong>{typeof point.cruise_setpoint_kph === "number" ? `${point.cruise_setpoint_kph.toFixed(0)} km/h` : "—"}</strong>
                      <small>0x50E Dat_CLIM · octet 6</small>
                    </div>
                    <div className={`cruise-candidate-indicator${point.cruise_active_candidate ? " active" : ""}`}>
                      <span>État moteur XVV</span>
                      <strong>{cruiseXvvStateLabel(point.cruise_xvv_state)}</strong>
                      <small>0x208 · code {point.cruise_xvv_state ?? "—"}</small>
                    </div>
                  </div>
                  <div className="cruise-control-pad" aria-label="Commandes détectées du régulateur">
                    <div className={`cruise-control-button${point.cruise_on ? " active" : ""}`}>
                      <span>ON</span><small>mode RVV = 1</small>
                    </div>
                    <div className={`cruise-control-button pulse${point.cruise_button_event === "set_plus" ? " active" : ""}`}>
                      <span>SET+</span><small>{point.cruise_button_event === "set_plus" ? `+${Math.abs(point.cruise_setpoint_step_kph ?? 0).toFixed(0)} km/h` : "variation +"}</small>
                    </div>
                    <div className={`cruise-control-button pulse${point.cruise_button_event === "set_minus" ? " active" : ""}`}>
                      <span>SET−</span><small>{point.cruise_button_event === "set_minus" ? `−${Math.abs(point.cruise_setpoint_step_kph ?? 0).toFixed(0)} km/h` : "variation −"}</small>
                    </div>
                    <div className={`cruise-control-button candidate pulse${point.cruise_button_event === "resume" ? " active" : ""}`}>
                      <span>RESUME</span><small>réengagement déduit</small>
                    </div>
                    <div className={`cruise-control-button pulse${point.cruise_button_event === "cancel" ? " active" : ""}`}>
                      <span>CANCEL</span><small>coupure sans frein</small>
                    </div>
                  </div>
                  <div className="cruise-validation-footer">
                    <span>Activation directe 0x50E <strong>{point.cruise_activation_request ? "oui" : "non"}</strong></span>
                    <span>RESUME <strong>candidat</strong> · aucun contact dédié visible</span>
                  </div>
                </div>
                <div className="cruise-validation-card">
                  <div className="cruise-validation-heading">
                    <span>ACC / LVV — caméra 0x452</span>
                    <strong className={point.acc_requested || point.lvv_requested ? "success-text" : ""}>
                      {point.acc_requested ? "ACC demandé" : point.lvv_requested ? "LVV demandé" : "Aucune demande caméra"}
                    </strong>
                  </div>
                  <div className="cruise-candidate-grid">
                    <div className={`cruise-candidate-indicator${point.acc_requested ? " active" : ""}`}>
                      <span>ACC</span>
                      <strong>{point.acc_requested ? "Demandé" : "Aucune"}</strong>
                      <small>RVV_ACC_ACTIVATION_REQ</small>
                    </div>
                    <div className={`cruise-candidate-indicator${point.lvv_requested ? " active" : ""}`}>
                      <span>LVV</span>
                      <strong>{point.lvv_requested ? "Demandé" : "Aucune"}</strong>
                      <small>LVV_ACTIVATION_REQ</small>
                    </div>
                    <div className="cruise-candidate-indicator">
                      <span>Consigne caméra</span>
                      <strong>{typeof point.speed_setpoint_kph === "number" && point.speed_setpoint_kph > 0 ? `${point.speed_setpoint_kph.toFixed(0)} km/h` : "—"}</strong>
                      <small>SPEED_SETPOINT</small>
                    </div>
                  </div>
                  <div className="cruise-validation-footer">
                    <span>Type régulation caméra <strong>{point.acc_mode ?? "—"}</strong></span>
                  </div>
                </div>
                <div><span>Frein conducteur</span><strong className={point.brake_active ? "danger-text" : ""}>{point.brake_active ? "Appuyé" : "Relâché"}</strong><small>État système {point.brake_system_state ?? "—"} · pression brute {point.brake_pressure_raw?.toFixed(0) ?? "—"}</small></div>
                <div><span>Effort au volant</span><strong>{point.driver_torque?.toFixed(0) ?? "—"}</strong><small>Valeur colonne non calibrée en N·m</small></div>
              </div>
            </>}
          </article>
        </section>

        <section className="panel replay-indicator-panel">
          <div className="section-heading custom-gauge-heading">
            <div>
              <span className="eyebrow">Combiné personnalisable</span>
              <h2>Mes témoins de bord</h2>
              <p>Les témoins disponibles suivent le CAN; les autres restent gris comme références, sans fausse alerte.</p>
            </div>
            <div className="indicator-actions">
              <div className="gauge-picker">
                <select value={replayIndicatorToAdd} onChange={(event) => setReplayIndicatorToAdd(event.target.value)} aria-label="Témoin à ajouter">
                  <option value="">Ajouter un témoin…</option>
                  {addableIndicatorDefinitions.map((definition) => (
                    <option key={definition.key} value={definition.key}>{definition.label}{definition.referenceOnly ? " · référence" : ""}</option>
                  ))}
                </select>
                <button className="secondary-button" disabled={!replayIndicatorToAdd} onClick={addReplayIndicator}>Ajouter</button>
              </div>
              <button className="ghost-button" onClick={() => setSelectedReplayIndicatorKeys(replayIndicatorCatalog.map((definition) => definition.key))}>Tout afficher</button>
            </div>
          </div>
          {selectedIndicatorDefinitions.length === 0 ? (
            <div className="custom-gauge-empty">Aucun témoin sélectionné. Utilise la galerie ci-dessus.</div>
          ) : (
            <div className="replay-indicator-grid">
              {selectedIndicatorDefinitions.map((definition) => {
                const state = replayIndicatorState(definition, point, replay);
                const blinkSignal = ["turn_left", "turn_right"].includes(definition.key) || (definition.key === "engine" && point.mil_blinking);
                const visualActive = state.active === true && (!blinkSignal || blinkOn);
                const cardState = !state.available ? "unavailable" : state.active === null ? "observed" : visualActive ? "active" : "inactive";
                return (
                  <article className={`replay-indicator-card ${definition.color} ${cardState}`} key={definition.key} title={definition.note}>
                    <button className="indicator-remove" onClick={() => removeReplayIndicator(definition.key)} aria-label={`Retirer ${definition.label}`}>×</button>
                    <div className="warning-lamp"><ReplayWarningIcon kind={definition.icon} /></div>
                    <h3>{definition.label}</h3>
                    <strong>{!state.available ? "Référence" : state.active === null ? "État brut" : state.active ? "Allumé" : "Éteint"}</strong>
                    <small>{state.detail}</small>
                    {state.inferred && <em>seuil estimé</em>}
                  </article>
                );
              })}
            </div>
          )}
          <p className="indicator-reference-note">
            Référentiel visuel basé sur les catégories du <a href={replayIsFiat500 ? FIAT_500_HANDBOOK_URL : PEUGEOT_308_HANDBOOK_URL} target="_blank" rel="noreferrer">manuel officiel {replayIsFiat500 ? "Fiat 500" : "Peugeot 308"}</a>. Un pictogramme gris signifie uniquement que son signal n'est pas présent dans la capture.
          </p>
        </section>

        <section className="panel custom-gauge-panel">
          <div className="section-heading custom-gauge-heading">
            <div>
              <span className="eyebrow">Instrumentation personnalisable</span>
              <h2>Mes jauges de replay</h2>
              <p>Ajoute ou retire les capteurs réellement présents dans cet enregistrement.</p>
            </div>
            <div className="gauge-picker">
              <select value={replayGaugeToAdd} onChange={(event) => setReplayGaugeToAdd(event.target.value)} aria-label="Capteur à ajouter">
                <option value="">Ajouter un capteur…</option>
                {addableGaugeDefinitions.map((definition) => <option key={definition.key} value={definition.key}>{definition.label}{replay.field_quality[String(definition.key)]?.includes("validated") ? "" : " · à confirmer"}</option>)}
                <option value="__fuel_consumption_unavailable" disabled>Consommation — diagnostic OBD requis</option>
              </select>
              <button className="secondary-button" disabled={!replayGaugeToAdd} onClick={addReplayGauge}>Ajouter</button>
              <button className="ghost-button" disabled={!availableGaugeDefinitions.length} onClick={() => setSelectedReplayGaugeKeys(availableGaugeDefinitions.map((definition) => String(definition.key)))}>Tout afficher</button>
            </div>
          </div>
          {selectedGaugeDefinitions.length === 0 ? (
            <div className="custom-gauge-empty">Aucune jauge sélectionnée. Choisis un capteur dans la liste ci-dessus.</div>
          ) : (
            <div className="custom-gauge-grid">
              {selectedGaugeDefinitions.map((definition) => {
                const rawValue = point[definition.key];
                const numericValue = typeof rawValue === "number" ? rawValue : null;
                const statusValue = typeof rawValue === "boolean" ? rawValue : null;
                const ratio = definition.status
                  ? statusValue ? 1 : 0
                  : numericValue === null ? 0 : Math.max(0, Math.min(1, (numericValue - definition.minimum) / (definition.maximum - definition.minimum)));
                const displayValue = definition.status
                  ? statusValue === null ? "—" : statusValue ? "Actif" : "Inactif"
                  : numericValue === null ? "—" : ["current_gear", "target_gear"].includes(String(definition.key)) && numericValue === 9 ? "R" : numericValue.toFixed(definition.precision ?? 0);
                const quality = replay.field_quality[definition.key] ?? "opendbc_candidate";
                const validation = validationByKey.get(String(definition.key));
                return (
                  <article className="custom-gauge-card" key={definition.key}>
                    <button className="gauge-remove" onClick={() => removeReplayGauge(definition.key)} aria-label={`Retirer ${definition.label}`}>×</button>
                    <div
                      className="custom-gauge-ring"
                      style={{ background: `conic-gradient(${definition.color} 0deg ${ratio * 300}deg, #263039 ${ratio * 300}deg 300deg, transparent 300deg)` }}
                    >
                      <div><strong>{displayValue}</strong><small>{definition.unit}</small></div>
                    </div>
                    <h3>{definition.label}</h3>
                    <p>{definition.note}</p>
                    <footer>
                      <span className={`validation-badge ${validation?.status ?? "candidate"}`}>{validation?.status === "validated" ? "Validé" : validation?.status === "plausible" ? "Plausible" : validation?.status === "suspicious" ? "Suspect" : quality.includes("state_only") ? "Contacteur logique" : "À confirmer"}</span>
                      <code>{definition.key}</code>
                    </footer>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel replay-graph-panel">
          <div className="section-heading custom-gauge-heading">
            <div>
              <span className="eyebrow">Analyse temporelle</span>
              <h2>Mes graphes synchronisés</h2>
              <p>Chaque courbe utilise l'échelle observée du capteur et le curseur suit exactement le replay.</p>
            </div>
            <div className="gauge-picker">
              <select value={replayGraphToAdd} onChange={(event) => setReplayGraphToAdd(event.target.value)} aria-label="Graphe à ajouter">
                <option value="">Ajouter un graphe…</option>
                {addableGraphDefinitions.map((definition) => <option key={definition.key} value={definition.key}>{definition.label}{replay.field_quality[String(definition.key)]?.includes("validated") ? "" : " · à confirmer"}</option>)}
              </select>
              <button className="secondary-button" disabled={!replayGraphToAdd} onClick={addReplayGraph}>Ajouter</button>
              <button className="ghost-button" disabled={!availableGraphDefinitions.length} onClick={() => setSelectedReplayGraphKeys(availableGraphDefinitions.map((definition) => String(definition.key)))}>Tout afficher</button>
            </div>
          </div>
          {selectedGraphDefinitions.length === 0 ? (
            <div className="custom-gauge-empty">Aucun graphe sélectionné. Choisis un signal numérique dans la liste.</div>
          ) : (
            <div className="replay-graph-grid">
              {selectedGraphDefinitions.map((definition) => {
                const geometry = currentReplayGraphGeometries.get(String(definition.key));
                const rawValue = point[definition.key];
                const numericValue = typeof rawValue === "number" ? rawValue : null;
                const span = Math.max(0.001, (geometry?.maximum ?? definition.maximum) - (geometry?.minimum ?? definition.minimum));
                const markerY = numericValue === null ? null : 172 - (numericValue - (geometry?.minimum ?? definition.minimum)) / span * 164;
                return (
                  <article className="replay-graph-card" key={definition.key}>
                    <header>
                      <div><span>{definition.label}</span><strong>{numericValue?.toFixed(definition.precision ?? 0) ?? "—"} <small>{definition.unit}</small></strong></div>
                      <button className="gauge-remove" onClick={() => removeReplayGraph(String(definition.key))} aria-label={`Retirer le graphe ${definition.label}`}>×</button>
                    </header>
                    <div className="replay-chart-wrap">
                      <svg
                        viewBox="0 0 900 180"
                        preserveAspectRatio="none"
                        role="img"
                        aria-label={`Courbe ${definition.label}`}
                        onClick={(event) => {
                          const bounds = event.currentTarget.getBoundingClientRect();
                          seekReplay((event.clientX - bounds.left) / bounds.width * replay.duration_ms);
                        }}
                      >
                        <path className="chart-grid-line" d="M0 45H900M0 90H900M0 135H900" />
                        <path className="chart-series-shadow" d={geometry?.path ?? ""} style={{ stroke: definition.color }} />
                        <path className="chart-series" d={geometry?.path ?? ""} style={{ stroke: definition.color }} />
                        <line className="chart-cursor" x1={progress * 900} x2={progress * 900} y1="0" y2="180" />
                        {markerY !== null && <circle className="chart-marker" cx={progress * 900} cy={Math.max(8, Math.min(172, markerY))} r="6" style={{ fill: definition.color }} />}
                      </svg>
                      <span className="chart-maximum">{(geometry?.maximum ?? definition.maximum).toFixed(definition.precision ?? 0)} {definition.unit}</span>
                      <span className="chart-minimum">{(geometry?.minimum ?? definition.minimum).toFixed(definition.precision ?? 0)} {definition.unit}</span>
                    </div>
                    <footer><span>00:00</span><span>{formatReplayTime(replayTimeMs)}</span><span>{formatReplayTime(replay.duration_ms)}</span></footer>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel replay-controls">
          <div className="transport-controls">
            <button onClick={() => seekReplay(replayTimeMs - 10_000)} aria-label="Reculer de dix secondes">−10</button>
            <button className="play-button" onClick={() => setReplayPlaying((playing) => !playing)}>{replayPlaying ? "Ⅱ" : "▶"}</button>
            <button onClick={() => seekReplay(replayTimeMs + 10_000)} aria-label="Avancer de dix secondes">+10</button>
            <strong>{formatReplayTime(replayTimeMs)}</strong><span>/ {formatReplayTime(replay.duration_ms)}</span>
          </div>
          <div className="rate-controls" aria-label="Vitesse de lecture">
            {[0.5, 1, 2, 5, 10].map((rate) => <button key={rate} className={replayRate === rate ? "active" : ""} onClick={() => setReplayRate(rate)}>×{rate}</button>)}
          </div>
          <div className="timeline-wrap">
            <input type="range" min="0" max={replay.duration_ms} step={replay.sample_period_ms} value={Math.round(replayTimeMs)} onChange={(event) => seekReplay(Number(event.target.value))} />
            <div className="event-track">
              {replay.events.map((event, index) => (
                <button
                  key={`${event.t_ms}-${event.kind}-${index}`}
                  className={`event-pin ${event.kind}`}
                  style={{ left: `${event.t_ms / replay.duration_ms * 100}%` }}
                  title={`${formatReplayTime(event.t_ms)} · ${event.label}`}
                  onClick={() => seekReplay(event.t_ms)}
                />
              ))}
            </div>
          </div>
          <div className="event-list">
            {replay.events.map((event, index) => (
              <button key={`${event.t_ms}-${index}`} className={event.kind} onClick={() => seekReplay(event.t_ms)}>
                <time>{formatReplayTime(event.t_ms)}</time><span>{event.label}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="replay-method-note">
          <span className="source-badge measured">Validé véhicule</span><p>Vitesse, roues, volant, lacet, pédales, régime, couple, rapports, freinage, tension et contacteur d’huile.</p>
          <span className="source-badge candidate">Plausible</span><p>Températures, états non provoqués et niveau carburant filtré : cohérents, mais sans mesure étalon indépendante.</p>
          <span className="source-badge suspicious">Indisponible</span><p>La consommation passive est invalide ou nulle sur cette capture; elle nécessite une lecture OBD moteur.</p>
          <span className={`source-badge ${gpsMeasured ? "measured" : "estimated"}`}>{gpsMeasured ? "GPS navigateur" : "Estimé"}</span><p>{gpsMeasured ? "Position, précision, cap et trace synchronisés avec le CAN." : gpsAnchored ? "Position initiale GPS; trajet ensuite estimé." : "Position, cap et distance sans GPS."}</p>
        </section>
      </div>
    );
  }
