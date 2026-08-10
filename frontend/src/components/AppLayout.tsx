import type { Dispatch, ReactNode, SetStateAction } from "react";

import { API_BASE } from "../api";
import { ECU_LIVE_CATALOG, ECU_LIVE_VIEW_KEYS } from "../navigation";
import type { NavModule, View } from "../navigation";
import type { DiagnosticVehicle, Status } from "../types";
import { NavButton } from "./ui";

type AppLayoutProps = {
  children: ReactNode;
  modal?: ReactNode;
  view: View;
  openNavModule: NavModule | null;
  setOpenNavModule: Dispatch<SetStateAction<NavModule | null>>;
  status: Status | null;
  error: string;
  diagnosticVehicles: DiagnosticVehicle[];
  selectedDiagnosticVin: string;
  vehicleSelectionBusy: boolean;
  captureActive: boolean;
  detectedEcuCount?: number;
  dtcCount?: number;
  maintenanceServiceCount?: number;
  validationQueueCount?: number;
  activeTitle: { eyebrow: string; title: string; description: string };
  onNavigate: (view: View) => void;
  onClearError: () => void;
  onOpenPassiveSensors: () => Promise<void>;
  onSelectVehicle: (vin: string) => Promise<void>;
  onOpenMaintenanceModeDialog: () => void;
};

export function AppLayout({
  children,
  modal,
  view,
  openNavModule,
  setOpenNavModule,
  status,
  error,
  diagnosticVehicles,
  selectedDiagnosticVin,
  vehicleSelectionBusy,
  captureActive,
  detectedEcuCount,
  dtcCount,
  maintenanceServiceCount,
  validationQueueCount,
  activeTitle,
  onNavigate,
  onClearError,
  onOpenPassiveSensors,
  onSelectVehicle,
  onOpenMaintenanceModeDialog,
}: AppLayoutProps) {
  const navigateClean = (nextView: View) => {
    onClearError();
    onNavigate(nextView);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span>OD</span><div><strong>Diagbox++</strong><small>OpenDiag Auto</small></div></div>
        <nav>
          <p>OpenDiag</p>
          <NavButton active={view === "dashboard"} glyph="⌂" label="Accueil" onClick={() => onNavigate("dashboard")} />
          <NavButton active={view === "garage"} glyph="▣" label="Garage" onClick={() => navigateClean("garage")} count={diagnosticVehicles.length || undefined} />
          <button className={`nav-disclosure ${openNavModule === "diagnostic" ? "open" : ""}`} onClick={() => setOpenNavModule((open) => open === "diagnostic" ? null : "diagnostic")} aria-expanded={openNavModule === "diagnostic"}><span>▦</span><strong>Diagnostic</strong><b>⌄</b></button>
          {openNavModule === "diagnostic" && <div className="nav-submenu">
            <NavButton active={view === "ecus"} glyph="ECU" label="Calculateurs" onClick={() => navigateClean("ecus")} count={detectedEcuCount} />
            <NavButton active={view === "sensors"} glyph="∿" label="Live Data" onClick={() => void onOpenPassiveSensors()} />
            <NavButton active={view === "dtcs"} glyph="!" label="Défauts" onClick={() => onNavigate("dtcs")} count={dtcCount} />
            <NavButton active={view === "identity"} glyph="VIN" label="Identité" onClick={() => navigateClean("identity")} />
          </div>}
          <button className={`nav-disclosure ${openNavModule === "atelier" ? "open" : ""}`} onClick={() => setOpenNavModule((open) => open === "atelier" ? null : "atelier")} aria-expanded={openNavModule === "atelier"}><span>⌁</span><strong>Atelier</strong><b>⌄</b></button>
          {openNavModule === "atelier" && <div className="nav-submenu">
            <NavButton active={view === "injection"} glyph="INJ" label="Moteur / injection" onClick={() => navigateClean("injection")} />
            {ECU_LIVE_VIEW_KEYS.map((key) => <NavButton key={key} active={view === key} glyph={ECU_LIVE_CATALOG[key].glyph} label={ECU_LIVE_CATALOG[key].name} onClick={() => navigateClean(key)} />)}
            <NavButton active={view === "maintenance"} glyph="WF" label="Procédures métier" onClick={() => navigateClean("maintenance")} count={maintenanceServiceCount} />
            <NavButton active={false} glyph="◉" label="Tableaux de bord" onClick={() => onNavigate("studio")} />
          </div>}
          <button className={`nav-disclosure ${openNavModule === "learn" ? "open" : ""}`} onClick={() => setOpenNavModule((open) => open === "learn" ? null : "learn")} aria-expanded={openNavModule === "learn"}><span>◎</span><strong>Learn</strong><b>⌄</b></button>
          {openNavModule === "learn" && <div className="nav-submenu">
            <NavButton active={view === "discovery"} glyph="REC" label="Capturer & corréler" onClick={() => onNavigate("discovery")} />
            <NavButton active={view === "inventory"} glyph="✓" label="Valider les capteurs" onClick={() => navigateClean("inventory")} count={validationQueueCount} />
            <NavButton active={view === "replay"} glyph="▷" label="Replays" onClick={() => onNavigate("replay")} />
          </div>}
          <NavButton active={view === "database"} glyph="DB" label="Database" onClick={() => onNavigate("database")} />
          <NavButton active={view === "security" || view === "psa"} glyph="◆" label="Security & Workflow" onClick={() => onNavigate("security")} />
        </nav>
        <div className="sidebar-footer"><div className={`connection-dot ${status ? "connected" : ""}`} /><div><strong>{status ? "Backend connecté" : "Backend hors ligne"}</strong><small>{status?.transport ?? API_BASE.replace(/^https?:\/\//, "")}</small></div></div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">{activeTitle.eyebrow}</span><h1>{activeTitle.title}</h1><p>{activeTitle.description}</p></div>
          <div className="topbar-status">
            <button className="topbar-customize" onClick={() => onNavigate("studio")}>Personnaliser le direct</button>
            <div className="vehicle-switcher-compact">
              <span>Véhicule actif</span>
              <select aria-label="Véhicule actif" value={selectedDiagnosticVin} disabled={!diagnosticVehicles.length || vehicleSelectionBusy || captureActive} onChange={(event) => void onSelectVehicle(event.target.value)}>
                {!diagnosticVehicles.length && <option value="">Aucun VIN chargé</option>}
                {diagnosticVehicles.map((vehicle) => <option value={vehicle.vin} key={vehicle.vin}>{vehicle.manufacturer} {vehicle.model} · {vehicle.vin.slice(-6)}</option>)}
              </select>
              <button aria-label="Ouvrir le garage" title="Ouvrir le garage" onClick={() => onNavigate("garage")}>▣</button>
            </div>
            <button className={`status-pill mode-status-button ${status?.read_only ? "good" : status ? "bad" : "neutral"}`} onClick={() => { onNavigate("security"); if (status?.read_only) onOpenMaintenanceModeDialog(); }}><i /> {status ? (status.read_only ? "Lecture seule · changer" : "Maintenance · gérer") : "État inconnu"}</button>
          </div>
        </header>
        <main className="content">
          {error && <div className="global-error"><strong>Opération impossible</strong><span>{error}</span><button onClick={onClearError}>×</button></div>}
          {children}
        </main>
      </div>
      {modal}
    </div>
  );
}
