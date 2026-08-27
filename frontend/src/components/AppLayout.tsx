import type { Dispatch, ReactNode, SetStateAction } from "react";

import { API_BASE } from "../api";
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
          <p>Mon garage</p>
          <NavButton active={view === "dashboard"} glyph="⌂" label="Accueil" onClick={() => navigateClean("dashboard")} />
          <NavButton active={view === "garage"} glyph="▣" label="Garage" onClick={() => navigateClean("garage")} count={diagnosticVehicles.length || undefined} />
          <NavButton active={view === "maintenance"} glyph="⌁" label="Entretien & réparations" onClick={() => navigateClean("maintenance")} />

          <p>Diagnostic</p>
          <NavButton active={view === "ecus"} glyph="ECU" label="Diagnostic complet" onClick={() => navigateClean("ecus")} count={detectedEcuCount} />
          <NavButton active={view === "dtcs"} glyph="!" label="Défauts" onClick={() => navigateClean("dtcs")} count={dtcCount} />
          <NavButton active={view === "sensors"} glyph="∿" label="Données en direct" onClick={() => void onOpenPassiveSensors()} />

          <button className={`nav-disclosure ${openNavModule === "advanced" ? "open" : ""}`} onClick={() => setOpenNavModule((open) => open === "advanced" ? null : "advanced")} aria-expanded={openNavModule === "advanced"}><span>•••</span><strong>Outils avancés</strong><b>⌄</b></button>
          {openNavModule === "advanced" && <div className="nav-submenu">
            <NavButton active={view === "identity"} glyph="VIN" label="Identité du véhicule" onClick={() => navigateClean("identity")} />
            <NavButton active={view === "injection"} glyph="INJ" label="Moteur / injection" onClick={() => navigateClean("injection")} />
            <NavButton active={view === "studio"} glyph="◉" label="Tableau de bord direct" onClick={() => navigateClean("studio")} />
            <NavButton active={view === "discovery"} glyph="REC" label="Capturer des données" onClick={() => navigateClean("discovery")} />
            <NavButton active={view === "inventory"} glyph="✓" label="Valider les capteurs" onClick={() => navigateClean("inventory")} count={validationQueueCount} />
            <NavButton active={view === "replay"} glyph="▷" label="Revoir un trajet" onClick={() => navigateClean("replay")} />
            <NavButton active={view === "database"} glyph="DB" label="Base technique" onClick={() => navigateClean("database")} />
            <NavButton active={view === "security" || view === "psa"} glyph="◆" label="Sécurité des opérations" onClick={() => navigateClean("security")} />
          </div>}
        </nav>
        <div className="sidebar-footer"><div className={`connection-dot ${status ? "connected" : ""}`} /><div><strong>{status ? "Backend connecté" : "Backend hors ligne"}</strong><small>{status?.transport ?? API_BASE.replace(/^https?:\/\//, "")}</small></div></div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">{activeTitle.eyebrow}</span><h1>{activeTitle.title}</h1><p>{activeTitle.description}</p></div>
          <div className="topbar-status">
            <div className="vehicle-switcher-compact">
              <span>Véhicule actif</span>
              <select aria-label="Véhicule actif" value={selectedDiagnosticVin} disabled={!diagnosticVehicles.length || vehicleSelectionBusy || captureActive} onChange={(event) => void onSelectVehicle(event.target.value)}>
                {!diagnosticVehicles.length && <option value="">Aucun VIN chargé</option>}
                {diagnosticVehicles.map((vehicle) => <option value={vehicle.vin} key={vehicle.vin}>{vehicle.manufacturer} {vehicle.model} · {vehicle.vin.slice(-6)}</option>)}
              </select>
              <button aria-label="Ouvrir le garage" title="Ouvrir le garage" onClick={() => onNavigate("garage")}>▣</button>
            </div>
            <button className={`status-pill mode-status-button ${status?.read_only ? "good" : status ? "bad" : "neutral"}`} onClick={() => { onNavigate("security"); if (status?.read_only) onOpenMaintenanceModeDialog(); }}><i /> {status ? (status.read_only ? "Mode sûr · lecture seule" : "Mode avancé actif") : "État inconnu"}</button>
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
