import React, { useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";
import { API_BASE, api } from "./api";
import { AppLayout } from "./components/AppLayout";
import { MaintenanceModeDialog } from "./components/MaintenanceModeDialog";
import {
  formatDate,
  formatDuration,
  formatIsoDate,
  formatReplayTime,
  hexadecimal,
} from "./format";
import { AnalysisScreen } from "./screens/AnalysisScreen";
import { DatabaseScreen } from "./screens/DatabaseScreen";
import { DashboardScreen } from "./screens/DashboardScreen";
import { GarageScreen } from "./screens/GarageScreen";
import { DiscoveryScreen } from "./screens/DiscoveryScreen";
import { DtcsScreen } from "./screens/DtcsScreen";
import { EcuLiveScreen } from "./screens/EcuLiveScreen";
import { EcusScreen } from "./screens/EcusScreen";
import { InjectionScreen } from "./screens/InjectionScreen";
import { MaintenanceScreen } from "./screens/MaintenanceScreen";
import { PsaAdvancedScreen } from "./screens/PsaAdvancedScreen";
import { ReplayScreen } from "./screens/ReplayScreen";
import { SecurityScreen } from "./screens/SecurityScreen";
import { SensorInventoryScreen } from "./screens/SensorInventoryScreen";
import { SensorsScreen } from "./screens/SensorsScreen";
import { StudioScreen } from "./screens/StudioScreen";
import { VehicleIdentityScreen } from "./screens/VehicleIdentityScreen";
import {
  ECU_LIVE_CATALOG,
  ECU_LIVE_VIEW_KEYS,
  LAB_MODE,
  initialView,
  viewTitles,
} from "./navigation";
import type { EcuLiveView, NavModule, View } from "./navigation";
import {
  FIAT_500_HANDBOOK_URL,
  PEUGEOT_308_HANDBOOK_URL,
  STUDIO_COLUMNS,
  STUDIO_GRAPH_WINDOWS,
  STUDIO_ROW_HEIGHT,
  cruiseXvvStateLabel,
  defaultReplayGaugeKeys,
  defaultReplayGraphKeys,
  defaultReplayIndicatorKeys,
  defaultStudioWidgets,
  laneAssistStatusLabel,
  liveGraphGeometry,
  passiveSnapshotToReplaySample,
  replayGaugeCatalog,
  replayGraphGeometry,
  replayIndicatorCatalog,
  replayIndicatorState,
  replayPointIndex,
  routeGeometry,
  vehicleVisualForProfile,
} from "./replay";
import { sensorCandidatesForProfile } from "./sensorInventory";
import type { PowertrainProfile } from "./sensorInventory";
import type {
  BehavioralAnalysis,
  ByteProfile,
  CanIdProfile,
  CaptureStatus,
  ClearDtcResult,
  DiagnosticReportSummary,
  DiagnosticSensorCatalogEntry,
  DiagnosticSensorSnapshot,
  DiagnosticSensorValue,
  DiagnosticVehicle,
  DidSweepResult,
  DidValue,
  DiscoverySession,
  DtcChange,
  DtcSnapshotResult,
  DtcValue,
  Ecu,
  EcuResetResult,
  LiveSensorDefinition,
  MaintenanceCatalog,
  MaintenanceInvoiceAnalysis,
  MaintenanceMileageEstimate,
  MaintenanceRecord,
  MaintenanceRecordInput,
  ServiceProvider,
  ServiceProviderInput,
  ObservedDtc,
  OilLogEntry,
  OilLogEntryInput,
  OpendbcCatalog,
  OperatingModeState,
  PassiveCanSignal,
  PassiveSensorSnapshot,
  PsaActionResult,
  PsaAdvancedAction,
  PsaAdvancedCatalog,
  PsaAdvancedEcu,
  PsaSeedKeyResult,
  PsaUnlockResult,
  RegressionResult,
  ReplayData,
  ReplayGaugeDefinition,
  ReplayGraphGeometry,
  ReplayIndicatorDefinition,
  ReplayIndicatorState,
  ReplaySample,
  ReplayValidation,
  Report,
  RouteGeometry,
  SensorInventoryStatus,
  SensorInventoryRow,
  SignalCandidate,
  Status,
  StudioGraphWindowSeconds,
  StudioSensorStyle,
  StudioWidget,
  StudioWidgetKind,
  TraceImportResult,
  TransportCatalog,
  TransportConnection,
  VehicleIdentityResult,
  VehicleProfileSummary,
  VehicleTimelineEntry,
  VehicleVisualProfile,
} from "./types";

export type {
  BehavioralAnalysis,
  CaptureStatus,
  DiagnosticSensorCatalogEntry,
  DiagnosticVehicle,
  DiscoverySession,
  Ecu,
  LiveSensorDefinition,
  MaintenanceCatalog,
  MaintenanceService,
  OperatingModeState,
  Report,
  SignalCandidate,
  Status,
  VehicleProfileSummary,
  VehicleTimelineEntry,
} from "./types";
export type { View } from "./navigation";

















































































const markerPresets = [
  "frein_appuye",
  "frein_relache",
  "phares_allumes",
  "phares_eteints",
  "clignotant_gauche",
  "clignotant_droit",
  "marche_arriere",
  "porte_ouverte",
  "volant_gauche",
  "volant_droite",
  "volant_centre",
  "accelerateur_appuye",
];
















export default function App() {
  const [view, setView] = useState<View>(initialView);
  const [openNavModule, setOpenNavModule] = useState<NavModule | null>(() => {
    const initial = initialView();
    if ((["identity", "injection", "studio", "discovery", "inventory", "replay", "database", "security", "psa", ...ECU_LIVE_VIEW_KEYS] as View[]).includes(initial)) return "advanced";
    return null;
  });
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState("");
  const [operatingMode, setOperatingMode] = useState<OperatingModeState | null>(null);
  const [modeDialogOpen, setModeDialogOpen] = useState(false);
  const [modeSwitchBusy, setModeSwitchBusy] = useState(false);
  const [modeConfirmation, setModeConfirmation] = useState("");
  const [modeChecks, setModeChecks] = useState({
    vehicle_stationary: false,
    ignition_on_engine_off: false,
    stable_battery_voltage: false,
    workshop_or_private_site: false,
  });
  const [transportCatalog, setTransportCatalog] = useState<TransportCatalog | null>(null);
  const [selectedTransportId, setSelectedTransportId] = useState("");
  const [transportConnectBusy, setTransportConnectBusy] = useState(false);
  const [transportMessage, setTransportMessage] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [selectedEcuKey, setSelectedEcuKey] = useState("");
  const [diagnosticRegression, setDiagnosticRegression] = useState<RegressionResult | null>(null);
  const [diagnosticRegressionBusy, setDiagnosticRegressionBusy] = useState(false);
  const [traceImportResult, setTraceImportResult] = useState<TraceImportResult | null>(null);
  const [traceImportBusy, setTraceImportBusy] = useState(false);
  const [dtcClearEcuKey, setDtcClearEcuKey] = useState("");
  const [dtcClearConfirmation, setDtcClearConfirmation] = useState("");
  const [dtcClearChecks, setDtcClearChecks] = useState({
    vehicle_stationary: false,
    ignition_on_engine_off: false,
    stable_battery_voltage: false,
    report_saved: false,
  });
  const [dtcClearBusy, setDtcClearBusy] = useState(false);
  const [dtcClearResult, setDtcClearResult] = useState<ClearDtcResult | null>(null);
  const [dtcSnapshotBusy, setDtcSnapshotBusy] = useState("");
  const [dtcSnapshotResults, setDtcSnapshotResults] = useState<Record<string, DtcSnapshotResult>>({});
  const [didSweepStart, setDidSweepStart] = useState("0000");
  const [didSweepEnd, setDidSweepEnd] = useState("01FF");
  const [didSweepBusy, setDidSweepBusy] = useState(false);
  const [didSweepResult, setDidSweepResult] = useState<DidSweepResult | null>(null);
  const [observedDtcs, setObservedDtcs] = useState<ObservedDtc[]>([]);
  const [oilLog, setOilLog] = useState<OilLogEntry[]>([]);
  const [oilLogBusy, setOilLogBusy] = useState(false);
  const [maintenanceRecords, setMaintenanceRecords] = useState<MaintenanceRecord[]>([]);
  const [maintenanceProviders, setMaintenanceProviders] = useState<ServiceProvider[]>([]);
  const [maintenanceRecordBusy, setMaintenanceRecordBusy] = useState(false);
  const [maintenanceCreateIntent, setMaintenanceCreateIntent] = useState<{
    key: number;
    eventType: MaintenanceRecordInput["event_type"];
  } | null>(null);
  useEffect(() => {
    if (view !== "maintenance") setMaintenanceCreateIntent(null);
  }, [view]);
  const [diagnosticVehicles, setDiagnosticVehicles] = useState<DiagnosticVehicle[]>([]);
  const [selectedDiagnosticVin, setSelectedDiagnosticVin] = useState(
    () => window.localStorage.getItem("opendiag.diagnostic-vin") ?? "",
  );
  const [vehicleSelectionBusy, setVehicleSelectionBusy] = useState(false);
  const [sessionAssignmentBusy, setSessionAssignmentBusy] = useState("");
  const [garageEventFilter, setGarageEventFilter] = useState<"all" | "diagnostic" | "capture" | "maintenance" | "identity">("all");
  const [diagnosticReportHistory, setDiagnosticReportHistory] = useState<DiagnosticReportSummary[]>([]);
  const [dtcFilter, setDtcFilter] = useState<DtcValue["state"] | "all">("active");
  const [diagnosticSensorCatalog, setDiagnosticSensorCatalog] = useState<DiagnosticSensorCatalogEntry[]>([]);
  const [injectionSnapshot, setInjectionSnapshot] = useState<DiagnosticSensorSnapshot | null>(null);
  const [injectionBusy, setInjectionBusy] = useState(false);
  const [vehicleProfiles, setVehicleProfiles] = useState<VehicleProfileSummary[]>([]);
  const [identityProfileKey, setIdentityProfileKey] = useState(() =>
    new URLSearchParams(window.location.search).get("profile")
      ?? window.localStorage.getItem("opendiag.identity-profile")
      ?? "peugeot_308_t9_2018"
  );
  const [vehicleIdentity, setVehicleIdentity] = useState<VehicleIdentityResult | null>(null);
  const [identityBusy, setIdentityBusy] = useState(false);
  const [manualVehicleBusy, setManualVehicleBusy] = useState(false);
  const [obdDtcResult, setObdDtcResult] = useState<Ecu | null>(null);
  const [obdDtcBusy, setObdDtcBusy] = useState(false);
  const [udsProbeEcuKey, setUdsProbeEcuKey] = useState("body_computer");
  const [udsProbeResult, setUdsProbeResult] = useState<DidValue | null>(null);
  const [udsProbeBusy, setUdsProbeBusy] = useState(false);
  const [psaCatalog, setPsaCatalog] = useState<PsaAdvancedCatalog | null>(null);
  const [ecuWatchValues, setEcuWatchValues] = useState<Record<string, DidValue>>({});
  const [ecuLiveReport, setEcuLiveReport] = useState<Ecu | null>(null);
  const [ecuLiveReportBusy, setEcuLiveReportBusy] = useState(false);
  const [maintenanceCatalog, setMaintenanceCatalog] = useState<MaintenanceCatalog | null>(null);
  const [maintenanceCategory, setMaintenanceCategory] = useState("Toutes");
  const [psaEcuKey, setPsaEcuKey] = useState("bsi");
  const [psaDid, setPsaDid] = useState("F190");
  const [psaDidResult, setPsaDidResult] = useState<DidValue | null>(null);
  const [psaSeed, setPsaSeed] = useState("11111111");
  const [psaApplicationKey, setPsaApplicationKey] = useState("D91C");
  const [psaSeedResult, setPsaSeedResult] = useState<PsaSeedKeyResult | null>(null);
  const [psaSelectedActionKey, setPsaSelectedActionKey] = useState("");
  const [psaConfirmation, setPsaConfirmation] = useState("");
  const [psaDurationMs, setPsaDurationMs] = useState(1500);
  const [psaUnlockEcuKey, setPsaUnlockEcuKey] = useState("telematics");
  const [psaUnlockApplicationKey, setPsaUnlockApplicationKey] = useState("D91C");
  const [psaUnlockConfirmation, setPsaUnlockConfirmation] = useState("");
  const [psaLabChecks, setPsaLabChecks] = useState({
    vehicle_stationary: false,
    ignition_on_engine_off: false,
    stable_battery_voltage: false,
    workshop_or_private_site: false,
  });
  const [psaBusy, setPsaBusy] = useState("");
  const [psaFeedback, setPsaFeedback] = useState("");
  const [ecuResetConfirmation, setEcuResetConfirmation] = useState("");
  const [ecuResetBusy, setEcuResetBusy] = useState(false);
  const [ecuResetResult, setEcuResetResult] = useState<EcuResetResult | null>(null);
  const [psaSection, setPsaSection] = useState<"read" | "actions" | "expert">(() => {
    const requested = new URLSearchParams(window.location.search).get("mode");
    return requested === "actions" || requested === "expert" ? requested : "read";
  });
  const [powertrainProfile, setPowertrainProfile] = useState<PowertrainProfile>(() => {
    const saved = window.localStorage.getItem("opendiag.powertrain-profile");
    return saved === "gasoline" || saved === "diesel" ? saved : "unknown";
  });
  const [inventorySearch, setInventorySearch] = useState("");
  const [inventorySystem, setInventorySystem] = useState("Tous");
  const [inventoryStatus, setInventoryStatus] = useState<"all" | "available" | "missing" | "excluded">("all");
  const [inventoryPriorityOnly, setInventoryPriorityOnly] = useState(false);
  const [validationFocusId, setValidationFocusId] = useState("");
  const [passiveSensors, setPassiveSensors] = useState<PassiveSensorSnapshot | null>(null);
  const sensorCursorUs = useRef(0);
  const sensorRefreshBusy = useRef(false);
  const [sensorCategory, setSensorCategory] = useState("Essentiels");
  const [sensorSearch, setSensorSearch] = useState("");
  const [sensorEditor, setSensorEditor] = useState<{
    key: string;
    label: string;
    description: string;
    unit: string;
    factor: string;
    offset: string;
    customized: boolean;
  } | null>(null);
  const [sensorEditorBusy, setSensorEditorBusy] = useState(false);
  const [liveSensorDefinitions, setLiveSensorDefinitions] = useState<LiveSensorDefinition[]>([]);
  const [liveSensorEditor, setLiveSensorEditor] = useState<{
    key?: string;
    sourceKey: string;
    label: string;
    description: string;
    category: string;
    unit: string;
    factor: string;
    offset: string;
  } | null>(null);
  const [liveSensorEditorBusy, setLiveSensorEditorBusy] = useState(false);
  const [detectionEndsAt, setDetectionEndsAt] = useState<number | null>(null);
  const [detectionRemaining, setDetectionRemaining] = useState(0);
  const [detectionBusy, setDetectionBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [extendedProbeEnabled, setExtendedProbeEnabled] = useState(false);
  const [error, setError] = useState("");

  const [capture, setCapture] = useState<CaptureStatus | null>(null);
  const [captureName, setCaptureName] = useState("Nouvelle session véhicule");
  const [captureNote, setCaptureNote] = useState("");
  const [captureGpsEnabled, setCaptureGpsEnabled] = useState(
    () => window.localStorage.getItem("opendiag.capture-gps") !== "false",
  );
  const [gpsTracking, setGpsTracking] = useState<{
    state: "idle" | "requesting" | "active" | "unavailable" | "denied" | "error";
    accuracyM?: number;
    message?: string;
  }>({ state: "idle" });
  const gpsWatchRef = useRef<number | null>(null);
  const gpsLastSentAtRef = useRef(0);
  const [markerName, setMarkerName] = useState("frein_appuye");
  const [markerNote, setMarkerNote] = useState("");
  const [sessions, setSessions] = useState<DiscoverySession[]>([]);
  const [analysis, setAnalysis] = useState<BehavioralAnalysis | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState("");
  const [opendbcCatalog, setOpendbcCatalog] = useState<OpendbcCatalog | null>(null);
  const [replay, setReplay] = useState<ReplayData | null>(null);
  const [replayValidation, setReplayValidation] = useState<ReplayValidation | null>(null);
  const [signalValidationBusy, setSignalValidationBusy] = useState("");
  const [replaySessionId, setReplaySessionId] = useState("");
  const [replayBusy, setReplayBusy] = useState(false);
  const [replayTimeMs, setReplayTimeMs] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replayRate, setReplayRate] = useState(1);
  const [replayGaugeToAdd, setReplayGaugeToAdd] = useState("");
  const [selectedReplayGaugeKeys, setSelectedReplayGaugeKeys] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.replay-gauges") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultReplayGaugeKeys;
    } catch {
      return defaultReplayGaugeKeys;
    }
  });
  const [replayGraphToAdd, setReplayGraphToAdd] = useState("");
  const [selectedReplayGraphKeys, setSelectedReplayGraphKeys] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.replay-graphs") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultReplayGraphKeys;
    } catch {
      return defaultReplayGraphKeys;
    }
  });
  const [replayIndicatorToAdd, setReplayIndicatorToAdd] = useState("");
  const [selectedReplayIndicatorKeys, setSelectedReplayIndicatorKeys] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.replay-indicators") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultReplayIndicatorKeys;
    } catch {
      return defaultReplayIndicatorKeys;
    }
  });
  const [studioWidgets, setStudioWidgets] = useState<StudioWidget[]>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("opendiag.studio-layout") ?? "null");
      return Array.isArray(saved) && saved.length ? saved : defaultStudioWidgets;
    } catch {
      return defaultStudioWidgets;
    }
  });
  const [studioWidgetToAdd, setStudioWidgetToAdd] = useState("gauge:oil_temperature_c");
  const [studioEditing, setStudioEditing] = useState(true);
  const studioBoardRef = useRef<HTMLDivElement>(null);
  const studioInteractionCleanup = useRef<(() => void) | null>(null);
  const [studioLiveHistory, setStudioLiveHistory] = useState<ReplaySample[]>([]);
  const studioLiveSessionRef = useRef("");
  const studioLiveStartUs = useRef(0);
  const studioFuelFilterRef = useRef<{ sessionId: string; generatedAtUs: number; value: number | null }>({
    sessionId: "",
    generatedAtUs: 0,
    value: null,
  });

  useEffect(() => {
    api<Status>("/api/system/status")
      .then((payload) => {
        setStatus(payload);
        setStatusError("");
      })
      .catch((err) => setStatusError(err instanceof Error ? err.message : String(err)));
    void refreshOperatingMode();
    refreshCapture();
    refreshTransportCatalog();
    refreshPassiveSensors();
    refreshSessions();
    void refreshDiagnosticHistory();
    api<DiagnosticSensorCatalogEntry[]>("/api/sensors/catalog")
      .then(setDiagnosticSensorCatalog)
      .catch(() => setDiagnosticSensorCatalog([]));
    api<VehicleProfileSummary[]>("/api/database/vehicles")
      .then((profiles) => {
        setVehicleProfiles(profiles);
        setIdentityProfileKey((current) => profiles.some((profile) => profile.key === current)
          ? current
          : profiles[0]?.key ?? current);
      })
      .catch(() => setVehicleProfiles([]));
    api<PsaAdvancedCatalog>("/api/diagnostic/psa/catalog")
      .then(setPsaCatalog)
      .catch(() => setPsaCatalog(null));
    api<OpendbcCatalog>("/api/learn/opendbc/catalog")
      .then(setOpendbcCatalog)
      .catch(() => setOpendbcCatalog(null));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(refreshCapture, capture?.active ? 800 : 2500);
    return () => window.clearInterval(timer);
  }, [capture?.active]);

  useEffect(() => {
    if (view === "security") void refreshOperatingMode();
  }, [view, capture?.active]);

  useEffect(() => {
    if (capture?.active && captureGpsEnabled) startGpsTracking(capture.session_id);
    else stopGpsTracking();
    return stopGpsTracking;
  }, [capture?.active, capture?.session_id, captureGpsEnabled]);

  useEffect(() => {
    if (
      !(["sensors", "inventory", "ecus", "psa", "studio", ...ECU_LIVE_VIEW_KEYS] as View[]).includes(view)
      || !capture?.active
    ) return;
    const timer = window.setInterval(refreshPassiveSensors, 200);
    return () => window.clearInterval(timer);
  }, [view, capture?.active]);

  useEffect(() => {
    if (view === "studio") void refreshPassiveSensors();
  }, [view]);

  useEffect(() => {
    if (!detectionEndsAt) return;
    const update = () => {
      const remaining = Math.max(0, Math.ceil((detectionEndsAt - Date.now()) / 1000));
      setDetectionRemaining(remaining);
      if (remaining === 0) setDetectionEndsAt(null);
    };
    update();
    const timer = window.setInterval(update, 250);
    return () => window.clearInterval(timer);
  }, [detectionEndsAt]);

  useEffect(() => {
    if (view !== "replay" || replaySessionId || replayBusy || sessions.length === 0) return;
    const preferred = sessions.find((session) => session.vin === selectedDiagnosticVin)
      ?? sessions.find((session) => !session.vin)
      ?? sessions[0];
    void loadReplay(preferred.session_id);
  }, [view, sessions, replaySessionId, replayBusy, selectedDiagnosticVin]);

  useEffect(() => {
    if (!replayPlaying || !replay) return;
    let frame = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      const elapsed = now - previous;
      previous = now;
      setReplayTimeMs((current) => {
        const next = current + elapsed * replayRate;
        if (next >= replay.duration_ms) {
          setReplayPlaying(false);
          return replay.duration_ms;
        }
        return next;
      });
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [replayPlaying, replay, replayRate]);

  useEffect(() => {
    if (view !== "replay") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      event.preventDefault();
      setReplayPlaying((playing) => !playing);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [view]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.replay-gauges", JSON.stringify(selectedReplayGaugeKeys));
  }, [selectedReplayGaugeKeys]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.replay-graphs", JSON.stringify(selectedReplayGraphKeys));
  }, [selectedReplayGraphKeys]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.replay-indicators", JSON.stringify(selectedReplayIndicatorKeys));
  }, [selectedReplayIndicatorKeys]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.studio-layout", JSON.stringify(studioWidgets));
  }, [studioWidgets]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.powertrain-profile", powertrainProfile);
  }, [powertrainProfile]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.capture-gps", String(captureGpsEnabled));
  }, [captureGpsEnabled]);

  useEffect(() => {
    window.localStorage.setItem("opendiag.identity-profile", identityProfileKey);
  }, [identityProfileKey]);

  useEffect(() => {
    if (selectedDiagnosticVin) window.localStorage.setItem("opendiag.diagnostic-vin", selectedDiagnosticVin);
    else window.localStorage.removeItem("opendiag.diagnostic-vin");
    void refreshLiveSensorDefinitions();
  }, [selectedDiagnosticVin]);

  useEffect(() => () => studioInteractionCleanup.current?.(), []);

  const detectedEcus = report?.ecus.filter((ecu) => ecu.detected) ?? [];
  const selectedEcu = detectedEcus.find((ecu) => ecu.key === selectedEcuKey)
    ?? detectedEcus[0]
    ?? report?.ecus[0]
    ?? null;
  useEffect(() => {
    if (!report?.ecus.length) {
      if (selectedEcuKey) setSelectedEcuKey("");
      return;
    }
    if (!report.ecus.some((ecu) => ecu.key === selectedEcuKey && ecu.detected)) {
      setSelectedEcuKey(report.ecus.find((ecu) => ecu.detected)?.key ?? report.ecus[0].key);
    }
  }, [report, selectedEcuKey]);
  const dtcs = useMemo(
    () => report?.ecus.flatMap((ecu) => ecu.dtcs.map((dtc) => ({ ecu, dtc }))) ?? [],
    [report],
  );
  const visibleDtcs = useMemo(
    () => dtcFilter === "all" ? dtcs : dtcs.filter(({ dtc }) => dtc.state === dtcFilter),
    [dtcs, dtcFilter],
  );
  const dtcCount = report?.dtc_summary.active ?? 0;
  const selectedDiagnosticVehicle = diagnosticVehicles.find((vehicle) => vehicle.vin === selectedDiagnosticVin) ?? null;
  const selectedIdentityProfile = vehicleProfiles.find((profile) => profile.key === identityProfileKey) ?? null;
  const vehicleManufacturers = useMemo(
    () => Array.from(new Set(vehicleProfiles.map((profile) => profile.manufacturer))).sort((left, right) => left.localeCompare(right, "fr")),
    [vehicleProfiles],
  );
  const profilesForSelectedManufacturer = useMemo(
    () => vehicleProfiles.filter((profile) => profile.manufacturer === selectedIdentityProfile?.manufacturer),
    [selectedIdentityProfile?.manufacturer, vehicleProfiles],
  );
  const activeCommunicationProfileKey = (
    capture?.active && capture.vehicle_profile
      ? capture.vehicle_profile
      : selectedDiagnosticVehicle?.vehicle_profile ?? identityProfileKey
  );
  const activeCommunicationProfile = vehicleProfiles.find((profile) => profile.key === activeCommunicationProfileKey) ?? selectedIdentityProfile;
  const activeIsFiat500 = activeCommunicationProfileKey === "fiat_500_generic";
  const activeVehicleVisual = vehicleVisualForProfile(activeCommunicationProfileKey);
  const effectivePowertrainProfile: PowertrainProfile = activeIsFiat500 ? "gasoline" : powertrainProfile;
  useEffect(() => {
    if (!activeCommunicationProfileKey) return;
    setMaintenanceCatalog(null);
    api<MaintenanceCatalog>(`/api/maintenance/catalog?vehicle_profile=${encodeURIComponent(activeCommunicationProfileKey)}`)
      .then(setMaintenanceCatalog)
      .catch(() => setMaintenanceCatalog(null));
  }, [activeCommunicationProfileKey]);
  const maintenanceCategories = useMemo(
    () => ["Toutes", ...Array.from(new Set(maintenanceCatalog?.services.map((service) => service.category) ?? []))],
    [maintenanceCatalog],
  );
  const visibleMaintenanceServices = useMemo(
    () => (maintenanceCatalog?.services ?? []).filter((service) => maintenanceCategory === "Toutes" || service.category === maintenanceCategory),
    [maintenanceCatalog, maintenanceCategory],
  );
  const vehicleLinkedSessions = useMemo(
    () => sessions.filter((session) => session.vin === selectedDiagnosticVin),
    [sessions, selectedDiagnosticVin],
  );
  const unassignedSessions = useMemo(
    () => sessions.filter((session) => !session.vin),
    [sessions],
  );
  const vehicleTimeline = useMemo<VehicleTimelineEntry[]>(() => {
    if (!selectedDiagnosticVin) return [];
    const entries: VehicleTimelineEntry[] = diagnosticReportHistory.map((item) => ({
      id: item.scan_id,
      kind: "diagnostic",
      timestampMs: new Date(item.scanned_at).getTime(),
      title: "Diagnostic complet ECU + DTC",
      description: `${item.detected_ecus} calculateurs détectés · ${item.dtc_summary.active} actif(s) · ${item.dtc_summary.historical} historique(s)`,
      badge: item.dtc_summary.active ? `${item.dtc_summary.active} défaut(s) actif(s)` : "Aucun défaut actif",
      scanId: item.scan_id,
      severity: item.dtc_summary.active ? "warning" : "good",
    }));
    for (const session of vehicleLinkedSessions) {
      entries.push({
        id: session.session_id,
        kind: "capture",
        timestampMs: (session.started_at_us ?? 0) / 1000,
        title: session.name,
        description: `${formatDuration(session.duration_ms)} · ${session.frame_count.toLocaleString("fr-FR")} trames${session.gps_point_count ? ` · ${session.gps_point_count} positions GPS` : ""}`,
        badge: session.gps_point_count ? "Trajet géolocalisé" : session.marker_count ? `${session.marker_count} marqueur(s)` : "Capture CAN",
        sessionId: session.session_id,
        severity: session.error ? "warning" : "neutral",
      });
    }
    if (selectedDiagnosticVehicle?.first_seen) {
      entries.push({
        id: `identity-${selectedDiagnosticVehicle.vin}`,
        kind: "identity",
        timestampMs: new Date(selectedDiagnosticVehicle.first_seen).getTime(),
        title: "Véhicule ajouté au garage",
        description: `Identité enregistrée sous le profil ${selectedDiagnosticVehicle.vehicle_profile}`,
        badge: "VIN confirmé",
        severity: "good",
      });
    }
    for (const entry of oilLog) {
      if (entry.vin !== selectedDiagnosticVin) continue;
      entries.push({
        id: entry.id,
        kind: "maintenance",
        timestampMs: new Date(entry.recorded_at).getTime(),
        title: "Relevé carnet d'entretien",
        description: `${entry.mileage_km.toLocaleString("fr-FR")} km${entry.oil_level_note ? ` · ${entry.oil_level_note}` : ""}${typeof entry.oil_added_l === "number" ? ` · +${entry.oil_added_l} L` : ""}`,
        badge: entry.mileage_source === "can_signal" ? "Kilométrage CAN" : "Kilométrage saisi",
        severity: "neutral",
      });
    }
    for (const entry of maintenanceRecords) {
      if (entry.vin !== selectedDiagnosticVin) continue;
      const eventDate = entry.performed_at || entry.purchased_at;
      if (!eventDate) continue;
      entries.push({
        id: entry.id,
        kind: "maintenance",
        timestampMs: new Date(`${eventDate}T12:00:00`).getTime(),
        title: entry.title,
        description: `${entry.mileage_km == null ? "Kilométrage inconnu" : `${entry.mileage_km.toLocaleString("fr-FR")} km`} · ${entry.parts.length} pièce(s)${entry.workshop ? ` · ${entry.workshop}` : ""}`,
        badge: entry.documents.length ? `${entry.documents.length} justificatif(s)` : entry.category,
        severity: "good",
      });
    }
    return entries
      .filter((entry) => Number.isFinite(entry.timestampMs) && (garageEventFilter === "all" || entry.kind === garageEventFilter))
      .sort((left, right) => right.timestampMs - left.timestampMs);
  }, [diagnosticReportHistory, garageEventFilter, maintenanceRecords, oilLog, selectedDiagnosticVehicle, selectedDiagnosticVin, vehicleLinkedSessions]);
  const activeVehicleLabel = selectedDiagnosticVehicle
    ? `${selectedDiagnosticVehicle.manufacturer} ${selectedDiagnosticVehicle.model}`
    : activeCommunicationProfile
      ? `${activeCommunicationProfile.manufacturer} ${activeCommunicationProfile.model}`
      : "Aucun profil chargé";
  const psaVehicleCompatible = Boolean(
    selectedDiagnosticVehicle
    && (
      selectedDiagnosticVehicle.manufacturer.toLocaleLowerCase("fr").includes("peugeot")
      || selectedDiagnosticVehicle.vehicle_profile.startsWith("peugeot_")
      || selectedDiagnosticVehicle.vehicle_profile.startsWith("psa_")
    ),
  );
  const directPsaCompatible = Boolean(
    activeCommunicationProfile
    && (
      activeCommunicationProfile.manufacturer.toLocaleLowerCase("fr").includes("peugeot")
      || activeCommunicationProfile.key.startsWith("peugeot_")
      || activeCommunicationProfile.key.startsWith("psa_")
    )
  );
  const activeTitle = viewTitles[view];
  const dualCanOperational = Boolean(
    capture?.active
    && capture.dual_can
    && capture.live_can_ready
    && capture.diagnostic_can_ready,
  );
  const diagnosticGatewayVerified = status?.transport === "virtual" || Boolean(status?.gateway_verified) || dualCanOperational;
  const liveObdReadOnly = status?.transport === "virtual" || status?.gateway_hello?.live_obd_read_only === true;
  const identityRequiresLiveObd = Boolean(selectedIdentityProfile?.identity_buses.includes("live"));
  const diagnosticReady = Boolean(
    status?.can_tx_enabled
    && diagnosticGatewayVerified
    && (!capture?.active || dualCanOperational),
  );
  const obdReadReady = Boolean(
    diagnosticReady
    && liveObdReadOnly,
  );
  const identityReadReady = Boolean(
    status?.can_tx_enabled
    && selectedIdentityProfile
    && selectedIdentityProfile.vin_methods.length > 0
    && !capture?.active,
  );
  const selectedPsaEcu = psaCatalog?.ecus.find((ecu) => ecu.key === psaEcuKey) ?? null;
  const selectedPsaAction = psaCatalog?.actions.find((action) => action.key === psaSelectedActionKey) ?? null;
  const psaUnlockEcu = psaCatalog?.ecus.find((ecu) => ecu.key === psaUnlockEcuKey) ?? null;
  const injectionValues = useMemo(
    () => new Map((injectionSnapshot?.values ?? []).map((value) => [value.key, value])),
    [injectionSnapshot],
  );
  const injectionGroups = useMemo(() => {
    const preferredOrder = ["Carburant", "Air", "Combustion", "Dépollution", "Températures", "Électrique", "Contexte"];
    return preferredOrder
      .map((group) => ({ group, sensors: diagnosticSensorCatalog.filter((sensor) => sensor.group === group) }))
      .filter(({ sensors }) => sensors.length > 0);
  }, [diagnosticSensorCatalog]);
  const engineDtcs = report?.ecus.find((ecu) => ecu.key === "engine")?.dtcs ?? [];

  useEffect(() => {
    setEcuWatchValues({});
    setDidSweepResult(null);
    setEcuLiveReport(null);
    setEcuResetConfirmation("");
    setEcuResetResult(null);
    setDtcClearConfirmation("");
    setDtcClearResult(null);
  }, [view]);

  useEffect(() => {
    if (!(ECU_LIVE_VIEW_KEYS as readonly View[]).includes(view)) return;
    const zones = psaCatalog?.ecus.find((item) => item.key === view)?.telecoding_zones ?? [];
    if (!psaVehicleCompatible || !diagnosticReady || zones.length === 0) return;
    let cancelled = false;
    let index = 0;
    const tick = async () => {
      if (cancelled) return;
      const zone = zones[index % zones.length];
      index += 1;
      try {
        const result = await api<DidValue>(
          `/api/diagnostic/psa/ecus/${encodeURIComponent(view)}/dids/0x${zone.did}`,
          { method: "POST" },
        );
        if (!cancelled) setEcuWatchValues((previous) => ({ ...previous, [zone.did]: result }));
      } catch {
        // Lecture ponctuelle échouée (NRC/timeout) : on garde la dernière valeur connue.
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 1200);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [view, psaCatalog, psaVehicleCompatible, diagnosticReady]);
  const sensorCategories = useMemo(
    () => ["Essentiels", "Toutes", ...Array.from(new Set(passiveSensors?.signals.map((signal) => signal.category) ?? []))],
    [passiveSensors],
  );
  const visiblePassiveSignals = useMemo(() => {
    const query = sensorSearch.trim().toLocaleLowerCase("fr");
    return (passiveSensors?.signals ?? []).filter((signal) => {
      if (sensorCategory === "Essentiels" && !signal.essential) return false;
      if (!["Toutes", "Essentiels"].includes(sensorCategory) && signal.category !== sensorCategory) return false;
      if (!query) return true;
      return `${signal.category} ${signal.display_name} ${signal.description} ${signal.message} ${signal.signal}`.toLocaleLowerCase("fr").includes(query);
    });
  }, [passiveSensors, sensorCategory, sensorSearch]);
  const passiveSubsystems = useMemo(() => {
    const definitions = [
      ["Moteur", "Calculateur moteur", "Régime, accélérateur, couple et états moteur"],
      ["Freinage / ABS", "ABS / ESP", "Vitesses des roues, freinage et stabilité"],
      ["Direction", "Direction / capteur volant", "Angle, vitesse et effort au volant"],
      ["Habitacle / BSI", "BSI et commandes habitacle", "Portes, éclairage, essuie-glaces et commandes"],
      ["ADAS / caméra", "Caméra et aides à la conduite", "Maintien dans la voie et régulation"],
      ["Airbag / retenue", "Airbag et retenue", "Ceintures et états du système de retenue"],
      ["Transmission", "Boîte de vitesses", "Rapports, autorisations et états de transmission"],
      ["Climatisation", "Climatisation", "Commande compresseur, ventilation et charge"],
    ] as const;
    return definitions.map(([category, name, description]) => {
      const messages = Array.from(new Set(
        (passiveSensors?.signals ?? [])
          .filter((signal) => signal.category === category)
          .map((signal) => signal.message),
      ));
      return { category, name, description, messages, detected: messages.length > 0 };
    });
  }, [passiveSensors]);
  const currentReplayIndex = useMemo(
    () => replay?.points.length ? replayPointIndex(replay.points, replayTimeMs) : 0,
    [replay, replayTimeMs],
  );
  const currentReplayPoint = replay?.points[currentReplayIndex] ?? null;
  const studioLiveSample = useMemo(() => {
    if (!passiveSensors) return null;
    const sample = passiveSnapshotToReplaySample(passiveSensors);
    const rawFuel = sample.point.fuel_liters_raw;
    if (typeof rawFuel === "number" && Number.isFinite(rawFuel)) {
      const filter = studioFuelFilterRef.current;
      if (filter.sessionId !== passiveSensors.session_id || filter.value === null) {
        filter.sessionId = passiveSensors.session_id;
        filter.generatedAtUs = passiveSensors.generated_at_us;
        filter.value = rawFuel;
      } else if (passiveSensors.generated_at_us > filter.generatedAtUs) {
        const elapsedS = Math.max(0, Math.min(5, (passiveSensors.generated_at_us - filter.generatedAtUs) / 1_000_000));
        const alpha = 1 - Math.exp(-elapsedS / 120);
        filter.value += alpha * (rawFuel - filter.value);
        filter.generatedAtUs = passiveSensors.generated_at_us;
      }
      sample.point.fuel_liters = Number(filter.value.toFixed(2));
      if (!sample.availableFields.includes("fuel_liters")) sample.availableFields.push("fuel_liters");
    }
    return sample;
  }, [passiveSensors]);
  const sensorInventoryRows = useMemo<SensorInventoryRow[]>(() => {
    const statusLabels: Record<SensorInventoryStatus, string> = {
      measured: "Mesuré",
      supported: "Supporté · à relire",
      to_test: "À tester",
      to_observe: "À observer",
      to_decode: "À décoder",
      unsupported: "Non exposé OBD",
      not_applicable: "Non applicable",
    };
    const availableFields = new Set(studioLiveSample?.availableFields ?? []);
    const point = studioLiveSample?.point;
    const formatInventoryValue = (raw: unknown) => {
      if (typeof raw === "boolean") return raw ? "Actif" : "Inactif";
      if (typeof raw === "number") return raw.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
      if (typeof raw === "string") return raw;
      return null;
    };
    const advancedRows: SensorInventoryRow[] = sensorCandidatesForProfile(activeCommunicationProfileKey).map((candidate) => {
      const applicability = candidate.applicability ?? "all";
      const excluded = effectivePowertrainProfile !== "unknown" && applicability !== "all" && applicability !== effectivePowertrainProfile;
      let status: SensorInventoryStatus = excluded ? "not_applicable" : candidate.source === "can" ? "to_observe" : "to_decode";
      let value: string | null = null;
      if (!excluded && candidate.liveFields?.length) {
        const observedField = (candidate.liveFields ?? []).find((field) => availableFields.has(field));
        if (observedField) {
          status = "measured";
          value = formatInventoryValue(point?.[observedField as keyof ReplaySample]);
        }
      }
      return {
        id: candidate.id,
        label: candidate.label,
        system: candidate.system,
        description: candidate.description,
        source: candidate.source === "can" ? "CAN / OBD direct" : candidate.source === "fiat" ? "Fiat spécifique" : "PSA spécifique",
        status,
        statusLabel: statusLabels[status],
        priority: candidate.priority,
        optional: Boolean(candidate.optional),
        value,
        reference: candidate.source === "can"
          ? candidate.liveFields?.join(" · ")
          : candidate.source === "fiat"
            ? "Paramètre IAW/Body CAN Fiat à identifier"
            : "DID ou trame PSA à identifier",
      };
    });
    const criticalObdKeys = new Set([
      "engine_rpm", "coolant_temperature", "fuel_pressure", "intake_manifold_pressure", "maf",
      "fuel_rail_gauge_pressure", "absolute_fuel_rail_pressure", "fuel_rate", "control_module_voltage",
      "engine_load", "throttle_position", "timing_advance", "short_fuel_trim_bank_1",
      "long_fuel_trim_bank_1", "oxygen_sensor_b1s1_voltage", "oxygen_sensor_b1s2_voltage",
    ]);
    const fiatNotApplicableObdKeys = new Set([
      "short_fuel_trim_bank_2", "long_fuel_trim_bank_2",
      "fuel_rail_gauge_pressure", "absolute_fuel_rail_pressure",
      "commanded_egr", "egr_error",
    ]);
    const obdRows: SensorInventoryRow[] = diagnosticSensorCatalog.map((sensor) => {
      const value = injectionValues.get(sensor.key);
      const supported = Boolean(injectionSnapshot?.supported_pids.includes(sensor.pid));
      const excluded = activeIsFiat500 && fiatNotApplicableObdKeys.has(sensor.key) && !supported;
      let status: SensorInventoryStatus = excluded ? "not_applicable" : "to_test";
      if (injectionSnapshot) status = supported ? value?.error ? "supported" : typeof value?.value === "number" ? "measured" : "supported" : excluded ? "not_applicable" : "unsupported";
      return {
        id: `obd-${sensor.key}`,
        label: sensor.name,
        system: sensor.group === "Dépollution" ? "Dépollution" : "Moteur / injection",
        description: sensor.description,
        source: "OBD-II",
        status,
        statusLabel: statusLabels[status],
        priority: criticalObdKeys.has(sensor.key) ? 1 : 2,
        optional: false,
        value: typeof value?.value === "number" ? `${value.value.toLocaleString("fr-FR", { maximumFractionDigits: 3 })} ${value.unit ?? sensor.unit}` : null,
        reference: `Mode 01 · PID 0x${sensor.pid.toString(16).toUpperCase().padStart(2, "0")}`,
      };
    });
    return [...obdRows, ...advancedRows].sort((left, right) =>
      left.priority - right.priority || left.system.localeCompare(right.system, "fr") || left.label.localeCompare(right.label, "fr"),
    );
  }, [activeCommunicationProfileKey, activeIsFiat500, diagnosticSensorCatalog, effectivePowertrainProfile, injectionSnapshot, injectionValues, studioLiveSample]);
  const inventorySystems = useMemo(
    () => ["Tous", ...Array.from(new Set(sensorInventoryRows.map((row) => row.system)))],
    [sensorInventoryRows],
  );
  const visibleInventoryRows = useMemo(() => {
    const query = inventorySearch.trim().toLocaleLowerCase("fr");
    return sensorInventoryRows.filter((row) => {
      if (inventorySystem !== "Tous" && row.system !== inventorySystem) return false;
      if (inventoryPriorityOnly && row.priority !== 1) return false;
      if (inventoryStatus === "available" && !["measured", "supported"].includes(row.status)) return false;
      if (inventoryStatus === "missing" && !["to_test", "to_observe", "to_decode", "unsupported"].includes(row.status)) return false;
      if (inventoryStatus === "excluded" && row.status !== "not_applicable") return false;
      if (!query) return true;
      return `${row.label} ${row.system} ${row.description} ${row.source} ${row.reference ?? ""}`.toLocaleLowerCase("fr").includes(query);
    });
  }, [inventoryPriorityOnly, inventorySearch, inventoryStatus, inventorySystem, sensorInventoryRows]);
  const inventoryCounts = useMemo(() => ({
    measured: sensorInventoryRows.filter((row) => row.status === "measured").length,
    supported: sensorInventoryRows.filter((row) => row.status === "supported").length,
    missing: sensorInventoryRows.filter((row) => ["to_test", "to_observe", "to_decode", "unsupported"].includes(row.status)).length,
    excluded: sensorInventoryRows.filter((row) => row.status === "not_applicable").length,
  }), [sensorInventoryRows]);
  const validationQueue = useMemo(
    () => sensorInventoryRows.filter((row) => ["to_test", "to_observe", "to_decode", "supported"].includes(row.status)),
    [sensorInventoryRows],
  );
  const focusedValidationRow = validationQueue.find((row) => row.id === validationFocusId)
    ?? validationQueue.find((row) => row.priority === 1)
    ?? validationQueue[0]
    ?? null;
  const liveSafetyEvidence = useMemo(() => {
    if (!passiveSensors?.active || studioLiveHistory.length < 2) {
      return { speedKnown: false, stationary: false, rpmKnown: false, engineOff: false, batteryKnown: false, batteryStable: false, batteryValue: null as number | null };
    }
    const latestMs = studioLiveHistory.at(-1)?.t_ms ?? 0;
    const recent = studioLiveHistory.filter((point) => point.t_ms >= latestMs - 5_000);
    const speeds = recent.map((point) => point.speed_kph).filter((value): value is number => typeof value === "number");
    const rpms = recent.map((point) => point.engine_rpm).filter((value): value is number => typeof value === "number");
    const voltages = recent.map((point) => point.battery_voltage_v).filter((value): value is number => typeof value === "number");
    return {
      speedKnown: speeds.length >= 2,
      stationary: speeds.length >= 2 && Math.max(...speeds) <= 0.5,
      rpmKnown: rpms.length >= 2,
      engineOff: rpms.length >= 2 && Math.max(...rpms) < 50,
      batteryKnown: voltages.length >= 5,
      batteryStable: voltages.length >= 5 && Math.min(...voltages) >= 11.7 && Math.max(...voltages) <= 15.2 && Math.max(...voltages) - Math.min(...voltages) <= 0.4,
      batteryValue: voltages.at(-1) ?? null,
    };
  }, [passiveSensors?.active, studioLiveHistory]);
  const effectivePsaLabChecks = {
    vehicle_stationary: liveSafetyEvidence.speedKnown ? liveSafetyEvidence.stationary : psaLabChecks.vehicle_stationary,
    ignition_on_engine_off: liveSafetyEvidence.rpmKnown ? liveSafetyEvidence.engineOff : psaLabChecks.ignition_on_engine_off,
    stable_battery_voltage: liveSafetyEvidence.batteryKnown ? liveSafetyEvidence.batteryStable : psaLabChecks.stable_battery_voltage,
    workshop_or_private_site: psaLabChecks.workshop_or_private_site,
  };
  const psaLabChecksComplete = Object.values(effectivePsaLabChecks).every(Boolean);
  const currentRouteGeometry = useMemo(() => routeGeometry(replay), [replay]);
  const currentReplayGraphGeometries = useMemo(() => {
    const geometries = new Map<string, ReplayGraphGeometry>();
    if (!replay) return geometries;
    selectedReplayGraphKeys.forEach((key) => {
      const definition = replayGaugeCatalog.find((candidate) => candidate.key === key && !candidate.status);
      if (definition && replay.available_fields.includes(String(definition.key))) {
        geometries.set(key, replayGraphGeometry(replay, definition));
      }
    });
    return geometries;
  }, [replay, selectedReplayGraphKeys]);
  const studioGraphGeometries = useMemo(() => {
    const geometries = new Map<string, ReplayGraphGeometry>();
    studioWidgets.filter((widget) => widget.kind === "graph" && widget.key).forEach((widget) => {
      const definition = replayGaugeCatalog.find((candidate) => candidate.key === widget.key && !candidate.status);
      const windowSeconds = STUDIO_GRAPH_WINDOWS.includes(widget.windowSeconds as StudioGraphWindowSeconds)
        ? widget.windowSeconds as StudioGraphWindowSeconds
        : 60;
      if (definition) geometries.set(widget.id, liveGraphGeometry(studioLiveHistory, definition, windowSeconds));
    });
    return geometries;
  }, [studioLiveHistory, studioWidgets]);

  useEffect(() => {
    if (!passiveSensors?.active || !studioLiveSample) return;
    if (studioLiveSessionRef.current !== passiveSensors.session_id) {
      studioLiveSessionRef.current = passiveSensors.session_id;
      studioLiveStartUs.current = passiveSensors.generated_at_us;
      setStudioLiveHistory([{ ...studioLiveSample.point, t_ms: 0 }]);
      return;
    }
    const tMs = Math.max(0, (passiveSensors.generated_at_us - studioLiveStartUs.current) / 1000);
    const point = { ...studioLiveSample.point, t_ms: tMs };
    setStudioLiveHistory((current) => [...current, point]
      .filter((item) => item.t_ms >= tMs - 300_000)
      .slice(-1800));
  }, [passiveSensors?.active, passiveSensors?.generated_at_us, passiveSensors?.session_id, studioLiveSample]);

  async function refreshTransportCatalog() {
    try {
      const payload = await api<TransportCatalog>("/api/system/transports");
      setTransportCatalog(payload);
      setSelectedTransportId((current) => current || payload.current_id || payload.options.find((option) => option.detected)?.id || payload.options[0]?.id || "");
    } catch {
      // Le statut général du backend rend déjà une indisponibilité explicite.
    }
  }

  async function refreshOperatingMode() {
    try {
      setOperatingMode(await api<OperatingModeState>("/api/system/operating-mode"));
    } catch {
      setOperatingMode(null);
    }
  }

  function openMaintenanceModeDialog() {
    setError("");
    setModeConfirmation("");
    setModeChecks({
      vehicle_stationary: false,
      ignition_on_engine_off: false,
      stable_battery_voltage: false,
      workshop_or_private_site: false,
    });
    setModeDialogOpen(true);
    void refreshOperatingMode();
  }

  async function activateReadOnlyMode() {
    if (operatingMode?.mode === "read_only") return;
    setModeSwitchBusy(true);
    setError("");
    try {
      const payload = await api<OperatingModeState>("/api/system/operating-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "read_only", vin: selectedDiagnosticVin || null }),
      });
      setOperatingMode(payload);
      setStatus(await api<Status>("/api/system/status"));
      setPsaCatalog(await api<PsaAdvancedCatalog>("/api/diagnostic/psa/catalog").catch(() => null));
      setModeDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setModeSwitchBusy(false);
    }
  }

  async function activateMaintenanceMode(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedDiagnosticVin) {
      setError("Charge d’abord le véhicule concerné depuis le Garage.");
      return;
    }
    setModeSwitchBusy(true);
    setError("");
    try {
      const payload = await api<OperatingModeState>("/api/system/operating-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "maintenance",
          confirmation: modeConfirmation,
          vin: selectedDiagnosticVin,
          ...modeChecks,
        }),
      });
      setOperatingMode(payload);
      setStatus(await api<Status>("/api/system/status"));
      setPsaCatalog(await api<PsaAdvancedCatalog>("/api/diagnostic/psa/catalog").catch(() => null));
      setModeDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setModeSwitchBusy(false);
    }
  }

  async function connectSelectedTransport() {
    const option = transportCatalog?.options.find((candidate) => candidate.id === selectedTransportId);
    if (!option || capture?.active) return;
    setTransportConnectBusy(true);
    setTransportMessage("");
    setError("");
    try {
      const connection = await api<TransportConnection>("/api/system/transport/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transport: option.transport, endpoint: option.endpoint, baud: option.baud ?? null }),
      });
      const nextStatus = await api<Status>("/api/system/status");
      setStatus(nextStatus);
      setStatusError("");
      setTransportMessage(connection.verified ? "ESP32 validé" : "Connexion non validée");
      await refreshTransportCatalog();
      await refreshOperatingMode();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setTransportMessage("Échec de connexion");
      setError(message);
      await refreshTransportCatalog();
    } finally {
      setTransportConnectBusy(false);
    }
  }

  async function refreshCapture() {
    try {
      setCapture(await api<CaptureStatus>("/api/learn/capture/status"));
    } catch {
      // Le panneau principal rend déjà l'indisponibilité du backend explicite.
    }
  }

  async function refreshSessions() {
    try {
      setSessions(await api<DiscoverySession[]>("/api/learn/sessions"));
    } catch {
      // Même principe : pas de deuxième alerte pour une unique panne réseau.
    }
  }

  async function setSignalManualValidation(key: string, validated: boolean) {
    if (!replaySessionId) return;
    setSignalValidationBusy(key);
    setError("");
    try {
      await api(`/api/learn/signals/${encodeURIComponent(key)}/validation`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ validated, session_id: replaySessionId }),
      });
      const updated = await api<ReplayValidation>(`/api/learn/replay/${encodeURIComponent(replaySessionId)}/validation`);
      setReplayValidation(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSignalValidationBusy("");
    }
  }

  async function clearSignalManualValidation(key: string) {
    if (!replaySessionId) return;
    setSignalValidationBusy(key);
    setError("");
    try {
      await api(`/api/learn/signals/${encodeURIComponent(key)}/validation`, { method: "DELETE" });
      const updated = await api<ReplayValidation>(`/api/learn/replay/${encodeURIComponent(replaySessionId)}/validation`);
      setReplayValidation(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSignalValidationBusy("");
    }
  }

  async function loadReplay(sessionId: string, force = false) {
    if (!sessionId) return;
    setReplayBusy(true);
    setReplayPlaying(false);
    setReplaySessionId(sessionId);
    setReplayTimeMs(0);
    setReplayValidation(null);
    setError("");
    try {
      const payload = await api<ReplayData>(`/api/learn/replay/${encodeURIComponent(sessionId)}${force ? "?force=true" : ""}`);
      setReplay(payload);
      const validation = await api<ReplayValidation>(`/api/learn/replay/${encodeURIComponent(sessionId)}/validation${force ? "?force=true" : ""}`);
      setReplayValidation(validation);
    } catch (err) {
      setReplay(null);
      setReplayValidation(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReplayBusy(false);
    }
  }

  function stopGpsTracking() {
    if (gpsWatchRef.current !== null && "geolocation" in navigator) {
      navigator.geolocation.clearWatch(gpsWatchRef.current);
    }
    gpsWatchRef.current = null;
    gpsLastSentAtRef.current = 0;
    setGpsTracking((current) => current.state === "idle" ? current : { state: "idle" });
  }

  function startGpsTracking(sessionId: string) {
    if (gpsWatchRef.current !== null) return;
    if (!("geolocation" in navigator)) {
      setGpsTracking({ state: "unavailable", message: "Géolocalisation absente de ce navigateur." });
      return;
    }
    if (!window.isSecureContext) {
      setGpsTracking({
        state: "unavailable",
        message: "Le GPS navigateur exige HTTPS ou une ouverture sur localhost.",
      });
      return;
    }

    setGpsTracking({ state: "requesting", message: "Autorisation GPS en attente…" });
    gpsWatchRef.current = navigator.geolocation.watchPosition(
      (position) => {
        const now = Date.now();
        if (now - gpsLastSentAtRef.current < 250) return;
        gpsLastSentAtRef.current = now;
        const finiteOrNull = (value: number | null) => value !== null && Number.isFinite(value) ? value : null;
        setGpsTracking({
          state: "active",
          accuracyM: position.coords.accuracy,
          message: `Position reçue à ±${Math.round(position.coords.accuracy)} m`,
        });
        void api<CaptureStatus>("/api/learn/capture/gps", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy_m: position.coords.accuracy,
            altitude_m: finiteOrNull(position.coords.altitude),
            altitude_accuracy_m: finiteOrNull(position.coords.altitudeAccuracy),
            heading_deg: finiteOrNull(position.coords.heading),
            speed_m_s: finiteOrNull(position.coords.speed),
            source_timestamp_us: Math.round(position.timestamp * 1000),
          }),
        }).then((payload) => {
          if (payload.session_id === sessionId) setCapture(payload);
        }).catch((err) => {
          setGpsTracking({
            state: "error",
            accuracyM: position.coords.accuracy,
            message: err instanceof Error ? err.message : String(err),
          });
        });
      },
      (positionError) => {
        const denied = positionError.code === positionError.PERMISSION_DENIED;
        setGpsTracking({
          state: denied ? "denied" : "error",
          message: denied
            ? "Autorisation GPS refusée; la capture CAN continue sans coordonnées."
            : positionError.code === positionError.POSITION_UNAVAILABLE
              ? "Position GPS indisponible."
              : "Délai GPS dépassé; nouvelle tentative en cours.",
        });
      },
      { enableHighAccuracy: true, maximumAge: 1_000, timeout: 15_000 },
    );
  }

  function seekReplay(timeMs: number) {
    setReplayTimeMs(Math.max(0, Math.min(replay?.duration_ms ?? 0, timeMs)));
  }

  function addReplayGauge() {
    if (!replayGaugeToAdd || selectedReplayGaugeKeys.includes(replayGaugeToAdd)) return;
    setSelectedReplayGaugeKeys((current) => [...current, replayGaugeToAdd]);
    setReplayGaugeToAdd("");
  }

  function removeReplayGauge(key: string) {
    setSelectedReplayGaugeKeys((current) => current.filter((item) => item !== key));
  }

  function addReplayGraph() {
    if (!replayGraphToAdd || selectedReplayGraphKeys.includes(replayGraphToAdd)) return;
    setSelectedReplayGraphKeys((current) => [...current, replayGraphToAdd]);
    setReplayGraphToAdd("");
  }

  function removeReplayGraph(key: string) {
    setSelectedReplayGraphKeys((current) => current.filter((item) => item !== key));
  }

  function addReplayIndicator() {
    if (!replayIndicatorToAdd || selectedReplayIndicatorKeys.includes(replayIndicatorToAdd)) return;
    setSelectedReplayIndicatorKeys((current) => [...current, replayIndicatorToAdd]);
    setReplayIndicatorToAdd("");
  }

  function removeReplayIndicator(key: string) {
    setSelectedReplayIndicatorKeys((current) => current.filter((item) => item !== key));
  }

  function addStudioWidget() {
    if (!studioWidgetToAdd) return;
    const [rawKind, key] = studioWidgetToAdd.split(":", 2);
    const kind = rawKind as StudioWidgetKind;
    const dimensions: Record<StudioWidgetKind, { w: number; h: number }> = {
      speed: { w: 3, h: 4 },
      steering: { w: 3, h: 4 },
      gear: { w: 2, h: 4 },
      vehicle: { w: 4, h: 6 },
      capture: { w: 6, h: 2 },
      gauge: { w: 2, h: 3 },
      graph: { w: 4, h: 3 },
      numeric: { w: 2, h: 2 },
      lamp: { w: 2, h: 2 },
      indicator: { w: 2, h: 2 },
    };
    const size = dimensions[kind] ?? dimensions.gauge;
    let position = { x: 0, y: 0 };
    let found = false;
    for (let y = 0; y < 16 && !found; y += 1) {
      for (let x = 0; x <= STUDIO_COLUMNS - size.w; x += 1) {
        const overlaps = studioWidgets.some((widget) =>
          x < widget.x + widget.w && x + size.w > widget.x && y < widget.y + widget.h && y + size.h > widget.y,
        );
        if (!overlaps) {
          position = { x, y };
          found = true;
          break;
        }
      }
    }
    if (!found) position = { x: 0, y: Math.max(0, ...studioWidgets.map((widget) => widget.y + widget.h)) };
    const id = `studio-${kind}-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`;
    setStudioWidgets((current) => [...current, {
      id,
      kind,
      key: key || undefined,
      ...position,
      ...size,
      ...(kind === "graph" ? { windowSeconds: 60 as StudioGraphWindowSeconds } : {}),
    }]);
  }

  function removeStudioWidget(id: string) {
    setStudioWidgets((current) => current.filter((widget) => widget.id !== id));
  }

  function setStudioGraphWindow(id: string, windowSeconds: StudioGraphWindowSeconds) {
    setStudioWidgets((current) => current.map((widget) => widget.id === id ? { ...widget, windowSeconds } : widget));
  }

  function setStudioSensorStyle(id: string, kind: StudioSensorStyle) {
    setStudioWidgets((current) => current.map((widget) => {
      if (widget.id !== id) return widget;
      if (kind === "lamp" && !replayGaugeCatalog.find((definition) => definition.key === widget.key)?.status) return widget;
      const minimum = kind === "graph" ? { w: 3, h: 3 } : { w: 2, h: 2 };
      return {
        ...widget,
        kind,
        w: Math.max(widget.w, minimum.w),
        h: Math.max(widget.h, minimum.h),
        ...(kind === "graph" && !widget.windowSeconds ? { windowSeconds: 60 as StudioGraphWindowSeconds } : {}),
      };
    }));
  }

  function resizeStudioWidget(id: string, delta: -1 | 1) {
    const boardHeight = studioBoardRef.current?.getBoundingClientRect().height ?? STUDIO_ROW_HEIGHT * 10;
    const maximumRows = Math.max(10, Math.floor(boardHeight / STUDIO_ROW_HEIGHT));
    setStudioWidgets((current) => current.map((widget) => {
      if (widget.id !== id) return widget;
      const minimum = widget.kind === "capture"
        ? { w: 4, h: 2 }
        : widget.kind === "graph" || widget.kind === "vehicle"
          ? { w: 3, h: 3 }
          : { w: 2, h: 2 };
      return {
        ...widget,
        w: Math.max(minimum.w, Math.min(STUDIO_COLUMNS - widget.x, widget.w + delta)),
        h: Math.max(minimum.h, Math.min(maximumRows - widget.y, widget.h + delta)),
      };
    }));
  }

  function beginStudioInteraction(event: React.PointerEvent, widget: StudioWidget, mode: "move" | "resize") {
    if (!studioEditing || !studioBoardRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    studioInteractionCleanup.current?.();
    setStudioWidgets((current) => [...current.filter((item) => item.id !== widget.id), widget]);
    const boardBounds = studioBoardRef.current.getBoundingClientRect();
    const startX = event.clientX;
    const startY = event.clientY;
    const columnWidth = boardBounds.width / STUDIO_COLUMNS;
    const maximumRows = Math.max(10, Math.floor(boardBounds.height / STUDIO_ROW_HEIGHT));
    const minimum = widget.kind === "capture"
      ? { w: 4, h: 2 }
      : widget.kind === "graph" || widget.kind === "vehicle"
        ? { w: 3, h: 3 }
        : { w: 2, h: 2 };
    const onPointerMove = (moveEvent: PointerEvent) => {
      const deltaColumns = Math.round((moveEvent.clientX - startX) / columnWidth);
      const deltaRows = Math.round((moveEvent.clientY - startY) / STUDIO_ROW_HEIGHT);
      setStudioWidgets((current) => current.map((item) => {
        if (item.id !== widget.id) return item;
        if (mode === "move") {
          return {
            ...item,
            x: Math.max(0, Math.min(STUDIO_COLUMNS - item.w, widget.x + deltaColumns)),
            y: Math.max(0, Math.min(maximumRows - item.h, widget.y + deltaRows)),
          };
        }
        return {
          ...item,
          w: Math.max(minimum.w, Math.min(STUDIO_COLUMNS - item.x, widget.w + deltaColumns)),
          h: Math.max(minimum.h, Math.min(maximumRows - item.y, widget.h + deltaRows)),
        };
      }));
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
      document.body.style.userSelect = "";
      studioInteractionCleanup.current = null;
    };
    studioInteractionCleanup.current = cleanup;
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
  }

  async function toggleStudioFullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function refreshPassiveSensors(openView = false) {
    if (sensorRefreshBusy.current) return;
    sensorRefreshBusy.current = true;
    try {
      const cursor = sensorCursorUs.current;
      const query = new URLSearchParams();
      if (cursor > 0) query.set("since_us", String(cursor));
      if (selectedDiagnosticVin) query.set("vin", selectedDiagnosticVin);
      const path = `/api/live-data/snapshot${query.toString() ? `?${query.toString()}` : ""}`;
      const payload = await api<PassiveSensorSnapshot>(path);
      setPassiveSensors((current) => {
        if (!current || current.session_id !== payload.session_id || cursor === 0) return payload;
        const merged = new Map(current.signals.map((signal) => [signal.key, signal]));
        payload.signals.forEach((signal) => merged.set(signal.key, signal));
        return {
          ...payload,
          signals: Array.from(merged.values()).sort((left, right) =>
            `${left.category}.${left.display_name}`.localeCompare(`${right.category}.${right.display_name}`, "fr"),
          ),
        };
      });
      sensorCursorUs.current = Math.max(cursor, payload.cursor_us);
      setError((current) => current.includes("CAN_TX_ENABLED=true") ? "" : current);
      if (openView) {
        setError("");
        setView("sensors");
      }
    } catch (err) {
      if (openView) setError(err instanceof Error ? err.message : String(err));
    } finally {
      sensorRefreshBusy.current = false;
    }
  }

  async function openPassiveSensors() {
    setError("");
    setView("sensors");
    await Promise.all([refreshPassiveSensors(), refreshLiveSensorDefinitions()]);
  }

  async function refreshLiveSensorDefinitions() {
    try {
      const query = new URLSearchParams();
      if (selectedDiagnosticVin) query.set("vin", selectedDiagnosticVin);
      const definitions = await api<LiveSensorDefinition[]>(
        `/api/live-data/sensors${query.toString() ? `?${query.toString()}` : ""}`,
      );
      setLiveSensorDefinitions(definitions);
    } catch {
      setLiveSensorDefinitions([]);
    }
  }

  async function startFullSensorDetection(openSensors = true, liveDataReads = true) {
    setDetectionBusy(true);
    setError("");
    setSensorCategory("Essentiels");
    setSensorSearch("");
    try {
      const query = selectedDiagnosticVin ? `?vin=${encodeURIComponent(selectedDiagnosticVin)}` : "";
      const endpoint = liveDataReads ? "/api/live-data/detect" : "/api/learn/sensors/passive/detect";
      const payload = await api<PassiveSensorSnapshot>(`${endpoint}${query}`, {
        method: "POST",
      });
      sensorCursorUs.current = payload.cursor_us;
      setPassiveSensors(payload);
      if (openSensors) setView("sensors");
      setDetectionEndsAt(Date.now() + 30_000);
      setDetectionRemaining(30);
      await refreshCapture();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetectionBusy(false);
    }
  }

  function editPassiveSensor(signal: PassiveCanSignal) {
    setSensorEditor({
      key: signal.key,
      label: signal.display_name,
      description: signal.description,
      unit: signal.unit ?? "",
      factor: String(signal.factor),
      offset: String(signal.offset),
      customized: signal.customized,
    });
  }

  async function savePassiveSensorOverride(event: React.FormEvent) {
    event.preventDefault();
    if (!sensorEditor) return;
    setSensorEditorBusy(true);
    setError("");
    try {
      await api("/api/learn/sensors/passive/override", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key: sensorEditor.key,
          label: sensorEditor.label.trim() || null,
          description: sensorEditor.description.trim() || null,
          unit: sensorEditor.unit.trim(),
          factor: Number(sensorEditor.factor),
          offset: Number(sensorEditor.offset),
        }),
      });
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSensorEditorBusy(false);
    }
  }

  async function resetPassiveSensorOverride() {
    if (!sensorEditor) return;
    setSensorEditorBusy(true);
    setError("");
    try {
      await api(`/api/learn/sensors/passive/override/${encodeURIComponent(sensorEditor.key)}`, {
        method: "DELETE",
      });
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSensorEditorBusy(false);
    }
  }

  function createLiveSensor() {
    if (!selectedDiagnosticVin) {
      setError("Charge d’abord un véhicule dans le Garage pour rattacher ce capteur à son VIN.");
      return;
    }
    const source = passiveSensors?.signals.find((signal) => !signal.user_defined);
    if (!source) {
      setError("Aucune source CAN ou OBD décodée n’est disponible pour créer un capteur.");
      return;
    }
    setLiveSensorEditor({
      sourceKey: source.key,
      label: "",
      description: "",
      category: source.category || "Personnalisés",
      unit: source.unit ?? "",
      factor: "1",
      offset: "0",
    });
  }

  function editLiveSensor(signal: PassiveCanSignal) {
    const definition = liveSensorDefinitions.find((item) => item.key === signal.definition_key);
    if (!definition) {
      setError("Définition locale de ce capteur introuvable.");
      return;
    }
    setLiveSensorEditor({
      key: definition.key,
      sourceKey: definition.source_key,
      label: definition.label,
      description: definition.description,
      category: definition.category,
      unit: definition.unit ?? "",
      factor: String(definition.factor),
      offset: String(definition.offset),
    });
  }

  async function saveLiveSensor(event: React.FormEvent) {
    event.preventDefault();
    if (!liveSensorEditor) return;
    setLiveSensorEditorBusy(true);
    setError("");
    const editing = Boolean(liveSensorEditor.key);
    try {
      const common = {
        label: liveSensorEditor.label.trim(),
        description: liveSensorEditor.description.trim(),
        category: liveSensorEditor.category.trim() || "Personnalisés",
        unit: liveSensorEditor.unit.trim() || null,
        factor: Number(liveSensorEditor.factor),
        offset: Number(liveSensorEditor.offset),
      };
      await api(
        editing
          ? `/api/live-data/sensors/${encodeURIComponent(liveSensorEditor.key!)}`
          : "/api/live-data/sensors",
        {
          method: editing ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(editing
            ? { ...common, archived: false }
            : {
                ...common,
                source_key: liveSensorEditor.sourceKey,
                vin: selectedDiagnosticVin || null,
              }),
        },
      );
      await refreshLiveSensorDefinitions();
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setLiveSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLiveSensorEditorBusy(false);
    }
  }

  async function archiveLiveSensor() {
    if (!liveSensorEditor?.key) return;
    if (!window.confirm("Supprimer ce capteur des vues Live Data ? Son historique restera conservé.")) return;
    setLiveSensorEditorBusy(true);
    setError("");
    try {
      await api(`/api/live-data/sensors/${encodeURIComponent(liveSensorEditor.key)}`, {
        method: "DELETE",
      });
      await refreshLiveSensorDefinitions();
      sensorCursorUs.current = 0;
      await refreshPassiveSensors();
      setLiveSensorEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLiveSensorEditorBusy(false);
    }
  }

  async function refreshDiagnosticHistory(preferredVin?: string, preferredProfile?: string) {
    try {
      const [vehicles, activeVehicle] = await Promise.all([
        api<DiagnosticVehicle[]>("/api/diagnostic/vehicles"),
        api<DiagnosticVehicle>("/api/diagnostic/vehicles/active").catch(() => null),
      ]);
      setDiagnosticVehicles(vehicles);
      const rememberedVin = preferredVin ?? activeVehicle?.vin ?? selectedDiagnosticVin;
      const selected = vehicles.some((vehicle) => vehicle.vin === rememberedVin)
        ? rememberedVin
        : vehicles[0]?.vin ?? "";
      const profile = preferredProfile
        ?? vehicles.find((vehicle) => vehicle.vin === selected)?.vehicle_profile
        ?? status?.vehicle_profile
        ?? identityProfileKey;
      setSelectedDiagnosticVin(selected);

      const query = new URLSearchParams();
      if (selected) query.set("vin", selected);
      else if (profile) query.set("vehicle_profile", profile);
      const suffix = query.toString() ? `?${query.toString()}` : "";
      const [latest, history, observations, oilLogEntries, maintenanceEntries, providers] = await Promise.all([
        api<Report>(`/api/diagnostic/reports/latest${suffix}`).catch(() => null),
        api<DiagnosticReportSummary[]>(`/api/diagnostic/reports${suffix}`).catch(() => []),
        api<ObservedDtc[]>(`/api/diagnostic/dtcs/observed${suffix}`).catch(() => []),
        api<OilLogEntry[]>(`/api/diagnostic/oil-log${suffix}`).catch(() => []),
        selected
          ? api<MaintenanceRecord[]>(`/api/maintenance/records?vin=${encodeURIComponent(selected)}`).catch(() => [])
          : Promise.resolve([]),
        api<ServiceProvider[]>("/api/maintenance/providers").catch(() => []),
      ]);
      setReport(latest);
      setDiagnosticReportHistory(history);
      setObservedDtcs(observations);
      setOilLog(oilLogEntries);
      setMaintenanceRecords(maintenanceEntries);
      setMaintenanceProviders(providers);
    } catch {
      setDiagnosticVehicles([]);
      setDiagnosticReportHistory([]);
      setObservedDtcs([]);
      setOilLog([]);
      setMaintenanceRecords([]);
      setMaintenanceProviders([]);
    }
  }

  async function recordOilLogEntry(entry: OilLogEntryInput) {
    setOilLogBusy(true);
    try {
      // Le VIN est résolu côté backend depuis le véhicule actif de ce profil
      // (comme les DTC observés) ; on ne fait que préciser le profil courant.
      const saved = await api<OilLogEntry>("/api/diagnostic/oil-log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...entry, vehicle_profile: activeCommunicationProfileKey }),
      });
      setOilLog((current) => [...current, saved]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOilLogBusy(false);
    }
  }

  async function uploadMaintenanceDocuments(record: MaintenanceRecord, documents: File[]) {
    for (const document of documents) {
      const form = new FormData();
      form.append("vin", record.vin);
      form.append("kind", "invoice");
      form.append("document", document);
      const uploaded = await api<MaintenanceRecord>(
        `/api/maintenance/records/${encodeURIComponent(record.id)}/documents`,
        { method: "POST", body: form },
      );
      setMaintenanceRecords((records) => records.map((item) => item.id === uploaded.id ? uploaded : item));
    }
  }

  async function createMaintenanceRecord(entry: MaintenanceRecordInput, documents: File[]): Promise<boolean> {
    setMaintenanceRecordBusy(true);
    setError("");
    try {
      const saved = await api<MaintenanceRecord>("/api/maintenance/records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entry),
      });
      setMaintenanceRecords((current) => [saved, ...current]);
      if (documents.length) {
        try {
          await uploadMaintenanceDocuments(saved, documents);
        } catch (err) {
          setError(`L’intervention est enregistrée, mais un justificatif n’a pas été ajouté : ${err instanceof Error ? err.message : String(err)}`);
        }
      }
      setMaintenanceRecords(await api<MaintenanceRecord[]>(`/api/maintenance/records?vin=${encodeURIComponent(entry.vin)}`));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setMaintenanceRecordBusy(false);
    }
  }

  async function updateMaintenanceRecord(recordId: string, entry: MaintenanceRecordInput): Promise<boolean> {
    setMaintenanceRecordBusy(true);
    setError("");
    try {
      const saved = await api<MaintenanceRecord>(`/api/maintenance/records/${encodeURIComponent(recordId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entry),
      });
      setMaintenanceRecords((current) => current.map((record) => record.id === saved.id ? saved : record));
      setMaintenanceRecords(await api<MaintenanceRecord[]>(`/api/maintenance/records?vin=${encodeURIComponent(entry.vin)}`));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setMaintenanceRecordBusy(false);
    }
  }

  async function setMaintenanceRecommendationStatus(
    recordId: string,
    recommendationIndex: number,
    status: "open" | "completed" | "dismissed",
  ): Promise<boolean> {
    const record = maintenanceRecords.find((item) => item.id === recordId);
    if (!record) return false;
    setMaintenanceRecordBusy(true);
    setError("");
    try {
      await api<MaintenanceRecord>(
        `/api/maintenance/records/${encodeURIComponent(recordId)}/recommendations/${recommendationIndex}?vin=${encodeURIComponent(record.vin)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        },
      );
      setMaintenanceRecords(await api<MaintenanceRecord[]>(`/api/maintenance/records?vin=${encodeURIComponent(record.vin)}`));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setMaintenanceRecordBusy(false);
    }
  }

  async function createMaintenanceProvider(entry: ServiceProviderInput): Promise<ServiceProvider | null> {
    setMaintenanceRecordBusy(true);
    setError("");
    try {
      const saved = await api<ServiceProvider>("/api/maintenance/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entry),
      });
      setMaintenanceProviders((current) => [...current, saved].sort((a, b) => (a.display_name || a.legal_name).localeCompare(b.display_name || b.legal_name, "fr")));
      return saved;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setMaintenanceRecordBusy(false);
    }
  }

  async function updateMaintenanceProvider(providerId: string, entry: ServiceProviderInput): Promise<ServiceProvider | null> {
    setMaintenanceRecordBusy(true);
    setError("");
    try {
      const saved = await api<ServiceProvider>(`/api/maintenance/providers/${encodeURIComponent(providerId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entry),
      });
      setMaintenanceProviders((current) => current.map((provider) => provider.id === saved.id ? saved : provider));
      return saved;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setMaintenanceRecordBusy(false);
    }
  }

  async function addMaintenanceDocuments(recordId: string, documents: File[]) {
    const record = maintenanceRecords.find((item) => item.id === recordId);
    if (!record || !documents.length) return;
    setMaintenanceRecordBusy(true);
    setError("");
    try {
      await uploadMaintenanceDocuments(record, documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setMaintenanceRecordBusy(false);
    }
  }

  async function estimateMaintenanceMileage(vin: string, performedAt: string): Promise<MaintenanceMileageEstimate | null> {
    setError("");
    try {
      const query = new URLSearchParams({ vin, performed_at: performedAt });
      return await api<MaintenanceMileageEstimate>(`/api/maintenance/mileage-estimate?${query.toString()}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  async function analyzeMaintenanceInvoice(vin: string, document: File): Promise<MaintenanceInvoiceAnalysis | null> {
    setError("");
    try {
      const form = new FormData();
      form.append("vin", vin);
      form.append("document", document);
      return await api<MaintenanceInvoiceAnalysis>("/api/maintenance/invoice-draft", {
        method: "POST",
        body: form,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  async function selectDiagnosticVehicle(vin: string) {
    if (!vin || vin === selectedDiagnosticVin) return;
    if (capture?.active) {
      setError("Arrête et sauvegarde la capture avant de changer de véhicule : elle est déjà rattachée au VIN actif.");
      return;
    }
    setVehicleSelectionBusy(true);
    setError("");
    const previousVin = selectedDiagnosticVin;
    setSelectedDiagnosticVin(vin);
    setReport(null);
    setDiagnosticReportHistory([]);
    setObservedDtcs([]);
    setInjectionSnapshot(null);
    setVehicleIdentity(null);
    setReplay(null);
    setReplayValidation(null);
    setReplaySessionId("");
    const profile = diagnosticVehicles.find((vehicle) => vehicle.vin === vin)?.vehicle_profile;
    if (profile) setIdentityProfileKey(profile);
    try {
      await api<DiagnosticVehicle>("/api/diagnostic/vehicles/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vin }),
      });
      await refreshDiagnosticHistory(vin, profile);
    } catch (err) {
      setSelectedDiagnosticVin(previousVin);
      await refreshDiagnosticHistory(previousVin || undefined);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setVehicleSelectionBusy(false);
    }
  }

  async function assignSessionsToActiveVehicle(sessionIds: string[]) {
    if (!selectedDiagnosticVehicle || !sessionIds.length) return;
    setSessionAssignmentBusy(sessionIds.length === 1 ? sessionIds[0] : "bulk");
    setError("");
    try {
      await Promise.all(sessionIds.map((sessionId) => api(`/api/learn/sessions/${encodeURIComponent(sessionId)}/vehicle`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vin: selectedDiagnosticVehicle.vin,
          vehicle_profile: selectedDiagnosticVehicle.vehicle_profile,
          vehicle_label: `${selectedDiagnosticVehicle.manufacturer} ${selectedDiagnosticVehicle.model}`,
        }),
      })));
      await refreshSessions();
      if (replaySessionId && sessionIds.includes(replaySessionId)) await loadReplay(replaySessionId, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSessionAssignmentBusy("");
    }
  }

  async function selectDiagnosticReport(scanId: string) {
    if (!scanId) return;
    setError("");
    try {
      const selected = await api<Report>(`/api/diagnostic/reports/${encodeURIComponent(scanId)}`);
      setReport(selected);
      setDiagnosticRegression(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function verifyDiagnosticRegression(scanId = report?.scan_id) {
    if (!scanId) return;
    setDiagnosticRegressionBusy(true);
    setError("");
    try {
      const result = await api<RegressionResult>(
        `/api/diagnostic/reports/${encodeURIComponent(scanId)}/regression`,
      );
      setDiagnosticRegression(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiagnosticRegressionBusy(false);
    }
  }

  async function importDiagnosticTrace(file: File | undefined) {
    if (!file) return;
    setTraceImportBusy(true);
    setTraceImportResult(null);
    setError("");
    try {
      const content = await file.text();
      const result = await api<TraceImportResult>("/api/diagnostic/traces/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: file.name,
          content,
          vehicle_profile: report?.vehicle_profile ?? identityProfileKey,
          source_format: "auto",
        }),
      });
      setTraceImportResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTraceImportBusy(false);
    }
  }

  async function clearSelectedEcuDtcs(ecuKey: string | undefined = dtcClearEcuKey) {
    if (!ecuKey) return;
    setDtcClearBusy(true);
    setDtcClearResult(null);
    setError("");
    try {
      const result = await api<ClearDtcResult>(
        `/api/diagnostic/ecus/${encodeURIComponent(ecuKey)}/dtcs/clear`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation: dtcClearConfirmation,
            ...dtcClearChecks,
          }),
        },
      );
      setDtcClearResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDtcClearBusy(false);
    }
  }

  async function readDtcSnapshot(ecuKey: string, dtc: DtcValue) {
    const resultKey = `${ecuKey}-${dtc.raw_hex}`;
    setDtcSnapshotBusy(resultKey);
    setError("");
    try {
      const result = await api<DtcSnapshotResult>(
        `/api/diagnostic/ecus/${encodeURIComponent(ecuKey)}/dtcs/snapshot`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dtc_raw_hex: dtc.raw_hex }),
        },
      );
      setDtcSnapshotResults((current) => ({ ...current, [resultKey]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDtcSnapshotBusy("");
    }
  }

  async function sweepSelectedEcuDids(ecuKey: string | undefined = selectedEcu?.key) {
    if (!ecuKey) return;
    const start = parseInt(didSweepStart.trim().replace(/^0x/i, ""), 16);
    const end = parseInt(didSweepEnd.trim().replace(/^0x/i, ""), 16);
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      setError("Les bornes du balayage DID doivent être des valeurs hexadécimales valides.");
      return;
    }
    setDidSweepBusy(true);
    setDidSweepResult(null);
    setError("");
    try {
      const result = await api<DidSweepResult>(
        `/api/diagnostic/ecus/${encodeURIComponent(ecuKey)}/dids/sweep`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ did_start: start, did_end: end }),
        },
      );
      setDidSweepResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDidSweepBusy(false);
    }
  }

  async function readEcuLiveReport(ecuKey: string) {
    setEcuLiveReportBusy(true);
    setError("");
    try {
      const profile = selectedDiagnosticVehicle?.vehicle_profile ?? identityProfileKey;
      const result = await api<Ecu>(
        `/api/diagnostic/ecus/${encodeURIComponent(ecuKey)}/report?vehicle_profile=${encodeURIComponent(profile)}`,
        { method: "POST" },
      );
      setEcuLiveReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setEcuLiveReportBusy(false);
    }
  }

  async function resetSelectedEcu(ecuKey: string) {
    setEcuResetBusy(true);
    setEcuResetResult(null);
    setError("");
    try {
      const result = await api<EcuResetResult>(`/api/diagnostic/psa/ecus/${encodeURIComponent(ecuKey)}/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmation: ecuResetConfirmation,
          ...effectivePsaLabChecks,
        }),
      });
      setEcuResetResult(result);
      setEcuResetConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setEcuResetBusy(false);
    }
  }

  async function scan() {
    if (capture?.active && !dualCanOperational) {
      setError("Arrête et sauvegarde la capture CAN avant de lancer l’inventaire UDS.");
      return;
    }
    if (!status?.can_tx_enabled) {
      setError("Les requêtes de lecture CAN sont verrouillées dans la configuration actuelle.");
      return;
    }
    if (!diagnosticGatewayVerified) {
      setError("Connecte et valide d’abord l’ESP32 diagnostic depuis le Dashboard direct.");
      setView("studio");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const vehicle = diagnosticVehicles.find((candidate) => candidate.vin === selectedDiagnosticVin);
      const payload = await api<Report>("/api/diagnostic/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vehicle_profile: vehicle?.vehicle_profile ?? identityProfileKey ?? status?.vehicle_profile,
          vin: selectedDiagnosticVin || null,
          extended_probe: extendedProbeEnabled,
        }),
      });
      setReport(payload);
      setDiagnosticRegression(null);
      if (payload.vin) setSelectedDiagnosticVin(payload.vin);
      await refreshDiagnosticHistory(payload.vin ?? undefined, payload.vehicle_profile);
      if (payload.scan_id) await verifyDiagnosticRegression(payload.scan_id);
      setView("ecus");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function readInjectionParameters(destination: View = "injection") {
    if (capture?.active && !dualCanOperational) {
      setError("Arrête et sauvegarde la capture CAN avant de lire les paramètres d’injection.");
      return;
    }
    if (!status?.can_tx_enabled) {
      setError("Les lectures OBD-II sont verrouillées dans la configuration actuelle.");
      return;
    }
    if (!diagnosticGatewayVerified) {
      setError("Connecte et valide d’abord l’ESP32 diagnostic depuis le Dashboard direct.");
      setView("studio");
      return;
    }
    if (!liveObdReadOnly) {
      setError("Le firmware principal doit annoncer live_obd_read_only=true pour autoriser les lectures OBD normalisées sur 6/14.");
      setView("studio");
      return;
    }
    setInjectionBusy(true);
    setError("");
    try {
      const profile = selectedDiagnosticVehicle?.vehicle_profile ?? identityProfileKey ?? status?.vehicle_profile;
      const query = profile ? `?vehicle_profile=${encodeURIComponent(profile)}` : "";
      const payload = await api<DiagnosticSensorSnapshot>(`/api/sensors/snapshot${query}`, { method: "POST" });
      setInjectionSnapshot(payload);
      setView(destination);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInjectionBusy(false);
    }
  }

  async function readVehicleIdentity() {
    if (capture?.active) {
      setError("Arrête et sauvegarde la capture CAN avant de lire l’identité du véhicule.");
      return;
    }
    if (!selectedIdentityProfile) {
      setError("Sélectionne d’abord un profil véhicule à identifier.");
      return;
    }
    if (!status?.can_tx_enabled) {
      setError("La lecture VIN nécessite des requêtes OBD/UDS de lecture (CAN_TX_ENABLED=true).");
      return;
    }
    setIdentityBusy(true);
    setError("");
    try {
      let readyStatus = status;
      if (status.transport !== "virtual") {
        const announcedBitrateValue = status.gateway_hello?.live_bitrate ?? status.gateway_hello?.bitrate;
        const announcedBitrate = typeof announcedBitrateValue === "number"
          ? announcedBitrateValue
          : Number(announcedBitrateValue);
        const bitrateMismatch = Boolean(
          selectedIdentityProfile.can_bitrate
          && (!Number.isFinite(announcedBitrate) || announcedBitrate !== selectedIdentityProfile.can_bitrate),
        );
        const capabilityMissing = identityRequiresLiveObd && !liveObdReadOnly;
        const mustConnect = !status.gateway_verified || bitrateMismatch || capabilityMissing;
        if (mustConnect) {
          const option = transportCatalog?.options.find((candidate) => candidate.id === selectedTransportId)
            ?? transportCatalog?.options.find((candidate) => candidate.id === transportCatalog.current_id)
            ?? transportCatalog?.options.find((candidate) => candidate.detected)
            ?? (status.gateway_endpoint && (status.transport === "esp32_serial" || status.transport === "esp32_wifi")
              ? {
                  id: `${status.transport}:${status.gateway_endpoint}`,
                  transport: status.transport,
                  endpoint: status.gateway_endpoint,
                  baud: null,
                  label: status.gateway_endpoint,
                }
              : null);
          if (!option) {
            throw new Error("Aucune passerelle ESP32 détectée. Branche-la en USB puis relance la lecture.");
          }
          setTransportConnectBusy(true);
          setTransportMessage("Connexion et réglage du CAN…");
          const connection = await api<TransportConnection>("/api/system/transport/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              transport: option.transport,
              endpoint: option.endpoint,
              baud: option.baud ?? null,
              vehicle_profile: selectedIdentityProfile.key,
            }),
          });
          readyStatus = await api<Status>("/api/system/status");
          setStatus(readyStatus);
          setStatusError("");
          setTransportMessage(connection.verified ? "ESP32 validé pour ce véhicule" : "Connexion non validée");
          await refreshTransportCatalog();
          if (!connection.verified) {
            throw new Error(connection.error || "La passerelle ESP32 n’a pas pu être validée.");
          }
        }
      }
      if (
        readyStatus.transport !== "virtual"
        && identityRequiresLiveObd
        && readyStatus.gateway_hello?.live_obd_read_only !== true
      ) {
        throw new Error(
          "Le firmware principal doit autoriser les lectures OBD filtrées sur les broches 6/14.",
        );
      }
      const result = await api<VehicleIdentityResult>("/api/diagnostic/identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vehicle_profile: identityProfileKey }),
      });
      setVehicleIdentity(result);
      if (result.vin) {
        setSelectedDiagnosticVin(result.vin);
        await refreshDiagnosticHistory(result.vin, result.vehicle_profile);
      }
      setView("identity");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTransportConnectBusy(false);
      setIdentityBusy(false);
    }
  }

  async function createManualVehicle(vin: string) {
    if (capture?.active) {
      setError("Arrête et sauvegarde la capture CAN avant d’ajouter un véhicule.");
      return;
    }
    if (!selectedIdentityProfile) {
      setError("Sélectionne d’abord le profil du véhicule.");
      return;
    }
    setManualVehicleBusy(true);
    setError("");
    try {
      const result = await api<VehicleIdentityResult>("/api/diagnostic/vehicles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vehicle_profile: selectedIdentityProfile.key,
          vin: vin.trim().toUpperCase(),
        }),
      });
      setVehicleIdentity(result);
      setSelectedDiagnosticVin(result.vin ?? "");
      await refreshDiagnosticHistory(result.vin ?? undefined, result.vehicle_profile);
      setView("identity");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setManualVehicleBusy(false);
    }
  }

  function beginVehicleIdentityCreation() {
    if (capture?.active) {
      setError("Arrête et sauvegarde la capture CAN avant d’ajouter un véhicule.");
      return;
    }
    setSelectedDiagnosticVin("");
    setVehicleIdentity(null);
    setInjectionSnapshot(null);
    setReport(null);
    setObdDtcResult(null);
    setError("");
    setView("identity");
  }

  async function readEngineObdDtcs() {
    setObdDtcBusy(true);
    setError("");
    try {
      const result = await api<Ecu>(
        `/api/diagnostic/obd/dtcs?ecu_key=engine&vehicle_profile=${encodeURIComponent(identityProfileKey)}`,
        { method: "POST" },
      );
      setObdDtcResult(result);
    } catch (err) {
      setObdDtcResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setObdDtcBusy(false);
    }
  }

  async function testUdsPresence() {
    setUdsProbeBusy(true);
    setUdsProbeResult(null);
    setError("");
    try {
      const result = await api<DidValue>(
        `/api/diagnostic/ecus/${encodeURIComponent(udsProbeEcuKey)}/dids/0xF186?vehicle_profile=${encodeURIComponent(identityProfileKey)}`,
        { method: "POST" },
      );
      setUdsProbeResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUdsProbeBusy(false);
    }
  }

  async function readPsaDid() {
    if (!psaVehicleCompatible) {
      setError("Le véhicule actif n’est pas un profil PSA compatible. Charge la Peugeot depuis le Garage avant toute lecture constructeur.");
      setView("garage");
      return;
    }
    if (!diagnosticReady) {
      setError(capture?.active && !dualCanOperational
        ? "Arrête et sauvegarde la capture avant une lecture UDS PSA."
        : "Connecte un firmware diagnostic compatible et active les requêtes CAN en lecture.");
      return;
    }
    const normalizedDid = psaDid.trim().replace(/^0x/i, "");
    if (!/^[0-9a-fA-F]{1,4}$/.test(normalizedDid)) {
      setError("Le DID PSA doit contenir de 1 à 4 chiffres hexadécimaux.");
      return;
    }
    setPsaBusy("did");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<DidValue>(`/api/diagnostic/psa/ecus/${encodeURIComponent(psaEcuKey)}/dids/0x${normalizedDid}`, { method: "POST" });
      setPsaDidResult(result);
      setPsaFeedback(`Zone 0x${normalizedDid.toUpperCase().padStart(4, "0")} reçue depuis ${selectedPsaEcu?.name ?? psaEcuKey}.`);
    } catch (err) {
      setPsaDidResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function calculatePsaSeedKey() {
    setPsaBusy("seed");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<PsaSeedKeyResult>("/api/diagnostic/psa/seed-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed_hex: psaSeed.trim(), application_key_hex: psaApplicationKey.trim() }),
      });
      setPsaSeedResult(result);
      setPsaFeedback("Clé calculée localement : aucune trame n'a été envoyée au véhicule.");
    } catch (err) {
      setPsaSeedResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function unlockPsaConfiguration() {
    if (!psaVehicleCompatible) {
      setError("SecurityAccess PSA refusé : le véhicule actif n’est pas un profil PSA compatible.");
      setView("garage");
      return;
    }
    setPsaBusy("unlock");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<PsaUnlockResult>(`/api/diagnostic/psa/ecus/${encodeURIComponent(psaUnlockEcuKey)}/unlock`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          application_key_hex: psaUnlockApplicationKey.trim(),
          confirmation: psaUnlockConfirmation,
          ...effectivePsaLabChecks,
        }),
      });
      setPsaFeedback(`${result.message} Seed ${result.seed_hex} · key ${result.response_key_hex}.`);
      setPsaUnlockConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function executePsaAction() {
    if (!psaVehicleCompatible) {
      setError("Commande PSA refusée : charge d’abord un véhicule PSA compatible depuis le Garage.");
      setView("garage");
      return;
    }
    if (!selectedPsaAction) return;
    setPsaBusy("action");
    setPsaFeedback("");
    setError("");
    try {
      const result = await api<PsaActionResult>(`/api/diagnostic/psa/actions/${encodeURIComponent(selectedPsaAction.key)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmation: psaConfirmation,
          duration_ms: psaDurationMs,
          ...effectivePsaLabChecks,
        }),
      });
      setPsaFeedback(`${result.message}${result.session_id ? ` Trace ${result.session_id}.` : ""}`);
      setPsaConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPsaBusy("");
    }
  }

  async function startCapture(enableLiveDataReads = true) {
    if (transportConnectBusy) return;
    setError("");
    try {
      const endpoint = enableLiveDataReads ? "/api/live-data/start" : "/api/learn/capture/start";
      const payload = await api<CaptureStatus>(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: captureName,
          note: captureNote || null,
          vin: selectedDiagnosticVehicle?.vin ?? null,
          vehicle_profile: activeCommunicationProfileKey || status?.vehicle_profile || null,
          vehicle_label: activeCommunicationProfile
            ? `${activeCommunicationProfile.manufacturer} ${activeCommunicationProfile.model}`
            : null,
        }),
      });
      setCapture(payload);
      setAnalysis(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function stopCapture() {
    setError("");
    try {
      const payload = await api<CaptureStatus>("/api/learn/capture/stop", { method: "POST" });
      setCapture(payload);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function addMarker(name = markerName) {
    if (!name.trim()) return;
    setError("");
    try {
      const payload = await api<CaptureStatus>("/api/learn/capture/marker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), note: markerNote || null }),
      });
      setCapture(payload);
      setMarkerName(name.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function analyzeSession(sessionId: string, saved = false) {
    setAnalysisBusy(sessionId);
    setError("");
    try {
      const path = saved
        ? `/api/learn/correlations/${sessionId}`
        : `/api/learn/correlate/${sessionId}`;
      const payload = await api<BehavioralAnalysis>(path, saved ? undefined : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          before_ms: 1200,
          after_ms: 1200,
          min_samples: 3,
          max_candidates_per_marker: 40,
        }),
      });
      setAnalysis(payload);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalysisBusy("");
    }
  }

  function renderReplay() {
    return (
      <ReplayScreen
        sessions={sessions}
        selectedDiagnosticVin={selectedDiagnosticVin}
        replay={replay}
        replaySessionId={replaySessionId}
        replayBusy={replayBusy}
        loadReplay={loadReplay}
        activeVehicleLabel={activeVehicleLabel}
        setView={setView}
        currentReplayPoint={currentReplayPoint}
        currentRouteGeometry={currentRouteGeometry}
        currentReplayIndex={currentReplayIndex}
        replayTimeMs={replayTimeMs}
        selectedReplayGaugeKeys={selectedReplayGaugeKeys}
        selectedReplayGraphKeys={selectedReplayGraphKeys}
        selectedReplayIndicatorKeys={selectedReplayIndicatorKeys}
        replayValidation={replayValidation}
        selectedDiagnosticVehicle={selectedDiagnosticVehicle}
        sessionAssignmentBusy={sessionAssignmentBusy}
        assignSessionsToActiveVehicle={assignSessionsToActiveVehicle}
        setSignalManualValidation={setSignalManualValidation}
        clearSignalManualValidation={clearSignalManualValidation}
        signalValidationBusy={signalValidationBusy}
        replayIndicatorToAdd={replayIndicatorToAdd}
        setReplayIndicatorToAdd={setReplayIndicatorToAdd}
        addReplayIndicator={addReplayIndicator}
        setSelectedReplayIndicatorKeys={setSelectedReplayIndicatorKeys}
        removeReplayIndicator={removeReplayIndicator}
        replayGaugeToAdd={replayGaugeToAdd}
        setReplayGaugeToAdd={setReplayGaugeToAdd}
        addReplayGauge={addReplayGauge}
        setSelectedReplayGaugeKeys={setSelectedReplayGaugeKeys}
        removeReplayGauge={removeReplayGauge}
        replayGraphToAdd={replayGraphToAdd}
        setReplayGraphToAdd={setReplayGraphToAdd}
        addReplayGraph={addReplayGraph}
        setSelectedReplayGraphKeys={setSelectedReplayGraphKeys}
        currentReplayGraphGeometries={currentReplayGraphGeometries}
        removeReplayGraph={removeReplayGraph}
        seekReplay={seekReplay}
        setReplayPlaying={setReplayPlaying}
        replayPlaying={replayPlaying}
        replayRate={replayRate}
        setReplayRate={setReplayRate}
      />
    );
  }

  function renderStudio() {
    return (
      <StudioScreen
        studioLiveSample={studioLiveSample}
        capture={capture}
        captureName={captureName}
        setCaptureName={setCaptureName}
        transportConnectBusy={transportConnectBusy}
        stopCapture={stopCapture}
        startCapture={startCapture}
        directPsaCompatible={directPsaCompatible}
        activeVehicleLabel={activeVehicleLabel}
        activeIsFiat500={activeIsFiat500}
        activeVehicleVisual={activeVehicleVisual}
        passiveSensors={passiveSensors}
        studioGraphGeometries={studioGraphGeometries}
        setStudioGraphWindow={setStudioGraphWindow}
        setView={setView}
        activeCommunicationProfile={activeCommunicationProfile}
        selectedDiagnosticVehicle={selectedDiagnosticVehicle}
        activeCommunicationProfileKey={activeCommunicationProfileKey}
        status={status}
        selectedTransportId={selectedTransportId}
        setSelectedTransportId={setSelectedTransportId}
        setTransportMessage={setTransportMessage}
        transportCatalog={transportCatalog}
        connectSelectedTransport={connectSelectedTransport}
        transportMessage={transportMessage}
        studioWidgetToAdd={studioWidgetToAdd}
        setStudioWidgetToAdd={setStudioWidgetToAdd}
        addStudioWidget={addStudioWidget}
        diagnosticReady={diagnosticReady}
        setError={setError}
        studioEditing={studioEditing}
        setStudioEditing={setStudioEditing}
        setStudioWidgets={setStudioWidgets}
        toggleStudioFullscreen={toggleStudioFullscreen}
        error={error}
        studioBoardRef={studioBoardRef}
        studioWidgets={studioWidgets}
        beginStudioInteraction={beginStudioInteraction}
        setStudioSensorStyle={setStudioSensorStyle}
        resizeStudioWidget={resizeStudioWidget}
        removeStudioWidget={removeStudioWidget}
      />
    );
  }

  function renderGarage() {
    return (
      <GarageScreen
        vehicleLinkedSessions={vehicleLinkedSessions}
        vehicleTimeline={vehicleTimeline}
        report={report}
        eventFilter={garageEventFilter}
        selectedVehicle={selectedDiagnosticVehicle}
        diagnosticVehicles={diagnosticVehicles}
        sessions={sessions}
        selectedVin={selectedDiagnosticVin}
        vehicleSelectionBusy={vehicleSelectionBusy}
        capture={capture}
        unassignedSessions={unassignedSessions}
        activeVehicleLabel={activeVehicleLabel}
        sessionAssignmentBusy={sessionAssignmentBusy}
        formatIsoDate={formatIsoDate}
        formatDuration={formatDuration}
        formatDate={formatDate}
        onSelectReport={selectDiagnosticReport}
        onLoadReplay={loadReplay}
        onSelectIdentityProfile={setIdentityProfileKey}
        onAddVehicle={beginVehicleIdentityCreation}
        onNavigate={setView}
        onSelectVehicle={selectDiagnosticVehicle}
        onFilterChange={setGarageEventFilter}
        onAssignSessions={assignSessionsToActiveVehicle}
      />
    );
  }

  function renderDashboard() {
    return (
      <DashboardScreen
        status={status}
        statusError={statusError}
        selectedVehicle={selectedDiagnosticVehicle}
        diagnosticVehicles={diagnosticVehicles}
        vehicleSelectionBusy={vehicleSelectionBusy}
        report={report}
        detectedEcuCount={detectedEcus.length}
        dtcCount={dtcCount}
        capture={capture}
        diagnosticReady={diagnosticReady}
        maintenanceRecords={maintenanceRecords}
        liveOdometerKm={passiveSensors?.active ? studioLiveSample?.point.odometer_km ?? null : null}
        onSelectVehicle={selectDiagnosticVehicle}
        onAddMaintenance={(eventType) => {
          setMaintenanceCreateIntent({ key: Date.now(), eventType });
          setView("maintenance");
        }}
        onNavigate={setView}
      />
    );
  }

  function renderSensors() {
    return (
      <SensorsScreen
        startFullSensorDetection={startFullSensorDetection}
        detectionBusy={detectionBusy}
        detectionRemaining={detectionRemaining}
        passiveSensors={passiveSensors}
        liveObdReadOnly={liveObdReadOnly}
        createLiveSensor={createLiveSensor}
        selectedDiagnosticVin={selectedDiagnosticVin}
        refreshPassiveSensors={refreshPassiveSensors}
        sensorCategories={sensorCategories}
        sensorCategory={sensorCategory}
        setSensorCategory={setSensorCategory}
        sensorSearch={sensorSearch}
        setSensorSearch={setSensorSearch}
        setView={setView}
        visiblePassiveSignals={visiblePassiveSignals}
        editLiveSensor={editLiveSensor}
        editPassiveSensor={editPassiveSensor}
        sensorEditor={sensorEditor}
        setSensorEditor={setSensorEditor}
        savePassiveSensorOverride={savePassiveSensorOverride}
        resetPassiveSensorOverride={resetPassiveSensorOverride}
        sensorEditorBusy={sensorEditorBusy}
        liveSensorEditor={liveSensorEditor}
        setLiveSensorEditor={setLiveSensorEditor}
        saveLiveSensor={saveLiveSensor}
        archiveLiveSensor={archiveLiveSensor}
        liveSensorEditorBusy={liveSensorEditorBusy}
      />
    );
  }

  function renderSensorInventory() {
    return (
      <SensorInventoryScreen
        sensorInventoryRows={sensorInventoryRows}
        inventoryCounts={inventoryCounts}
        injectionBusy={injectionBusy}
        obdReadReady={obdReadReady}
        setValidationFocusId={setValidationFocusId}
        readInjectionParameters={readInjectionParameters}
        detectionBusy={detectionBusy}
        detectionRemaining={detectionRemaining}
        startFullSensorDetection={startFullSensorDetection}
        setView={setView}
        focusedValidationRow={focusedValidationRow}
        validationQueue={validationQueue}
        activeIsFiat500={activeIsFiat500}
        activeVehicleLabel={activeVehicleLabel}
        effectivePowertrainProfile={effectivePowertrainProfile}
        setPowertrainProfile={setPowertrainProfile}
        powertrainProfile={powertrainProfile}
        inventoryStatus={inventoryStatus}
        setInventoryStatus={setInventoryStatus}
        inventorySystems={inventorySystems}
        visibleInventoryRows={visibleInventoryRows}
        inventoryPriorityOnly={inventoryPriorityOnly}
        setInventoryPriorityOnly={setInventoryPriorityOnly}
        inventorySystem={inventorySystem}
        setInventorySystem={setInventorySystem}
        inventorySearch={inventorySearch}
        setInventorySearch={setInventorySearch}
      />
    );
  }

  function renderVehicleIdentity() {
    return (
      <VehicleIdentityScreen
        vehicleIdentity={vehicleIdentity}
        identityProfileKey={identityProfileKey}
        identityReadReady={identityReadReady}
        capture={capture}
        selectedIdentityProfile={selectedIdentityProfile}
        vehicleProfiles={vehicleProfiles}
        setIdentityProfileKey={setIdentityProfileKey}
        setSelectedDiagnosticVin={setSelectedDiagnosticVin}
        setVehicleIdentity={setVehicleIdentity}
        setInjectionSnapshot={setInjectionSnapshot}
        setReport={setReport}
        setError={setError}
        vehicleManufacturers={vehicleManufacturers}
        profilesForSelectedManufacturer={profilesForSelectedManufacturer}
        readVehicleIdentity={readVehicleIdentity}
        identityBusy={identityBusy}
        createManualVehicle={createManualVehicle}
        manualVehicleBusy={manualVehicleBusy}
        status={status}
        readEngineObdDtcs={readEngineObdDtcs}
        obdDtcBusy={obdDtcBusy}
        obdDtcResult={obdDtcResult}
        udsProbeEcuKey={udsProbeEcuKey}
        setUdsProbeEcuKey={setUdsProbeEcuKey}
        setUdsProbeResult={setUdsProbeResult}
        testUdsPresence={testUdsPresence}
        udsProbeBusy={udsProbeBusy}
        udsProbeResult={udsProbeResult}
      />
    );
  }

  function renderInjection() {
    return (
      <InjectionScreen
        diagnosticSensorCatalog={diagnosticSensorCatalog}
        injectionSnapshot={injectionSnapshot}
        obdReadReady={obdReadReady}
        capture={capture}
        status={status}
        diagnosticGatewayVerified={diagnosticGatewayVerified}
        readInjectionParameters={readInjectionParameters}
        injectionBusy={injectionBusy}
        dualCanOperational={dualCanOperational}
        injectionGroups={injectionGroups}
        injectionValues={injectionValues}
        setView={setView}
        psaCatalog={psaCatalog}
        liveSafetyEvidence={liveSafetyEvidence}
        effectivePsaLabChecks={effectivePsaLabChecks}
        setPsaLabChecks={setPsaLabChecks}
        ecuResetConfirmation={ecuResetConfirmation}
        setEcuResetConfirmation={setEcuResetConfirmation}
        resetSelectedEcu={resetSelectedEcu}
        psaVehicleCompatible={psaVehicleCompatible}
        diagnosticReady={diagnosticReady}
        psaLabChecksComplete={psaLabChecksComplete}
        ecuResetBusy={ecuResetBusy}
        ecuResetResult={ecuResetResult}
        dtcClearChecks={dtcClearChecks}
        setDtcClearChecks={setDtcClearChecks}
        dtcClearConfirmation={dtcClearConfirmation}
        setDtcClearConfirmation={setDtcClearConfirmation}
        clearSelectedEcuDtcs={clearSelectedEcuDtcs}
        dtcClearBusy={dtcClearBusy}
        dtcClearResult={dtcClearResult}
        report={report}
        engineDtcs={engineDtcs}
      />
    );
  }

  function renderEcuLive(ecuKey: EcuLiveView) {
    return (
      <EcuLiveScreen
        ecuKey={ecuKey}
        psaCatalog={psaCatalog}
        report={report}
        ecuLiveReport={ecuLiveReport}
        passiveSensors={passiveSensors}
        psaVehicleCompatible={psaVehicleCompatible}
        diagnosticReady={diagnosticReady}
        psaLabChecks={psaLabChecks}
        setPsaLabChecks={setPsaLabChecks}
        ecuWatchValues={ecuWatchValues}
        readEcuLiveReport={readEcuLiveReport}
        ecuLiveReportBusy={ecuLiveReportBusy}
        setView={setView}
        didSweepStart={didSweepStart}
        setDidSweepStart={setDidSweepStart}
        didSweepEnd={didSweepEnd}
        setDidSweepEnd={setDidSweepEnd}
        sweepSelectedEcuDids={sweepSelectedEcuDids}
        didSweepBusy={didSweepBusy}
        didSweepResult={didSweepResult}
        liveSafetyEvidence={liveSafetyEvidence}
        effectivePsaLabChecks={effectivePsaLabChecks}
        ecuResetConfirmation={ecuResetConfirmation}
        setEcuResetConfirmation={setEcuResetConfirmation}
        resetSelectedEcu={resetSelectedEcu}
        psaLabChecksComplete={psaLabChecksComplete}
        ecuResetBusy={ecuResetBusy}
        ecuResetResult={ecuResetResult}
        status={status}
        dtcClearChecks={dtcClearChecks}
        setDtcClearChecks={setDtcClearChecks}
        dtcClearConfirmation={dtcClearConfirmation}
        setDtcClearConfirmation={setDtcClearConfirmation}
        clearSelectedEcuDtcs={clearSelectedEcuDtcs}
        dtcClearBusy={dtcClearBusy}
        dtcClearResult={dtcClearResult}
      />
    );
  }

  function renderMaintenance() {
    return (
      <MaintenanceScreen
        catalog={maintenanceCatalog}
        categories={maintenanceCategories}
        selectedCategory={maintenanceCategory}
        services={visibleMaintenanceServices}
        onCategoryChange={setMaintenanceCategory}
        onUnavailableProcedure={() => setError("L’exécuteur de cette procédure n’est pas encore installé.")}
        oilLog={oilLog}
        liveOdometerKm={passiveSensors?.active ? studioLiveSample?.point.odometer_km ?? null : null}
        onRecordOilLogEntry={recordOilLogEntry}
        oilLogBusy={oilLogBusy}
        vehicle={selectedDiagnosticVehicle}
        maintenanceRecords={maintenanceRecords}
        maintenanceProviders={maintenanceProviders}
        maintenanceRecordBusy={maintenanceRecordBusy}
        onCreateMaintenanceRecord={createMaintenanceRecord}
        onUpdateMaintenanceRecord={updateMaintenanceRecord}
        onSetMaintenanceRecommendationStatus={setMaintenanceRecommendationStatus}
        onCreateMaintenanceProvider={createMaintenanceProvider}
        onUpdateMaintenanceProvider={updateMaintenanceProvider}
        onAddMaintenanceDocuments={addMaintenanceDocuments}
        onEstimateMaintenanceMileage={estimateMaintenanceMileage}
        onAnalyzeMaintenanceInvoice={analyzeMaintenanceInvoice}
        createIntent={maintenanceCreateIntent}
      />
    );
  }

  function renderPsaAdvanced() {
    return (
      <PsaAdvancedScreen
        status={status}
        psaCatalog={psaCatalog}
        diagnosticReady={diagnosticReady}
        psaVehicleCompatible={psaVehicleCompatible}
        diagnosticGatewayVerified={diagnosticGatewayVerified}
        psaLabChecksComplete={psaLabChecksComplete}
        psaLabChecks={psaLabChecks}
        setPsaLabChecks={setPsaLabChecks}
        psaSection={psaSection}
        setPsaSection={setPsaSection}
        psaEcuKey={psaEcuKey}
        setPsaEcuKey={setPsaEcuKey}
        setPsaDidResult={setPsaDidResult}
        psaDid={psaDid}
        setPsaDid={setPsaDid}
        readPsaDid={readPsaDid}
        psaBusy={psaBusy}
        selectedPsaEcu={selectedPsaEcu}
        psaDidResult={psaDidResult}
        psaSeed={psaSeed}
        setPsaSeed={setPsaSeed}
        psaApplicationKey={psaApplicationKey}
        setPsaApplicationKey={setPsaApplicationKey}
        calculatePsaSeedKey={calculatePsaSeedKey}
        psaSeedResult={psaSeedResult}
        setPsaSeedResult={setPsaSeedResult}
        effectivePsaLabChecks={effectivePsaLabChecks}
        liveSafetyEvidence={liveSafetyEvidence}
        passiveSensors={passiveSensors}
        psaSelectedActionKey={psaSelectedActionKey}
        setPsaSelectedActionKey={setPsaSelectedActionKey}
        setPsaConfirmation={setPsaConfirmation}
        setPsaFeedback={setPsaFeedback}
        selectedPsaAction={selectedPsaAction}
        psaDurationMs={psaDurationMs}
        setPsaDurationMs={setPsaDurationMs}
        psaConfirmation={psaConfirmation}
        executePsaAction={executePsaAction}
        psaUnlockEcuKey={psaUnlockEcuKey}
        setPsaUnlockEcuKey={setPsaUnlockEcuKey}
        setPsaUnlockApplicationKey={setPsaUnlockApplicationKey}
        setPsaUnlockConfirmation={setPsaUnlockConfirmation}
        psaUnlockApplicationKey={psaUnlockApplicationKey}
        psaUnlockEcu={psaUnlockEcu}
        psaUnlockConfirmation={psaUnlockConfirmation}
        unlockPsaConfiguration={unlockPsaConfiguration}
        psaFeedback={psaFeedback}
      />
    );
  }

  function renderEcus() {
    return (
      <EcusScreen
        startFullSensorDetection={startFullSensorDetection}
        detectionBusy={detectionBusy}
        detectionRemaining={detectionRemaining}
        passiveSubsystems={passiveSubsystems}
        diagnosticReady={diagnosticReady}
        dualCanOperational={dualCanOperational}
        capture={capture}
        status={status}
        diagnosticGatewayVerified={diagnosticGatewayVerified}
        liveObdReadOnly={liveObdReadOnly}
        scan={scan}
        busy={busy}
        report={report}
        detectedEcus={detectedEcus}
        verifyDiagnosticRegression={verifyDiagnosticRegression}
        diagnosticRegressionBusy={diagnosticRegressionBusy}
        diagnosticRegression={diagnosticRegression}
        selectedEcu={selectedEcu}
        setSelectedEcuKey={setSelectedEcuKey}
        openPassiveSensors={openPassiveSensors}
        setView={setView}
        didSweepStart={didSweepStart}
        setDidSweepStart={setDidSweepStart}
        didSweepEnd={didSweepEnd}
        setDidSweepEnd={setDidSweepEnd}
        sweepSelectedEcuDids={sweepSelectedEcuDids}
        didSweepBusy={didSweepBusy}
        didSweepResult={didSweepResult}
        dtcClearEcuKey={dtcClearEcuKey}
        setDtcClearEcuKey={setDtcClearEcuKey}
        setDtcClearConfirmation={setDtcClearConfirmation}
        setDtcClearResult={setDtcClearResult}
        dtcClearChecks={dtcClearChecks}
        setDtcClearChecks={setDtcClearChecks}
        dtcClearConfirmation={dtcClearConfirmation}
        clearSelectedEcuDtcs={clearSelectedEcuDtcs}
        dtcClearBusy={dtcClearBusy}
        dtcClearResult={dtcClearResult}
      />
    );
  }

  function renderDtcs() {
    return (
      <DtcsScreen
        report={report}
        refreshDiagnosticHistory={refreshDiagnosticHistory}
        selectedDiagnosticVin={selectedDiagnosticVin}
        selectDiagnosticVehicle={selectDiagnosticVehicle}
        diagnosticVehicles={diagnosticVehicles}
        selectDiagnosticReport={selectDiagnosticReport}
        diagnosticReportHistory={diagnosticReportHistory}
        selectedDiagnosticVehicle={selectedDiagnosticVehicle}
        observedDtcs={observedDtcs}
        extendedProbeEnabled={extendedProbeEnabled}
        setExtendedProbeEnabled={setExtendedProbeEnabled}
        scan={scan}
        busy={busy}
        diagnosticReady={diagnosticReady}
        capture={capture}
        status={status}
        dtcFilter={dtcFilter}
        setDtcFilter={setDtcFilter}
        detectedEcus={detectedEcus}
        visibleDtcs={visibleDtcs}
        dtcSnapshotResults={dtcSnapshotResults}
        readDtcSnapshot={readDtcSnapshot}
        dtcSnapshotBusy={dtcSnapshotBusy}
      />
    );
  }

  function candidateLocation(candidate: SignalCandidate) {
    const parts = [hexadecimal(candidate.arbitration_id)];
    if (candidate.dbc_message) parts.push(candidate.dbc_message);
    if (candidate.dbc_signal) parts.push(candidate.dbc_signal);
    if (candidate.byte_index !== null && candidate.byte_index !== undefined) parts.push(`octet ${candidate.byte_index}`);
    if (candidate.bit_index !== null && candidate.bit_index !== undefined) parts.push(`bit ${candidate.bit_index}`);
    return parts.join(" · ");
  }

  function renderDatabase() {
    return (
      <DatabaseScreen
        report={report}
        vehicleProfiles={vehicleProfiles}
        detectedEcus={detectedEcus}
        diagnosticSensorCatalog={diagnosticSensorCatalog}
        liveSensorDefinitions={liveSensorDefinitions}
        maintenanceCatalog={maintenanceCatalog}
        onNavigate={setView}
        onOpenPassiveSensors={openPassiveSensors}
      />
    );
  }

  function renderSecurity() {
    return (
      <SecurityScreen
        operatingMode={operatingMode}
        status={status}
        modeSwitchBusy={modeSwitchBusy}
        labMode={LAB_MODE}
        onActivateReadOnly={activateReadOnlyMode}
        onOpenMaintenanceDialog={openMaintenanceModeDialog}
        onNavigate={setView}
      />
    );
  }

  function renderAnalysis() {
    return (
      <AnalysisScreen
        analysis={analysis}
        onAnalyze={analyzeSession}
        formatDuration={formatDuration}
        formatHexadecimal={hexadecimal}
        candidateLocation={candidateLocation}
      />
    );
  }

  function renderDiscovery() {
    return (
      <DiscoveryScreen
        traceImportBusy={traceImportBusy}
        importDiagnosticTrace={importDiagnosticTrace}
        traceImportResult={traceImportResult}
        capture={capture}
        captureName={captureName}
        setCaptureName={setCaptureName}
        captureNote={captureNote}
        setCaptureNote={setCaptureNote}
        captureGpsEnabled={captureGpsEnabled}
        setCaptureGpsEnabled={setCaptureGpsEnabled}
        startCapture={startCapture}
        gpsTracking={gpsTracking}
        liveObdReadOnly={liveObdReadOnly}
        markerName={markerName}
        setMarkerName={setMarkerName}
        markerNote={markerNote}
        setMarkerNote={setMarkerNote}
        addMarker={addMarker}
        markerPresets={markerPresets}
        stopCapture={stopCapture}
        opendbcCatalog={opendbcCatalog}
        refreshSessions={refreshSessions}
        sessions={sessions}
        analysisBusy={analysisBusy}
        analyzeSession={analyzeSession}
        analysisContent={renderAnalysis()}
      />
    );
  }

  if (view === "studio") return renderStudio();

  return (
    <AppLayout
      view={view}
      openNavModule={openNavModule}
      setOpenNavModule={setOpenNavModule}
      status={status}
      error={error}
      diagnosticVehicles={diagnosticVehicles}
      selectedDiagnosticVin={selectedDiagnosticVin}
      vehicleSelectionBusy={vehicleSelectionBusy}
      captureActive={Boolean(capture?.active)}
      detectedEcuCount={report ? detectedEcus.length : undefined}
      dtcCount={dtcCount || undefined}
      validationQueueCount={validationQueue.length || undefined}
      activeTitle={activeTitle}
      onNavigate={setView}
      onClearError={() => setError("")}
      onOpenPassiveSensors={openPassiveSensors}
      onSelectVehicle={selectDiagnosticVehicle}
      onOpenMaintenanceModeDialog={openMaintenanceModeDialog}
      modal={(
        <MaintenanceModeDialog
          open={modeDialogOpen}
          operatingMode={operatingMode}
          selectedVin={selectedDiagnosticVin}
          checks={modeChecks}
          setChecks={setModeChecks}
          confirmation={modeConfirmation}
          setConfirmation={setModeConfirmation}
          busy={modeSwitchBusy}
          onClose={() => setModeDialogOpen(false)}
          onSubmit={activateMaintenanceMode}
        />
      )}
    >
      {view === "dashboard" && renderDashboard()}
      {view === "garage" && renderGarage()}
      {view === "replay" && renderReplay()}
      {view === "sensors" && renderSensors()}
      {view === "inventory" && renderSensorInventory()}
      {view === "identity" && renderVehicleIdentity()}
      {view === "injection" && renderInjection()}
      {(ECU_LIVE_VIEW_KEYS as readonly View[]).includes(view) && renderEcuLive(view as EcuLiveView)}
      {view === "maintenance" && renderMaintenance()}
      {view === "ecus" && renderEcus()}
      {view === "dtcs" && renderDtcs()}
      {view === "discovery" && renderDiscovery()}
      {view === "database" && renderDatabase()}
      {view === "security" && renderSecurity()}
      {view === "psa" && (LAB_MODE ? renderPsaAdvanced() : renderSecurity())}
    </AppLayout>
  );
}
