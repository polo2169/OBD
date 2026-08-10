import type {
  PassiveSensorSnapshot,
  ReplayData,
  ReplayGaugeDefinition,
  ReplayGraphGeometry,
  ReplayIndicatorDefinition,
  ReplayIndicatorState,
  ReplaySample,
  RouteGeometry,
  StudioGraphWindowSeconds,
  StudioWidget,
  VehicleVisualProfile,
} from "./types";

export const replayGaugeCatalog: ReplayGaugeDefinition[] = [
  { key: "speed_kph", label: "Vitesse véhicule", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#62e39a", note: "Vitesse véhicule calculée à partir des roues ABS." },
  { key: "engine_rpm", label: "Régime moteur", unit: "tr/min", minimum: 0, maximum: 6500, color: "#8ce9b4", note: "Régime moteur diffusé par le calculateur moteur." },
  { key: "engine_load_pct", label: "Charge moteur", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#ff8d72", note: "Charge moteur calculée normalisée EOBD 01/04." },
  { key: "absolute_engine_load_pct", label: "Charge moteur absolue", unit: "%", minimum: 0, maximum: 150, precision: 1, color: "#ffb45f", note: "Charge absolue normalisée EOBD 01/43." },
  { key: "fuel_pressure_kpa", label: "Pression carburant basse", unit: "kPa", minimum: 0, maximum: 765, precision: 0, color: "#f2cc60", note: "Pression carburant relative EOBD 01/0A, uniquement si l'ECU Fiat l'annonce." },
  { key: "manifold_pressure_kpa", label: "Pression collecteur", unit: "kPa abs", minimum: 20, maximum: 110, precision: 0, color: "#72c6ff", note: "Capteur MAP normalisé EOBD 01/0B; particulièrement pertinent sur le 1.2 FIRE." },
  { key: "mass_air_flow_g_s", label: "Débit d'air massique", unit: "g/s", minimum: 0, maximum: 150, precision: 2, color: "#63e6e2", note: "Débit d'air MAF EOBD 01/10 lorsqu'un débitmètre est exposé." },
  { key: "throttle_position_pct", label: "Position papillon", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#62e39a", note: "Position absolue du papillon EOBD 01/11." },
  { key: "relative_throttle_position_pct", label: "Position relative papillon", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#8ce9b4", note: "Ouverture relative du papillon EOBD 01/45." },
  { key: "throttle_position_b_pct", label: "Papillon voie B", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#59a8ff", note: "Seconde piste de position du papillon EOBD 01/47." },
  { key: "throttle_position_c_pct", label: "Papillon voie C", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#89d7ff", note: "Troisième piste de position du papillon EOBD 01/48 lorsqu'elle existe." },
  { key: "commanded_throttle_actuator_pct", label: "Commande actionneur papillon", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#b8efc9", note: "Consigne envoyée au papillon motorisé EOBD 01/4C." },
  { key: "fiat_throttle_candidate_pct", label: "Papillon CAN Fiat candidat", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#62e39a", note: "Octet 7 de 0x0618A001 mis à l'échelle 0…100 %. À comparer au papillon EOBD 01/11." },
  { key: "fiat_air_load_candidate_raw", label: "Charge d'air Fiat candidate", unit: "brut", minimum: 0, maximum: 255, precision: 0, color: "#72c6ff", note: "Octet 4 de 0x0618A001. Sa dynamique suit l'admission, mais aucune unité physique n'est encore attribuée." },
  { key: "ignition_advance_deg", label: "Avance à l'allumage", unit: "°", minimum: -20, maximum: 60, precision: 1, color: "#b384ff", note: "Avance d'allumage essence EOBD 01/0E." },
  { key: "fuel_injection_timing_deg", label: "Calage d'injection", unit: "°", minimum: -90, maximum: 90, precision: 1, color: "#ff8ec7", note: "Calage normalisé de l'injection EOBD 01/5D si pris en charge." },
  { key: "short_fuel_trim_pct", label: "Correction richesse court terme", unit: "%", minimum: -25, maximum: 25, precision: 1, color: "#f2cc60", note: "STFT banque 1 normalisée EOBD 01/06." },
  { key: "long_fuel_trim_pct", label: "Correction richesse long terme", unit: "%", minimum: -25, maximum: 25, precision: 1, color: "#ffb45f", note: "LTFT banque 1 normalisée EOBD 01/07." },
  { key: "oxygen_sensor_b1s1_v", label: "Lambda amont B1S1", unit: "V", minimum: 0, maximum: 1.1, precision: 3, color: "#63e6e2", note: "Tension de la sonde amont EOBD 01/14 lorsqu'elle est exposée." },
  { key: "oxygen_sensor_b1s2_v", label: "Lambda aval B1S2", unit: "V", minimum: 0, maximum: 1.1, precision: 3, color: "#89d7ff", note: "Tension de la sonde aval EOBD 01/15 lorsqu'elle est exposée." },
  { key: "commanded_equivalence_ratio", label: "Richesse commandée", unit: "λ", minimum: .7, maximum: 1.3, precision: 3, color: "#b8efc9", note: "Rapport lambda commandé EOBD 01/44." },
  { key: "evap_purge_pct", label: "Purge canister", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#a7c7e7", note: "Commande de purge des vapeurs d'essence EOBD 01/2E." },
  { key: "engine_runtime_s", label: "Temps moteur", unit: "s", minimum: 0, maximum: 7200, precision: 0, color: "#8ce9b4", note: "Temps écoulé depuis le démarrage EOBD 01/1F." },
  { key: "fuel_level_pct", label: "Niveau carburant", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#f2cc60", note: "Niveau déclaré en EOBD 01/2F si le calculateur Fiat le relaie." },
  { key: "fuel_rate_lph", label: "Débit carburant", unit: "L/h", minimum: 0, maximum: 30, precision: 2, color: "#ff8d72", note: "Débit carburant normalisé EOBD 01/5E si pris en charge." },
  { key: "idle_setpoint_rpm", label: "Consigne de ralenti", unit: "tr/min", minimum: 650, maximum: 1100, color: "#b8efc9", note: "Consigne du calculateur moteur, validée par comparaison avec le régime réel au ralenti." },
  { key: "current_gear", label: "Rapport engagé", unit: "rapport", minimum: 0, maximum: 9, color: "#f2cc60", note: "Rapport réellement engagé diffusé par le calculateur moteur. Sur cette capture, le code 9 correspond à la marche arrière." },
  { key: "target_gear", label: "Rapport cible", unit: "rapport", minimum: 0, maximum: 9, color: "#ffb45f", note: "Rapport demandé pendant la stratégie de changement de vitesse. Le code 9 est affiché R." },
  { key: "steering_angle_deg", label: "Angle du volant", unit: "°", minimum: -540, maximum: 540, precision: 1, color: "#b384ff", note: "Angle du volant validé sur ce véhicule; négatif vers la droite." },
  { key: "brake_pressure_raw", label: "Pression de freinage brute", unit: "brut", minimum: 0, maximum: 255, color: "#ff6b65", note: "Signal de freinage non calibré : aucune unité physique ne doit être déduite." },
  { key: "oil_temperature_c", label: "Température d'huile", unit: "°C", minimum: 40, maximum: 150, color: "#ffb45f", note: "Température du carter moteur issue du message Dat_CMM." },
  { key: "coolant_temperature_c", label: "Liquide de refroidissement", unit: "°C", minimum: 40, maximum: 120, color: "#59a8ff", note: "Température d'eau moteur diffusée par le calculateur." },
  { key: "oil_pressure_switch", label: "Contacteur pression d'huile", unit: "état", minimum: 0, maximum: 1, color: "#ffcf66", note: "Signal logique uniquement : aucune pression en bar n'est disponible.", status: true },
  { key: "battery_voltage_v", label: "Tension batterie", unit: "V", minimum: 10, maximum: 15, precision: 2, color: "#62e39a", note: "Tension brute du réseau électrique diffusée par le BSI." },
  { key: "battery_charge_pct", label: "Charge batterie", unit: "%", minimum: 0, maximum: 100, color: "#8ce9b4", note: "Estimation de charge batterie du BSI." },
  { key: "battery_temperature_c", label: "Température batterie", unit: "°C", minimum: -20, maximum: 80, color: "#89d7ff", note: "Température batterie candidate OpenDBC." },
  { key: "ambient_temperature_c", label: "Température extérieure", unit: "°C", minimum: -20, maximum: 50, precision: 1, color: "#8fdcff", note: "Température ambiante diffusée à 1 Hz." },
  { key: "intake_air_temperature_c", label: "Air d'admission", unit: "°C", minimum: -20, maximum: 100, color: "#b384ff", note: "Température d'air à l'admission moteur." },
  { key: "atmospheric_pressure_hpa", label: "Pression atmosphérique", unit: "hPa", minimum: 850, maximum: 1100, color: "#a7c7e7", note: "Pression environnementale candidate OpenDBC." },
  { key: "fuel_liters", label: "Niveau carburant filtré", unit: "L", minimum: 0, maximum: 53, precision: 1, color: "#f2cc60", note: "Mesure du flotteur amortie sur 120 s pour réduire le ballottement; l'étalonnage absolu reste à confirmer." },
  { key: "engine_torque_nm", label: "Couple moteur", unit: "Nm", minimum: -100, maximum: 400, color: "#ff8d72", note: "Estimation de couple moteur réel." },
  { key: "accelerator_pct", label: "Accélérateur · voie D", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#62e39a", note: "Position de pédale; sur la Fiat, voie normalisée EOBD 01/49." },
  { key: "accelerator_secondary_pct", label: "Accélérateur · voie E", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#8ce9b4", note: "Seconde voie redondante de la pédale EOBD 01/4A." },
  { key: "relative_accelerator_position_pct", label: "Accélérateur relatif", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#b8efc9", note: "Position relative de l'accélérateur EOBD 01/5A." },
  { key: "cruise_xvv_state", label: "Régulateur · état brut", unit: "code", minimum: 0, maximum: 3, color: "#f2cc60", note: "0x208 Dyn_CMM, octet 4 bits 2-3 : 0 inactif, 2 actif, 3 transitoire (bascule). Candidat confirmé par corrélation sur plusieurs essais.", experimental: true },
  { key: "cruise_active_candidate", label: "Régulateur", unit: "état", minimum: 0, maximum: 1, color: "#62e39a", note: "Actif quand cruise_xvv_state = 2.", status: true, experimental: true },
  { key: "cruise_setpoint_kph", label: "Régulateur · consigne", unit: "km/h", minimum: 0, maximum: 150, precision: 0, color: "#89d7ff", note: "0x50E Dat_CLIM.P219_Com_xPrpReqRaw (255 = inactif). Confirmé sur 5 engagements, 4 essais indépendants.", experimental: true },
  { key: "cruise_setpoint_step_kph", label: "Régulateur · pas détecté", unit: "km/h", minimum: -10, maximum: 10, precision: 1, color: "#89d7ff", note: "Amplitude du dernier saut de cruise_setpoint_kph (0x50E) : détection automatique des appuis + et - du commodo, aucun bit de direction dédié identifié sur le bus observé.", experimental: true },
  { key: "acc_mode", label: "ACC · type de régulation", unit: "code", minimum: 0, maximum: 3, color: "#ffb45f", note: "0x452 HS2_DAT_MDD_CMD_452.LONGITUDINAL_REGULATION_TYPE (2 bits, code caméra ACC/LVV). Toujours à 0 sur les essais disponibles.", experimental: true },
  { key: "acc_requested", label: "ACC · demande caméra", unit: "état", minimum: 0, maximum: 1, color: "#ffb45f", note: "0x452 HS2_DAT_MDD_CMD_452.RVV_ACC_ACTIVATION_REQ : demande d'activation de l'ACC par la caméra.", status: true, experimental: true },
  { key: "lvv_requested", label: "LVV · demande caméra", unit: "état", minimum: 0, maximum: 1, color: "#ffb45f", note: "0x452 HS2_DAT_MDD_CMD_452.LVV_ACTIVATION_REQ : demande d'activation du limiteur par la caméra.", status: true, experimental: true },
  { key: "speed_setpoint_kph", label: "ACC · consigne caméra", unit: "km/h", minimum: 0, maximum: 150, precision: 0, color: "#ffb45f", note: "0x452 HS2_DAT_MDD_CMD_452.SPEED_SETPOINT : consigne caméra ACC/LVV, distincte de la consigne commodo cruise_setpoint_kph (0x50E).", experimental: true },
  { key: "climate_ac_active", label: "Climatisation active", unit: "état", minimum: 0, maximum: 1, color: "#59a8ff", note: "0x50E Dat_CLIM.P050_Com_stAC.", status: true },
  { key: "climate_ac_power_kw", label: "Climatisation · puissance", unit: "kW", minimum: 0, maximum: 6.4, precision: 2, color: "#59a8ff", note: "0x50E Dat_CLIM.P210_Com_pwrACDem × 0.025." },
  { key: "interior_temp_candidate_c", label: "Température intérieure (candidat)", unit: "°C", minimum: 0, maximum: 40, precision: 1, color: "#8fdcff", note: "0x3B8 octet 2, non documenté. Dérive lente et plage plausible sur un essai ; non validé.", experimental: true },
  { key: "front_sensor_b0_raw", label: "Radar avant · octet 0", unit: "brut", minimum: 0, maximum: 255, color: "#ff8ec7", note: "0x489 octet 0, non documenté. Candidat très précoce, non validé.", experimental: true },
  { key: "front_sensor_b2_raw", label: "Radar avant · octet 2", unit: "brut", minimum: 0, maximum: 255, color: "#ff8ec7", note: "0x489 octet 2, non documenté. Candidat très précoce, non validé.", experimental: true },
  { key: "front_sensor_b4_raw", label: "Radar avant · octet 4", unit: "brut", minimum: 0, maximum: 32, color: "#ff8ec7", note: "0x489 octet 4, non documenté. Bascule par à-coups dont la cadence semble suivre la proximité sur deux essais dédiés ; à confirmer.", experimental: true },
  { key: "rear_left_door", label: "Porte arrière gauche", unit: "état", minimum: 0, maximum: 1, color: "#62e39a", note: "0x412 Dat_BSI, octet 6, bit 0x20 (non documenté dans opendbc). Validé par essai dédié : bascule fermé/ouvert/fermé/ouvert/fermé, DRIVER_DOOR/PASSENGER_DOOR/PARKING_BRAKE constants pendant le test.", status: true },
  { key: "rear_right_door", label: "Porte arrière droite", unit: "état", minimum: 0, maximum: 1, color: "#62e39a", note: "0x412 Dat_BSI, octet 6, bit 0x40 (non documenté dans opendbc). Validé par essai dédié : bascule fermé/ouvert/fermé/ouvert/fermé, DRIVER_DOOR/PASSENGER_DOOR/PARKING_BRAKE constants pendant le test.", status: true },
  { key: "rear_door_ajar_candidate", label: "Porte arrière (indicateur générique, candidat)", unit: "état", minimum: 0, maximum: 1, color: "#f2cc60", note: "0x78D octet 7, non documenté. Bascule 0/1 à l'identique sur les essais porte arrière gauche ET droite : hypothèse d'un indicateur générique « au moins une porte arrière ouverte », non confirmée individuellement.", status: true, experimental: true },
  { key: "engine_rpm_3b8_candidate", label: "Régime moteur · copie 0x3B8 (candidat)", unit: "tr/min", minimum: 0, maximum: 4000, precision: 0, color: "#ff8d72", note: "0x3B8 octet 0, non documenté. Formule exacte confirmée par corrélation : rpm ≈ (255 − octet) × 32.", },
  { key: "accelerator_pct_3b8_candidate", label: "Accélérateur · copie 0x3B8 (candidat)", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#62e39a", note: "0x3B8 octet 3, non documenté. Formule exacte confirmée par corrélation : pct ≈ (255 − octet) / 2. Corrige l'ancienne hypothèse « climatisation air soufflé ».", },
  { key: "accelerator_pct_2e8_candidate", label: "Accélérateur · copie 0x2E8 (candidat)", unit: "%", minimum: 0, maximum: 100, precision: 1, color: "#8ce9b4", note: "0x2E8 octet 1, non documenté. Formule exacte confirmée par corrélation : octet ≈ pct × 2.", },
  { key: "engine_state_57c_candidate_raw", label: "État moteur · 0x57C (hypothèse)", unit: "brut", minimum: 0, maximum: 255, color: "#f2cc60", note: "0x57C octet 5, non documenté. Anti-corrélé au régime moteur (r≈-0.79) mais seulement 5-7 valeurs distinctes sur un essai : hypothèse d'un état discret (ralenti, Start&Stop…), non confirmée.", experimental: true },
  { key: "gear_torque_table_2e8_candidate_raw", label: "Table couple/rapport · 0x2E8 (hypothèse)", unit: "brut", minimum: 0, maximum: 255, color: "#f2cc60", note: "0x2E8 octet 3, non documenté. Corrèle modérément avec la vitesse et le rapport engagé (r≈0.66-0.68) mais seulement 4-5 valeurs distinctes : hypothèse d'une table liée au rapport, non confirmée.", experimental: true },
  { key: "speed_389_candidate_raw", label: "Vitesse · 0x389 (hypothèse)", unit: "brut", minimum: 0, maximum: 255, color: "#f2cc60", note: "0x389 octet 0, non documenté. Corrélation modérée avec la vitesse (r≈0.5) : piste faible, non confirmée.", experimental: true },
  { key: "fiat_clock_hour_candidate", label: "Fiat · horloge (heure)", unit: "h", minimum: 0, maximum: 23, color: "#89d7ff", note: "0x0C28A000 octet 0, BCD. Auto-validé : incrémente avec la minute.", experimental: true },
  { key: "fiat_clock_minute_candidate", label: "Fiat · horloge (minute)", unit: "min", minimum: 0, maximum: 59, color: "#89d7ff", note: "0x0C28A000 octet 1, BCD. Incrémente de +1 toutes les 60s réelles observées.", experimental: true },
  { key: "fiat_start_stop_state_raw", label: "Fiat · état Start&Stop", unit: "code", minimum: 0, maximum: 5, color: "#f2cc60", note: "0x0C1CA000 octet 1, brut. Un seul changement observé (coupure contact) ; à confirmer.", experimental: true },
  { key: "fiat_clutch_pedal_candidate", label: "Fiat · pédale d'embrayage", unit: "état", minimum: 0, maximum: 1, color: "#62e39a", note: "0x0628A001 octet 5 = 0x10. Impulsions brèves cohérentes avec des changements de rapport.", status: true, experimental: true },
  { key: "fiat_battery_voltage_candidate_v", label: "Fiat · tension batterie", unit: "V", minimum: 10, maximum: 15, precision: 1, color: "#62e39a", note: "0x0628A001 octet 3 × 0.1. Stable à 12.8V, avec de brefs écarts (11.6-13.8V) pile aux mêmes instants que la pédale d'embrayage.", experimental: true },
  { key: "fiat_a1_fast_nibble_candidate", label: "Fiat · 0x0A18A001 nibble rapide", unit: "brut", minimum: 0, maximum: 15, color: "#ff8ec7", note: "Change toutes les 100-300 ms : trop rapide pour un rapport de boîte, signification inconnue.", experimental: true },
  { key: "fiat_mode_flag_candidate", label: "Fiat · drapeau de mode", unit: "état", minimum: 0, maximum: 1, color: "#b384ff", note: "0x0A18A001 octet 4. Bascule par blocs de 1-2 minutes ; hypothèse : climatisation ou ralenti.", status: true, experimental: true },
  { key: "fiat_mode_analog_candidate_raw", label: "Fiat · valeur liée au mode", unit: "brut", minimum: 0, maximum: 255, color: "#b384ff", note: "0x0A18A001 octet 5. Plage très différente selon le drapeau de mode ; signification inconnue.", experimental: true },
  { key: "longitudinal_accel_ms2", label: "Accélération longitudinale", unit: "m/s²", minimum: -4, maximum: 4, precision: 2, color: "#72c6ff", note: "Accélération calculée à partir des roues." },
  { key: "lateral_accel_ms2", label: "Accélération latérale", unit: "m/s²", minimum: -5, maximum: 5, precision: 2, color: "#ff8ec7", note: "Trame 0x3CD, échelle 0,05 m/s² validée par corrélation avec les quatre roues et le volant." },
  { key: "yaw_rate_deg_s", label: "Vitesse de lacet", unit: "°/s", minimum: -40, maximum: 40, precision: 1, color: "#63e6e2", note: "Trame 0x3CD, échelle 0,1°/s validée par deux références CAN indépendantes." },
  { key: "driver_torque", label: "Effort au volant", unit: "brut", minimum: -60, maximum: 60, color: "#b5a2ff", note: "Valeur de colonne validée mais non calibrée en N·m." },
  { key: "steering_rate_deg_s", label: "Vitesse du volant", unit: "°/s", minimum: -120, maximum: 120, color: "#b384ff", note: "Vitesse et sens de rotation du volant." },
  { key: "wheel_front_left_kph", label: "Roue avant gauche", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
  { key: "wheel_front_right_kph", label: "Roue avant droite", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
  { key: "wheel_rear_left_kph", label: "Roue arrière gauche", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
  { key: "wheel_rear_right_kph", label: "Roue arrière droite", unit: "km/h", minimum: 0, maximum: 150, precision: 1, color: "#59a8ff", note: "Vitesse individuelle mesurée par l'ABS." },
];

export const defaultReplayGaugeKeys = [
  "oil_temperature_c",
  "coolant_temperature_c",
  "oil_pressure_switch",
  "battery_voltage_v",
];

export const laneAssistStatusLabels: Record<number, string> = {
  0: "Indisponible",
  1: "Non sélectionné",
  2: "Sélectionné",
  3: "Autorisé",
  4: "Actif",
  5: "Défaut",
  6: "Collision détectée",
  7: "Réservé",
};

export function laneAssistStatusLabel(status?: number | null): string {
  return typeof status === "number"
    ? laneAssistStatusLabels[status] ?? `État inconnu ${status}`
    : "État absent";
}

export const cruiseXvvStateLabels: Record<number, string> = {
  0: "Inactif",
  2: "Actif",
  3: "Transitoire",
};

export function cruiseXvvStateLabel(state?: number | null): string {
  return typeof state === "number"
    ? cruiseXvvStateLabels[state] ?? `État inconnu ${state}`
    : "Signal absent";
}

export const replayIndicatorCatalog: ReplayIndicatorDefinition[] = [
  { key: "turn_left", label: "Clignotant gauche", color: "green", icon: "arrow-left", fields: ["turn_signal"], note: "Commande de clignotant enregistrée." },
  { key: "turn_right", label: "Clignotant droit", color: "green", icon: "arrow-right", fields: ["turn_signal"], note: "Commande de clignotant enregistrée." },
  { key: "low_beam", label: "Feux de croisement", color: "green", icon: "low-beam", fields: ["low_beam"], note: "État des feux de croisement." },
  { key: "high_beam", label: "Feux de route", color: "blue", icon: "high-beam", fields: ["high_beam"], note: "État des feux de route." },
  { key: "parking_brake", label: "Frein de stationnement", color: "red", icon: "parking", fields: ["parking_brake"], note: "État candidat du frein de stationnement." },
  { key: "brake_fault", label: "Défaut freinage", color: "red", icon: "brake", fields: ["brake_fault"], note: "Demande de témoin de défaut du frein principal." },
  { key: "abs", label: "ABS", color: "amber", icon: "abs", fields: ["abs_intervention"], note: "La capture expose l'intervention ABS, pas un défaut ABS confirmé." },
  { key: "esp", label: "ESP / antipatinage", color: "amber", icon: "esp", fields: ["esp_fault_state", "esp_intervention"], note: "Défaut ou intervention ESP selon les états CAN candidats." },
  { key: "oil_pressure", label: "Contacteur d'huile", color: "red", icon: "oil", fields: ["oil_pressure_switch"], note: "Contacteur logique brut; aucune pression en bar n'est disponible." },
  { key: "coolant", label: "Température moteur", color: "red", icon: "coolant", fields: ["coolant_temperature_c"], note: "Alerte visuelle estimée à partir de la température mesurée." },
  { key: "battery", label: "Charge batterie", color: "red", icon: "battery", fields: ["battery_voltage_v", "engine_rpm"], note: "Alerte estimée si la tension est basse moteur tournant." },
  { key: "fuel", label: "Réserve carburant", color: "amber", icon: "fuel", fields: ["low_fuel_warning"], note: "Demande de témoin de niveau carburant minimal." },
  { key: "engine", label: "Voyant moteur", color: "amber", icon: "engine", fields: ["mil_on", "mil_blinking", "obd_error"], note: "États OBD/MIL candidats diffusés par le moteur." },
  { key: "door", label: "Porte ouverte", color: "red", icon: "door", fields: ["driver_door", "passenger_door"], note: "Ouverture des portes avant enregistrée." },
  { key: "rear_door", label: "Porte arrière", color: "red", icon: "door", fields: ["rear_left_door", "rear_right_door"], note: "Validé par essais dédiés : 0x412 Dat_BSI, octet 6, bits 0x20 (gauche) / 0x40 (droite), non documentés dans opendbc." },
  { key: "rear_door_ajar_candidate", label: "Porte arrière (générique, candidat)", color: "amber", icon: "door", fields: ["rear_door_ajar_candidate"], note: "0x78D octet 7, non documenté. Hypothèse d'indicateur générique, non confirmée individuellement." },
  { key: "seatbelt", label: "Ceintures", color: "red", icon: "seatbelt", fields: ["driver_seatbelt_state", "passenger_seatbelt_state"], note: "États bruts présents; leur codage exact reste à valider." },
  { key: "lane", label: "Aide au maintien de voie", color: "green", icon: "lane", fields: ["lka_active", "lane_departure", "lane_assist_status"], note: "Activation ou alerte de franchissement de ligne." },
  { key: "lane_fault", label: "Défaut aide à la conduite", color: "amber", icon: "lane", fields: ["lane_assist_status"], note: "STATUS 5 = DEFECT dans la définition CAN observée sur cette 308." },
  { key: "reverse", label: "Marche arrière", color: "green", icon: "reverse", fields: ["reverse"], note: "État de marche arrière candidat BSI." },
  { key: "headlamp_fault", label: "Défaut d'éclairage", color: "amber", icon: "bulb", fields: ["headlamp_fault"], note: "Défaut déclaré sur un feu de croisement ou de route." },
  { key: "gearbox", label: "Défaut boîte", color: "amber", icon: "gearbox", fields: ["gearbox_fault"], note: "État de défaut système de boîte candidat." },
  { key: "stop", label: "STOP", color: "red", icon: "stop", fields: ["generic_warning_requested"], note: "Requête générique de lampe d'alerte issue du calculateur ABS." },
  { key: "front_fog", label: "Antibrouillard avant", color: "green", icon: "fog", fields: [], note: "Témoin classique; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "rear_fog", label: "Antibrouillard arrière", color: "amber", icon: "fog", fields: [], note: "Témoin classique; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "airbag", label: "Airbag", color: "red", icon: "airbag", fields: [], note: "Témoin classique; aucun état airbag fiable dans ce replay.", referenceOnly: true },
  { key: "tire_pressure", label: "Pression des pneus", color: "amber", icon: "tpms", fields: [], note: "Témoin classique; signal TPMS absent de cet enregistrement.", referenceOnly: true },
  { key: "power_steering", label: "Direction assistée", color: "red", icon: "steering", fields: [], note: "Témoin classique; aucun défaut de direction enregistré.", referenceOnly: true },
  { key: "service", label: "Service", color: "amber", icon: "service", fields: [], note: "Témoin classique; état d'entretien absent du replay.", referenceOnly: true },
  { key: "adblue", label: "AdBlue / SCR", color: "amber", icon: "adblue", fields: [], note: "Témoin classique diesel; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "glow_plug", label: "Préchauffage diesel", color: "amber", icon: "glow", fields: [], note: "Témoin classique diesel; signal absent de cet enregistrement.", referenceOnly: true },
  { key: "washer", label: "Lave-glace", color: "amber", icon: "washer", fields: [], note: "Témoin classique; niveau de lave-glace non enregistré.", referenceOnly: true },
];

export const defaultReplayGraphKeys = ["speed_kph", "engine_rpm", "steering_angle_deg", "oil_temperature_c"];

export const defaultReplayIndicatorKeys = [
  "turn_left", "turn_right", "low_beam", "high_beam", "parking_brake", "brake_fault",
  "abs", "esp", "oil_pressure", "coolant", "battery", "fuel", "engine", "door", "rear_door", "seatbelt", "lane", "lane_fault",
];

export const PEUGEOT_308_HANDBOOK_URL = "https://public.servicebox.peugeot.com/APddb/modeles/308n/eGuide_308n_308_ed01-18_dag/pdfs/9999_9999_226_en-GB.pdf";

export const FIAT_500_HANDBOOK_URL = "https://aftersales.fiat.com/eLumData/EN/00/150_500/00_150_500_603.81.684_EN_01_02.10_L_LG/00_150_500_603.81.684_EN_01_02.10_L_LG.pdf";

export const PEUGEOT_308_VISUAL: VehicleVisualProfile = {
  label: "Peugeot 308",
  topImage: "/peugeot-308-top.png",
  steeringImage: "/peugeot-308-gt-steering.png",
  topAlt: "Peugeot 308 vue du dessus",
  steeringAlt: "Volant Peugeot 308 GT",
  frontAtTop: false,
};

export const FIAT_500_VISUAL: VehicleVisualProfile = {
  label: "Fiat 500",
  topImage: "/fiat-500-top.png",
  steeringImage: "/fiat-500-steering.png",
  topAlt: "Fiat 500 vue du dessus",
  steeringAlt: "Volant Fiat 500",
  frontAtTop: true,
};

export function vehicleVisualForProfile(profileKey?: string | null): VehicleVisualProfile {
  return profileKey === "fiat_500_generic" ? FIAT_500_VISUAL : PEUGEOT_308_VISUAL;
}

export const STUDIO_COLUMNS = 12;

export const STUDIO_ROW_HEIGHT = 68;

export const STUDIO_GRAPH_WINDOWS: StudioGraphWindowSeconds[] = [10, 30, 60, 300];

export const defaultStudioWidgets: StudioWidget[] = [
  { id: "studio-speed", kind: "speed", x: 0, y: 0, w: 3, h: 4 },
  { id: "studio-steering", kind: "steering", x: 3, y: 0, w: 3, h: 4 },
  { id: "studio-gear", kind: "gear", x: 6, y: 0, w: 2, h: 4 },
  { id: "studio-vehicle", kind: "vehicle", x: 8, y: 0, w: 4, h: 6 },
  { id: "studio-speed-graph", kind: "graph", key: "speed_kph", x: 0, y: 4, w: 4, h: 3, windowSeconds: 60 },
  { id: "studio-oil", kind: "gauge", key: "oil_temperature_c", x: 4, y: 4, w: 2, h: 3 },
  { id: "studio-engine-light", kind: "indicator", key: "engine", x: 6, y: 4, w: 2, h: 2 },
  { id: "studio-lane-fault", kind: "indicator", key: "lane_fault", x: 6, y: 6, w: 2, h: 2 },
  { id: "studio-capture", kind: "capture", x: 0, y: 7, w: 6, h: 2 },
  { id: "studio-rpm", kind: "gauge", key: "engine_rpm", x: 6, y: 8, w: 3, h: 3 },
  { id: "studio-battery", kind: "gauge", key: "battery_voltage_v", x: 9, y: 8, w: 3, h: 3 },
];

export function replayPointIndex(points: ReplaySample[], timeMs: number) {
  let low = 0;
  let high = points.length - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (points[middle].t_ms <= timeMs) low = middle + 1;
    else high = middle - 1;
  }
  return Math.max(0, Math.min(points.length - 1, high));
}

export function routeGeometry(replay: ReplayData | null): RouteGeometry {
  if (!replay?.points.length) return { path: "", coordinates: [], gpsCoordinates: [], mapTiles: [], mapZoom: null };
  const width = 760;
  const height = 470;
  const padding = 52;
  const geographicPoints = replay.points.filter((point) =>
    typeof point.latitude === "number"
    && Number.isFinite(point.latitude)
    && typeof point.longitude === "number"
    && Number.isFinite(point.longitude),
  );
  if (geographicPoints.length === replay.points.length) {
    const tileSize = 256;
    const project = (latitude: number, longitude: number, zoom: number) => {
      const scale = tileSize * 2 ** zoom;
      const safeLatitude = Math.max(-85.05112878, Math.min(85.05112878, latitude));
      const sinLatitude = Math.sin(safeLatitude * Math.PI / 180);
      return {
        x: (longitude + 180) / 360 * scale,
        y: (0.5 - Math.log((1 + sinLatitude) / (1 - sinLatitude)) / (4 * Math.PI)) * scale,
      };
    };
    let zoom = 18;
    let projected = geographicPoints.map((point) => project(point.latitude as number, point.longitude as number, zoom));
    for (; zoom > 2; zoom -= 1) {
      projected = geographicPoints.map((point) => project(point.latitude as number, point.longitude as number, zoom));
      const xs = projected.map((point) => point.x);
      const ys = projected.map((point) => point.y);
      if (Math.max(...xs) - Math.min(...xs) <= width - padding * 2
        && Math.max(...ys) - Math.min(...ys) <= height - padding * 2) break;
    }
    const xs = projected.map((point) => point.x);
    const ys = projected.map((point) => point.y);
    const centerX = (Math.min(...xs) + Math.max(...xs)) / 2;
    const centerY = (Math.min(...ys) + Math.max(...ys)) / 2;
    const viewportLeft = centerX - width / 2;
    const viewportTop = centerY - height / 2;
    const coordinates = projected.map((point) => ({ x: point.x - viewportLeft, y: point.y - viewportTop }));
    const pathStep = Math.max(1, Math.ceil(coordinates.length / 2400));
    const pathCoordinates = coordinates.filter((_, index) => index % pathStep === 0 || index === coordinates.length - 1);
    const path = pathCoordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const tileCount = 2 ** zoom;
    const mapTiles: RouteGeometry["mapTiles"] = [];
    const firstTileX = Math.floor(viewportLeft / tileSize);
    const lastTileX = Math.floor((viewportLeft + width) / tileSize);
    const firstTileY = Math.max(0, Math.floor(viewportTop / tileSize));
    const lastTileY = Math.min(tileCount - 1, Math.floor((viewportTop + height) / tileSize));
    for (let tileY = firstTileY; tileY <= lastTileY; tileY += 1) {
      for (let rawTileX = firstTileX; rawTileX <= lastTileX; rawTileX += 1) {
        const tileX = ((rawTileX % tileCount) + tileCount) % tileCount;
        mapTiles.push({
          key: `${zoom}-${rawTileX}-${tileY}`,
          href: `https://tile.openstreetmap.org/${zoom}/${tileX}/${tileY}.png`,
          x: rawTileX * tileSize - viewportLeft,
          y: tileY * tileSize - viewportTop,
        });
      }
    }
    const referenceLatitude = geographicPoints[Math.floor(geographicPoints.length / 2)].latitude as number;
    const metersPerPixel = Math.cos(referenceLatitude * Math.PI / 180) * 2 * Math.PI * 6378137 / (tileSize * 2 ** zoom);
    const gpsCoordinates = replay.gps_points.map((point) => {
      const projectedGps = project(point.latitude, point.longitude, zoom);
      return {
        x: projectedGps.x - viewportLeft,
        y: projectedGps.y - viewportTop,
        accuracyPx: Math.max(3, Math.min(80, point.accuracy_m / Math.max(0.01, metersPerPixel))),
      };
    });
    return { path, coordinates, gpsCoordinates, mapTiles, mapZoom: zoom };
  }
  const minX = replay.route_bounds.min_x ?? 0;
  const maxX = replay.route_bounds.max_x ?? 1;
  const minY = replay.route_bounds.min_y ?? 0;
  const maxY = replay.route_bounds.max_y ?? 1;
  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  const coordinates = replay.points.map((point) => ({
    x: width / 2 + (point.x_m - centerX) * scale,
    y: height / 2 - (point.y_m - centerY) * scale,
  }));
  const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  return { path, coordinates, gpsCoordinates: [], mapTiles: [], mapZoom: null };
}

export function replayGraphGeometry(replay: ReplayData, definition: ReplayGaugeDefinition): ReplayGraphGeometry {
  const numericPoints = replay.points.filter((point) => typeof point[definition.key] === "number");
  if (!numericPoints.length) return { path: "", minimum: definition.minimum, maximum: definition.maximum };
  const values = numericPoints.map((point) => Number(point[definition.key]));
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  const observedSpan = maximum - minimum;
  const padding = observedSpan > 0 ? observedSpan * 0.08 : Math.max(1, Math.abs(maximum) * 0.04);
  minimum -= padding;
  maximum += padding;
  const span = Math.max(0.001, maximum - minimum);
  const sampleStep = Math.max(1, Math.ceil(replay.points.length / 720));
  const sampled = replay.points.filter((_, index) => index % sampleStep === 0 || index === replay.points.length - 1);
  let drawing = false;
  const commands: string[] = [];
  sampled.forEach((point) => {
    const value = point[definition.key];
    if (typeof value !== "number") {
      drawing = false;
      return;
    }
    const x = replay.duration_ms ? point.t_ms / replay.duration_ms * 900 : 0;
    const y = 172 - (value - minimum) / span * 164;
    commands.push(`${drawing ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`);
    drawing = true;
  });
  return { path: commands.join(" "), minimum, maximum };
}

export function passiveSnapshotToReplaySample(snapshot: PassiveSensorSnapshot): { point: ReplaySample; availableFields: string[] } {
  const signals = new Map(snapshot.signals.map((signal) => [signal.key, signal.value]));
  const numeric = (key: string): number | null => {
    const value = signals.get(key);
    if (typeof value === "boolean") return Number(value);
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    return value;
  };
  const logical = (key: string): boolean | null => {
    const value = signals.get(key);
    if (typeof value === "boolean") return value;
    if (typeof value === "number" && Number.isFinite(value)) return value !== 0;
    return null;
  };
  const integer = (key: string): number | null => {
    const value = numeric(key);
    return value === null ? null : Math.round(value);
  };
  const bounded = (key: string, minimum: number, maximum: number): number | null => {
    const value = numeric(key);
    return value !== null && value >= minimum && value <= maximum ? value : null;
  };
  const turnSignalValue = integer("HS2_DAT_MDD_CMD_452.TURN_SIGNAL_STATUS");
  const headlampFaults = [
    logical("HS2_DAT7_BSI_612.DEF_FEU_CROISMNT_D"), logical("HS2_DAT7_BSI_612.DEF_FEU_CROISMNT_G"),
    logical("HS2_DAT7_BSI_612.DEF_FEU_ROUTE_D"), logical("HS2_DAT7_BSI_612.DEF_FEU_ROUTE_G"),
  ];
  const fiatWheelSpeeds = [
    numeric("FIAT_ABS.WHEEL_FRONT_LEFT_SPEED"),
    numeric("FIAT_ABS.WHEEL_FRONT_RIGHT_SPEED"),
    numeric("FIAT_ABS.WHEEL_REAR_LEFT_SPEED"),
    numeric("FIAT_ABS.WHEEL_REAR_RIGHT_SPEED"),
  ];
  const fiatAverageWheelSpeed = fiatWheelSpeeds.every((value) => value !== null)
    ? fiatWheelSpeeds.reduce<number>((total, value) => total + (value ?? 0), 0) / fiatWheelSpeeds.length
    : null;
  const point: ReplaySample = {
    t_ms: 0,
    x_m: 0,
    y_m: 0,
    heading_deg: 0,
    distance_m: 0,
    speed_kph: numeric("HS2_DYN_ABR_38D.VITESSE_VEHICULE_ROUES") ?? numeric("OBD01.vehicle_speed") ?? fiatAverageWheelSpeed,
    engine_rpm: numeric("Dyn_CMM.P000_Com_nEng") ?? numeric("FIAT_ENGINE.ENGINE_RPM") ?? numeric("OBD01.engine_rpm"),
    engine_load_pct: numeric("OBD01.engine_load"),
    absolute_engine_load_pct: numeric("OBD01.absolute_engine_load"),
    fuel_pressure_kpa: numeric("OBD01.fuel_pressure"),
    manifold_pressure_kpa: numeric("OBD01.intake_manifold_pressure"),
    mass_air_flow_g_s: numeric("OBD01.maf"),
    throttle_position_pct: numeric("OBD01.throttle_position"),
    relative_throttle_position_pct: numeric("OBD01.relative_throttle_position"),
    throttle_position_b_pct: numeric("OBD01.absolute_throttle_position_b"),
    throttle_position_c_pct: numeric("OBD01.absolute_throttle_position_c"),
    commanded_throttle_actuator_pct: numeric("OBD01.commanded_throttle_actuator"),
    fiat_throttle_candidate_pct: numeric("FIAT_ENGINE.THROTTLE_POSITION_CANDIDATE"),
    fiat_air_load_candidate_raw: numeric("FIAT_ENGINE.AIR_LOAD_CANDIDATE_RAW"),
    ignition_advance_deg: numeric("OBD01.timing_advance"),
    fuel_injection_timing_deg: numeric("OBD01.fuel_injection_timing"),
    short_fuel_trim_pct: numeric("OBD01.short_fuel_trim_bank_1"),
    long_fuel_trim_pct: numeric("OBD01.long_fuel_trim_bank_1"),
    oxygen_sensor_b1s1_v: numeric("OBD01.oxygen_sensor_b1s1_voltage"),
    oxygen_sensor_b1s2_v: numeric("OBD01.oxygen_sensor_b1s2_voltage"),
    commanded_equivalence_ratio: numeric("OBD01.commanded_equivalence_ratio"),
    evap_purge_pct: numeric("OBD01.commanded_evap_purge"),
    engine_runtime_s: numeric("OBD01.engine_runtime"),
    fuel_level_pct: numeric("OBD01.fuel_level"),
    fuel_rate_lph: numeric("OBD01.fuel_rate"),
    steering_angle_deg: snapshot.steering.detected ? snapshot.steering.angle_degrees ?? null : null,
    steering_rate_deg_s: snapshot.steering.detected ? snapshot.steering.rate_degrees_s ?? null : null,
    driver_torque: snapshot.steering.detected ? snapshot.steering.driver_torque ?? null : null,
    accelerator_pct: numeric("Dyn_CMM.P002_Com_rAPP") ?? numeric("Dyn5_CMM.P334_ACCPed_Position") ?? numeric("DRIVER.GAS_PEDAL") ?? numeric("OBD01.accelerator_pedal_d") ?? numeric("OBD01.throttle_position"),
    accelerator_secondary_pct: numeric("Dyn5_CMM.P334_ACCPed_Position") ?? numeric("OBD01.accelerator_pedal_e"),
    relative_accelerator_position_pct: numeric("OBD01.relative_accelerator_position"),
    engine_torque_nm: numeric("Dyn_CMM.P003_Com_trqActOut"),
    idle_setpoint_rpm: numeric("Dat_CMM.P022_Com_nSetPLo"),
    fuel_consumption_candidate_mm3: numeric("Dat_CMM.P021_Com_volFlCons"),
    virtual_fuel_consumption_candidate_mm3: numeric("Dat2_CMM.P316_FlSys_volFlConsVirt"),
    current_gear: integer("Dyn2_CMM.P152_Gearbx_stGear"),
    target_gear: integer("Dyn_V2_BVMP.P283_Com_stGearTrgtPos"),
    gear_shift_active: logical("Dyn_V2_BVMP.P009_Com_bGearShftActv"),
    drivetrain_engaged_state: integer("Dyn_V2_BVMP.P030_Gbx_stDrvTrnEgd"),
    longitudinal_accel_ms2: numeric("HS2_DYN_ABR_38D.ACCEL_LONGI_ROUES"),
    lateral_accel_ms2: numeric("Dyn2_FRE.LATERAL_ACCELERATION"),
    yaw_rate_deg_s: numeric("Dyn2_FRE.YAW_RATE"),
    brake_active: logical("Dat_BSI.P013_MainBrake") ?? logical("FIAT_ABS.BRAKE_PEDAL_ACTIVE"),
    brake_system_state: integer("Dyn2_FRE.P226_Com_stBrkActv"),
    brake_pressure_raw: numeric("Dyn2_FRE.BRAKE_PRESSURE") ?? numeric("FIAT_ABS.BRAKE_PEDAL_STATE_RAW"),
    turn_signal: turnSignalValue === null ? null : ({ 0: "off", 1: "right", 2: "left", 3: "hazard" } as const)[turnSignalValue as 0 | 1 | 2 | 3] ?? "off",
    low_beam: logical("HS2_DAT7_BSI_612.ETAT_FEUX_CROIST"),
    high_beam: logical("HS2_DAT7_BSI_612.ETAT_FEUX_ROUTE"),
    reverse: logical("Dat_BSI.P103_Com_bRevGear"),
    parking_brake: logical("Dat_BSI.PARKING_BRAKE") ?? logical("FIAT_BODY.PARKING_BRAKE"),
    driver_door: logical("Dat_BSI.DRIVER_DOOR") ?? logical("FIAT_BODY.DRIVER_DOOR_OPEN"),
    passenger_door: logical("Dat_BSI.PASSENGER_DOOR"),
    front_wiper_status: integer("HS2_DAT_MDD_CMD_452.FRONT_WIPER_STATUS"),
    fuel_liters_raw: numeric("HS2_DAT7_BSI_612.INFO_NIV_CARB"),
    oil_temperature_c: numeric("Dat_CMM.P011_Oil_tSwmp") ?? numeric("OBD01.engine_oil_temperature"),
    coolant_temperature_c: numeric("Dat_CMM.P005_CEngDst_tSens") ?? numeric("OBD01.coolant_temperature"),
    intake_air_temperature_c: numeric("Dat_CMM.P158_Air_tAFS") ?? numeric("OBD01.intake_air_temperature"),
    oil_pressure_switch: logical("Dat2_CMM.P278_Oil_stPSwmp"),
    battery_voltage_v: bounded("Dat6_BSI.P418_Com_uBattRaw", 8, 16.5) ?? bounded("OBD01.control_module_voltage", 8, 16.5),
    battery_temperature_c: bounded("Dat6_BSI.P273_Com_tBatt", -40, 90),
    battery_charge_pct: bounded("Dat6_BSI.P272_Com_rBattCh", 0, 100),
    ambient_temperature_c: numeric("Contexte1_5B2.P146_Com_tEnvT") ?? numeric("OBD01.ambient_temperature"),
    atmospheric_pressure_hpa: numeric("Dat2_CMM.P338_EnvP_p") ?? (() => { const value = numeric("OBD01.barometric_pressure"); return value === null ? null : value * 10; })(),
    obd_error: logical("Dyn2_CMM.P343_Com_bOBDErr"),
    mil_on: logical("Dyn2_CMM.P344_Com_bMILOn"),
    mil_blinking: logical("Dyn2_CMM.P345_Com_bMILBln"),
    esp_fault_state: integer("Dyn2_CMM.P025_Com_stESPErr"),
    esp_intervention: logical("Dyn_CDS.P147_Com_bESPIntvActv"),
    abs_intervention: logical("Dat_ABR.P351_Com_bABSIntvActv"),
    gearbox_fault: logical("Dyn_STT_BV.P444_Com_bGbxSysFaultRaw"),
    generic_warning_requested: logical("HS2_DYN_ABR_38D.REQ_LAMPE_WARNING"),
    brake_fault: logical("Dat_BSI.P040_MainBrakeFault"),
    low_fuel_warning: logical("Dat_BSI.P012_Com_bFlMin"),
    fuel_level_fault_state: integer("Dat_BSI.P086_Com_stFlLvlDia"),
    headlamp_fault: headlampFaults.some((value) => value !== null) ? headlampFaults.some(Boolean) : null,
    driver_seatbelt_state: integer("RESTRAINTS.DRIVER_SEATBELT"),
    passenger_seatbelt_state: integer("RESTRAINTS.PASSENGER_SEATBELT"),
    lane_assist_status: integer("LANE_KEEP_ASSIST.STATUS"),
    lane_departure: integer("LANE_KEEP_ASSIST.LANE_DEPARTURE"),
    lka_active: logical("LANE_KEEP_ASSIST.LXA_ACTIVATION"),
    acc_mode: integer("HS2_DAT_MDD_CMD_452.LONGITUDINAL_REGULATION_TYPE"),
    acc_requested: logical("HS2_DAT_MDD_CMD_452.RVV_ACC_ACTIVATION_REQ"),
    lvv_requested: logical("HS2_DAT_MDD_CMD_452.LVV_ACTIVATION_REQ"),
    speed_setpoint_kph: numeric("HS2_DAT_MDD_CMD_452.SPEED_SETPOINT"),
    cruise_probable: null,
    cruise_confidence: null,
    cruise_detection_state: null,
    cruise_detection_reason: null,
    cruise_switch_candidate:
      integer("HS2_DAT_MDD_CMD_452.LONGITUDINAL_REGULATION_TYPE") === null
        ? null
        : integer("HS2_DAT_MDD_CMD_452.LONGITUDINAL_REGULATION_TYPE") !== 0,
    cruise_xvv_state: integer("Dyn_CMM.P037_VehV_stXVV"),
    cruise_active_candidate:
      integer("Dyn_CMM.P037_VehV_stXVV") === null
        ? null
        : integer("Dyn_CMM.P037_VehV_stXVV") === 2,
    cruise_setpoint_kph:
      (integer("Dat_CLIM.P219_Com_xPrpReqRaw") ?? 255) >= 255
        ? null
        : integer("Dat_CLIM.P219_Com_xPrpReqRaw"),
    cruise_setpoint_direction: null,
    cruise_setpoint_step_kph: null,
    climate_ac_active: logical("Dat_CLIM.P050_Com_stAC"),
    climate_ac_power_kw:
      numeric("Dat_CLIM.P210_Com_pwrACDem") !== null
        ? Math.round(numeric("Dat_CLIM.P210_Com_pwrACDem") ?? 0) / 1000
        : null,
    front_sensor_b0_raw: integer("FRONT_SENSOR_CANDIDATE.BYTE0_RAW"),
    front_sensor_b2_raw: integer("FRONT_SENSOR_CANDIDATE.BYTE2_RAW"),
    front_sensor_b4_raw: integer("FRONT_SENSOR_CANDIDATE.BYTE4_RAW"),
    wheel_front_left_kph: numeric("Dyn4_FRE.P263_VehV_VPsvValWhlFrtL") ?? fiatWheelSpeeds[0],
    wheel_front_right_kph: numeric("Dyn4_FRE.P264_VehV_VPsvValWhlFrtR") ?? fiatWheelSpeeds[1],
    wheel_rear_left_kph: numeric("Dyn4_FRE.P265_VehV_VPsvValWhlBckL") ?? fiatWheelSpeeds[2],
    wheel_rear_right_kph: numeric("Dyn4_FRE.P266_VehV_VPsvValWhlBckR") ?? fiatWheelSpeeds[3],
  };
  const availableFields = Object.entries(point)
    .filter(([key, value]) => !["t_ms", "x_m", "y_m", "heading_deg", "distance_m"].includes(key) && value !== null && value !== undefined)
    .map(([key]) => key);
  return { point, availableFields };
}

export function liveGraphGeometry(points: ReplaySample[], definition: ReplayGaugeDefinition, windowSeconds: StudioGraphWindowSeconds): ReplayGraphGeometry {
  const commands: string[] = [];
  let drawing = false;
  const span = Math.max(.001, definition.maximum - definition.minimum);
  const windowMs = windowSeconds * 1000;
  const latestMs = points.at(-1)?.t_ms ?? 0;
  const startMs = latestMs - windowMs;
  points.filter((point) => point.t_ms >= startMs).forEach((point) => {
    const value = point[definition.key];
    if (typeof value !== "number") {
      drawing = false;
      return;
    }
    const x = Math.max(0, Math.min(900, (point.t_ms - startMs) / windowMs * 900));
    const y = 172 - (value - definition.minimum) / span * 164;
    commands.push(`${drawing ? "L" : "M"}${x.toFixed(1)},${Math.max(8, Math.min(172, y)).toFixed(1)}`);
    drawing = true;
  });
  return { path: commands.join(" "), minimum: definition.minimum, maximum: definition.maximum };
}

export function replayIndicatorState(
  definition: ReplayIndicatorDefinition,
  point: ReplaySample,
  replay: Pick<ReplayData, "available_fields">,
): ReplayIndicatorState {
  const available = definition.fields.some((field) => replay.available_fields.includes(String(field)));
  if (definition.referenceOnly || !available) {
    return { available: false, active: null, detail: "Signal non enregistré" };
  }
  switch (definition.key) {
    case "turn_left":
      return { available, active: ["left", "hazard"].includes(point.turn_signal ?? "off"), detail: point.turn_signal === "hazard" ? "Feux de détresse" : "Commande gauche" };
    case "turn_right":
      return { available, active: ["right", "hazard"].includes(point.turn_signal ?? "off"), detail: point.turn_signal === "hazard" ? "Feux de détresse" : "Commande droite" };
    case "low_beam":
      return { available, active: Boolean(point.low_beam), detail: point.low_beam ? "Allumés" : "Éteints" };
    case "high_beam":
      return { available, active: Boolean(point.high_beam), detail: point.high_beam ? "Allumés" : "Éteints" };
    case "parking_brake":
      return { available, active: Boolean(point.parking_brake), detail: point.parking_brake ? "Serré" : "Desserré" };
    case "brake_fault":
      return { available, active: Boolean(point.brake_fault), detail: point.brake_fault ? "Défaut demandé" : "Aucun défaut demandé" };
    case "abs":
      return { available, active: Boolean(point.abs_intervention), detail: point.abs_intervention ? "Intervention détectée" : "Pas d'intervention" };
    case "esp": {
      const fault = (point.esp_fault_state ?? 0) !== 0;
      const active = fault || Boolean(point.esp_intervention);
      return { available, active, detail: fault ? `Défaut brut ${point.esp_fault_state}` : point.esp_intervention ? "Intervention détectée" : "Veille" };
    }
    case "oil_pressure":
      return { available, active: Boolean(point.oil_pressure_switch), detail: point.oil_pressure_switch ? "Contacteur actif" : "Contacteur inactif" };
    case "coolant": {
      const temperature = point.coolant_temperature_c;
      return { available, active: typeof temperature === "number" ? temperature >= 115 : null, detail: typeof temperature === "number" ? `${temperature.toFixed(0)} °C · seuil visuel 115 °C` : "Valeur absente", inferred: true };
    }
    case "battery": {
      const voltage = point.battery_voltage_v;
      const running = (point.engine_rpm ?? 0) > 500;
      return { available, active: typeof voltage === "number" ? running && voltage < 12.2 : null, detail: typeof voltage === "number" ? `${voltage.toFixed(2)} V${running ? " moteur tournant" : ""}` : "Valeur absente", inferred: true };
    }
    case "fuel":
      return { available, active: Boolean(point.low_fuel_warning), detail: point.low_fuel_warning ? "Niveau minimal demandé" : "Réserve non demandée" };
    case "engine": {
      const active = Boolean(point.mil_on || point.mil_blinking || point.obd_error);
      return { available, active, detail: point.mil_blinking ? "MIL clignotant" : active ? "MIL / défaut OBD demandé" : "Témoin non demandé" };
    }
    case "door": {
      const labels = [point.driver_door ? "conducteur" : "", point.passenger_door ? "passager" : ""].filter(Boolean);
      return { available, active: labels.length > 0, detail: labels.length ? `Ouverte : ${labels.join(" + ")}` : "Portes avant fermées" };
    }
    case "rear_door": {
      const labels = [point.rear_left_door ? "arrière gauche" : "", point.rear_right_door ? "arrière droite" : ""].filter(Boolean);
      return { available, active: labels.length > 0, detail: labels.length ? `Ouverte : ${labels.join(" + ")}` : "Portes arrière fermées" };
    }
    case "rear_door_ajar_candidate":
      return { available, active: Boolean(point.rear_door_ajar_candidate), detail: point.rear_door_ajar_candidate ? "Au moins une porte arrière ouverte (candidat)" : "Portes arrière fermées (candidat)" };
    case "seatbelt":
      return { available, active: null, detail: `États bruts C ${point.driver_seatbelt_state ?? "—"} · P ${point.passenger_seatbelt_state ?? "—"}` };
    case "lane":
      return { available, active: Boolean(point.lka_active || point.lane_departure || point.lane_assist_status === 4), detail: point.lane_departure ? `Alerte ligne brute ${point.lane_departure}` : laneAssistStatusLabel(point.lane_assist_status) };
    case "lane_fault": {
      const active = point.lane_assist_status === 5 || point.lane_assist_status === 6;
      return { available, active, detail: laneAssistStatusLabel(point.lane_assist_status) };
    }
    case "reverse":
      return { available, active: Boolean(point.reverse || point.current_gear === 9), detail: point.reverse || point.current_gear === 9 ? "Rapport arrière" : "Inactive" };
    case "headlamp_fault":
      return { available, active: Boolean(point.headlamp_fault), detail: point.headlamp_fault ? "Défaut de lampe déclaré" : "Aucun défaut déclaré" };
    case "gearbox":
      return { available, active: Boolean(point.gearbox_fault), detail: point.gearbox_fault ? "Défaut système déclaré" : "Aucun défaut déclaré" };
    case "stop":
      return { available, active: Boolean(point.generic_warning_requested), detail: point.generic_warning_requested ? "Requête d'alerte active" : "Aucune requête" };
    default:
      return { available, active: null, detail: "État brut disponible" };
  }
}
