import type { ReactNode } from "react";

export function ReplayWarningIcon({ kind }: { kind: string }) {
  const textIcons: Record<string, string> = {
    parking: "P", brake: "!", abs: "ABS", esp: "ESP", stop: "STOP", airbag: "SRS",
    tpms: "!", service: "🔧", adblue: "UREA", gearbox: "!", reverse: "R",
  };
  let drawing: ReactNode;
  switch (kind) {
    case "arrow-left":
      drawing = <path d="M8 32 29 14v11h27v14H29v11Z" fill="currentColor" />;
      break;
    case "arrow-right":
      drawing = <path d="m56 32-21-18v11H8v14h27v11Z" fill="currentColor" />;
      break;
    case "low-beam":
    case "high-beam":
    case "fog":
      drawing = <><path d="M30 17c-12 1-19 7-19 15s7 14 19 15V17Z" /><path d={kind === "low-beam" ? "m37 22 18 5M37 31l18 5M37 40l18 5" : kind === "fog" ? "m37 22 18 0M37 32h12m-12 10h18M48 27c7 2 7 8 0 10" : "m37 22 19-6M37 32h19M37 42l19 6"} /></>;
      break;
    case "oil":
      drawing = <><path d="M10 27h29l8 8-8 13H15L8 39Z" /><path d="m21 27 4-9h13l5 9M47 25l8-7" /><path d="M54 36c5 6 5 9 0 11-5-2-5-5 0-11Z" fill="currentColor" /></>;
      break;
    case "coolant":
      drawing = <><path d="M28 12v27a10 10 0 1 0 8 0V12a4 4 0 0 0-8 0Z" /><path d="M32 22v24M8 53c6-5 10 5 16 0s10 5 16 0 10 5 16 0" /></>;
      break;
    case "battery":
      drawing = <><rect x="8" y="20" width="48" height="31" rx="3" /><path d="M18 20v-6h9v6m10 0v-6h9v6M17 35h11m-5-5v11m16-6h10" /></>;
      break;
    case "fuel":
      drawing = <><rect x="12" y="10" width="27" height="44" rx="3" /><path d="M18 16h15v13H18Zm21 5 9 7v19c0 7 8 7 8 0V25l-6-7" /></>;
      break;
    case "engine":
      drawing = <path d="M9 24h8l6-7h18l6 7h8v23h-9l-5 6H20l-5-6H9Zm12-11v7m21-7v7M4 31h5m46 0h5" />;
      break;
    case "door":
      drawing = <><path d="M22 9h20l7 13v27l-8 7H23l-8-7V22Z" /><path d="M17 26 7 18m40 8 10-8M23 23h18l3 11H20Z" /></>;
      break;
    case "seatbelt":
      drawing = <><circle cx="24" cy="14" r="6" /><path d="M22 21 14 34l10 6 4 15m2-31 13 30M24 40h20" /></>;
      break;
    case "lane":
      drawing = <><path d="M17 56 25 8M47 56 39 8" /><path d="m32 17 8 11h-6v15h-4V28h-6Z" fill="currentColor" /></>;
      break;
    case "bulb":
      drawing = <><path d="M20 29a12 12 0 1 1 24 0c0 7-6 8-7 16H27c-1-8-7-9-7-16Z" /><path d="M27 50h10m-9 5h8M32 5V1M11 12l-4-4m46 4 4-4M9 31H3m58 0h-6" /></>;
      break;
    case "steering":
      drawing = <><circle cx="32" cy="32" r="23" /><circle cx="32" cy="32" r="6" /><path d="M10 28h44M28 37l-9 14m17-14 9 14" /></>;
      break;
    case "washer":
      drawing = <><path d="M10 42h44l-5 12H15Z" /><path d="m18 32 4-8m10 8V20m10 12-4-8" /><circle cx="22" cy="18" r="2" fill="currentColor" /><circle cx="32" cy="14" r="2" fill="currentColor" /><circle cx="42" cy="18" r="2" fill="currentColor" /></>;
      break;
    case "glow":
      drawing = <path d="M6 32c5-13 11-13 16 0s11 13 16 0 11-13 20 0" />;
      break;
    default:
      drawing = <text x="32" y="38" textAnchor="middle" fill="currentColor">{textIcons[kind] ?? kind.slice(0, 4).toUpperCase()}</text>;
  }
  return <svg viewBox="0 0 64 64" aria-hidden="true">{drawing}</svg>;
}
