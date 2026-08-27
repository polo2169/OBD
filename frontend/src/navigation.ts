export const ECU_LIVE_VIEW_KEYS = [
  "gearbox",
  "abs_esp",
  "bsi",
  "airbag",
  "power_steering",
  "instrument_cluster",
  "climate_control",
  "front_camera",
  "parking_assistance",
  "telematics",
  "gear_selector",
  "rain_light_sensor",
  "front_radar",
  "tire_pressure",
] as const;

export type EcuLiveView = typeof ECU_LIVE_VIEW_KEYS[number];

export const ECU_LIVE_CATALOG: Record<EcuLiveView, { name: string; glyph: string }> = {
  gearbox: { name: "Boîte de vitesses pilotée / automatique", glyph: "BV" },
  abs_esp: { name: "ABS / ESP90 Bosch", glyph: "ESP" },
  bsi: { name: "Boîtier de servitude intelligent", glyph: "BSI" },
  airbag: { name: "Airbags / prétensionneurs", glyph: "SRS" },
  power_steering: { name: "Direction assistée électrique", glyph: "DIR" },
  instrument_cluster: { name: "Combiné d'instruments", glyph: "CBI" },
  climate_control: { name: "Climatisation", glyph: "CLI" },
  front_camera: { name: "Caméra vidéo multifonction", glyph: "CAM" },
  parking_assistance: { name: "Aide au stationnement", glyph: "PARK" },
  telematics: { name: "Autoradio / télématique", glyph: "NAC" },
  gear_selector: { name: "Commande électrique de boîte / sélecteur", glyph: "SEL" },
  rain_light_sensor: { name: "Capteur de pluie et luminosité", glyph: "PLU" },
  front_radar: { name: "Radar avant / régulation adaptative", glyph: "RAD" },
  tire_pressure: { name: "Surveillance pression pneumatiques", glyph: "TPMS" },
};

export type View = "dashboard" | "garage" | "studio" | "replay" | "sensors" | "inventory" | "identity" | "injection" | "maintenance" | "psa" | "ecus" | "dtcs" | "discovery" | "database" | "security" | EcuLiveView;

export type NavModule = "advanced";

export const views: View[] = ["dashboard", "garage", "studio", "replay", "sensors", "inventory", "identity", "injection", "maintenance", "psa", "ecus", "dtcs", "discovery", "database", "security", ...ECU_LIVE_VIEW_KEYS];

export const LAB_MODE = new URLSearchParams(window.location.search).get("lab") === "1"
  || import.meta.env.VITE_LAB_MODE === "true";

export function initialView(): View {
  const requested = new URLSearchParams(window.location.search).get("view");
  if (requested === "psa" && !LAB_MODE) return "security";
  return views.includes(requested as View) ? (requested as View) : "dashboard";
}

export const viewTitles: Record<View, { eyebrow: string; title: string; description: string }> = {
  dashboard: {
    eyebrow: "Mon véhicule",
    title: "Accueil",
    description: "L’essentiel du véhicule actif, son entretien et les points à suivre.",
  },
  garage: {
    eyebrow: "Mes véhicules",
    title: "Garage",
    description: "Sélectionne un véhicule et retrouve tout son historique dans un seul dossier.",
  },
  studio: {
    eyebrow: "Composition libre",
    title: "Dashboard libre",
    description: "Dispose, redimensionne et enregistre tes instruments comme tu le souhaites.",
  },
  replay: {
    eyebrow: "Post-traitement temporel",
    title: "Replay véhicule",
    description: "Trajectoire reconstruite, commandes conducteur, instruments et aides à la conduite.",
  },
  sensors: {
    eyebrow: "CAN passif + OBD temps réel",
    title: "Capteurs en direct",
    description: "Trames constructeur passives et lectures Mode 01 normalisées, avec provenance explicite.",
  },
  inventory: {
    eyebrow: "Validation guidée",
    title: "Validation des capteurs",
    description: "Une file de travail claire pour observer, tester et confirmer chaque information utile.",
  },
  identity: {
    eyebrow: "OBD-II / UDS · lecture seule",
    title: "VIN & identité véhicule",
    description: "Lecture multi-source du VIN, du logiciel, de la calibration et du nom ECU pour Peugeot ou Fiat.",
  },
  injection: {
    eyebrow: "Calculateur moteur · OBD-II",
    title: "Injection & moteur",
    description: "Air, carburant, pression de rampe, combustion, EGR et températures en lecture seule.",
  },
  maintenance: {
    eyebrow: "Carnet du véhicule",
    title: "Entretien & réparations",
    description: "Ajoute une facture, une réparation ou un diagnostic et suis les recommandations à venir.",
  },
  psa: {
    eyebrow: "UDS constructeur · accès protégé",
    title: "Centre d’autorisation PSA",
    description: "Lecture, commandes nommées et outils experts séparés par des niveaux d’autorisation explicites.",
  },
  ecus: {
    eyebrow: "Architecture et défauts",
    title: "Diagnostic véhicule",
    description: "Identifier les calculateurs, lire les défauts et conserver un rapport par VIN.",
  },
  dtcs: {
    eyebrow: "Mémoire défauts",
    title: "Codes DTC",
    description: "Défauts décodés, états UDS et provenance des catalogues.",
  },
  discovery: {
    eyebrow: "OpenDiag Learn",
    title: "Découverte & corrélation",
    description: "Enregistrer passivement, annoter les actions et analyser hors ligne.",
  },
  database: {
    eyebrow: "Connaissance ouverte",
    title: "Database OpenDiag",
    description: "ECU, capteurs, DTC, procédures, sources et niveaux de confiance.",
  },
  security: {
    eyebrow: "Moteur interne de protection",
    title: "Security & Workflow",
    description: "Préconditions, autorisations, journalisation, contrôle et rapports pour chaque opération.",
  },
  ...Object.fromEntries(ECU_LIVE_VIEW_KEYS.map((key) => [key, {
    eyebrow: "Calculateur · lecture seule",
    title: ECU_LIVE_CATALOG[key].name,
    description: "Signaux CAN décodés attribués à ce calculateur et zones UDS en direct, sans écriture ni commande.",
  }])) as Record<EcuLiveView, { eyebrow: string; title: string; description: string }>,
};
