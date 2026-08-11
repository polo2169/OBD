export type PowertrainProfile = "unknown" | "gasoline" | "diesel";
export type InventorySource = "can" | "psa" | "fiat";

export type VehicleSensorCandidate = {
  id: string;
  label: string;
  system: string;
  description: string;
  source: InventorySource;
  liveFields?: string[];
  applicability?: "all" | "gasoline" | "diesel";
  optional?: boolean;
  priority: 1 | 2 | 3;
};

// Ce catalogue décrit les informations utiles à l'atelier, pas uniquement les
// composants physiques. Une valeur peut provenir d'un capteur, d'un état ECU ou
// d'un calcul interne. Les entrées CAN déjà décodées sont rapprochées des champs
// du direct; les entrées PSA nécessitent encore un DID ou une trame validée.
export const vehicleSensorCandidates: VehicleSensorCandidate[] = [
  { id: "can-engine-rpm", label: "Régime moteur", system: "Moteur / injection", description: "Vitesse de rotation du vilebrequin.", source: "can", liveFields: ["engine_rpm"], priority: 1 },
  { id: "can-accelerator", label: "Pédale d'accélérateur", system: "Moteur / injection", description: "Demande conducteur en pourcentage.", source: "can", liveFields: ["accelerator_pct"], priority: 1 },
  { id: "can-engine-torque", label: "Couple moteur réel", system: "Moteur / injection", description: "Estimation de couple produite par le calculateur moteur.", source: "can", liveFields: ["engine_torque_nm"], priority: 1 },
  { id: "can-oil-temperature", label: "Température d'huile", system: "Moteur / injection", description: "Température du carter moteur.", source: "can", liveFields: ["oil_temperature_c"], priority: 1 },
  { id: "can-coolant-temperature", label: "Température de liquide de refroidissement", system: "Moteur / injection", description: "Température moteur principale.", source: "can", liveFields: ["coolant_temperature_c"], priority: 1 },
  { id: "can-intake-temperature", label: "Température d'air d'admission", system: "Moteur / injection", description: "Température mesurée à l'admission.", source: "can", liveFields: ["intake_air_temperature_c"], priority: 1 },
  { id: "can-oil-switch", label: "Contacteur de pression d'huile", system: "Moteur / injection", description: "État logique uniquement, sans valeur en bar.", source: "can", liveFields: ["oil_pressure_switch"], priority: 1 },
  { id: "can-atmospheric-pressure", label: "Pression atmosphérique", system: "Moteur / injection", description: "Pression environnementale utilisée par l'ECU.", source: "can", liveFields: ["atmospheric_pressure_hpa"], priority: 2 },
  { id: "psa-injector-correction-1", label: "Correction injecteur cylindre 1", system: "Moteur / injection", description: "Équilibrage individuel de combustion.", source: "psa", priority: 1 },
  { id: "psa-injector-correction-2", label: "Correction injecteur cylindre 2", system: "Moteur / injection", description: "Équilibrage individuel de combustion.", source: "psa", priority: 1 },
  { id: "psa-injector-correction-3", label: "Correction injecteur cylindre 3", system: "Moteur / injection", description: "Équilibrage individuel de combustion.", source: "psa", priority: 1 },
  { id: "psa-injector-correction-4", label: "Correction injecteur cylindre 4", system: "Moteur / injection", description: "Équilibrage individuel de combustion.", source: "psa", priority: 1 },
  { id: "psa-injection-quantity", label: "Quantité injectée", system: "Moteur / injection", description: "Masse de carburant injectée par cycle.", source: "psa", priority: 1 },
  { id: "psa-injection-duration", label: "Durée d'injection", system: "Moteur / injection", description: "Durée de commande des injecteurs.", source: "psa", priority: 1 },
  { id: "psa-injection-phases", label: "Pré/main/post-injections", system: "Moteur / injection", description: "Nombre et répartition des phases d'injection.", source: "psa", applicability: "diesel", priority: 2 },
  { id: "psa-rail-target", label: "Consigne de pression de rampe", system: "Moteur / injection", description: "Pression demandée par la stratégie d'injection.", source: "psa", priority: 1 },
  { id: "psa-rail-regulator", label: "Commande régulateur de rampe", system: "Moteur / injection", description: "Rapport cyclique du régulateur ou de la pompe haute pression.", source: "psa", priority: 1 },
  { id: "psa-low-fuel-pressure", label: "Pression carburant basse pression", system: "Moteur / injection", description: "Alimentation amont de la pompe haute pression.", source: "psa", priority: 1 },
  { id: "psa-fuel-temperature", label: "Température carburant", system: "Moteur / injection", description: "Température utilisée pour corriger la quantité injectée.", source: "psa", priority: 2 },
  { id: "psa-oil-pressure", label: "Pression d'huile réelle", system: "Moteur / injection", description: "Valeur analogique en bar si le moteur possède le capteur.", source: "psa", priority: 1, optional: true },
  { id: "psa-oil-level", label: "Niveau d'huile mesuré", system: "Moteur / injection", description: "Mesure de niveau au démarrage, distincte du simple état d'alerte.", source: "psa", priority: 2 },
  { id: "psa-turbo-target", label: "Consigne de suralimentation", system: "Moteur / injection", description: "Pression turbo demandée par l'ECU.", source: "psa", priority: 1 },
  { id: "psa-turbo-actuator", label: "Position actionneur turbo", system: "Moteur / injection", description: "Géométrie variable ou wastegate commandée/réelle.", source: "psa", priority: 1 },
  { id: "psa-airflow-target", label: "Consigne de débit d'air", system: "Moteur / injection", description: "Masse d'air demandée comparée au débitmètre.", source: "psa", priority: 2 },
  { id: "psa-swirl", label: "Volets d'admission / swirl", system: "Moteur / injection", description: "Position commandée et retour des volets si équipés.", source: "psa", priority: 2, optional: true },
  { id: "psa-cam-crank-sync", label: "Synchronisation AAC / vilebrequin", system: "Moteur / injection", description: "État de synchronisation des capteurs de phase et régime.", source: "psa", priority: 2 },
  { id: "psa-misfire-count", label: "Compteurs de ratés par cylindre", system: "Moteur / injection", description: "Ratés de combustion reconnus par l'ECU.", source: "psa", applicability: "gasoline", priority: 1 },
  { id: "psa-knock", label: "Retard cliquetis", system: "Moteur / injection", description: "Correction d'allumage due au cliquetis.", source: "psa", applicability: "gasoline", priority: 2 },
  { id: "psa-fan-command", label: "Consigne et vitesse ventilateur moteur", system: "Moteur / injection", description: "Demande ECU et retour du groupe motoventilateur.", source: "psa", priority: 2 },

  { id: "psa-egr-target", label: "Consigne EGR", system: "Dépollution", description: "Ouverture demandée de la vanne EGR.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-egr-position", label: "Position réelle EGR", system: "Dépollution", description: "Retour de position comparé à la consigne.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-exhaust-temperature-turbo", label: "Température échappement avant turbo", system: "Dépollution", description: "Protection thermique du turbo.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-exhaust-temperature-dpf-in", label: "Température entrée FAP", system: "Dépollution", description: "Température utilisée pendant la régénération.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-exhaust-temperature-dpf-out", label: "Température sortie FAP", system: "Dépollution", description: "Température aval du filtre à particules.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-dpf-pressure", label: "Pression différentielle FAP", system: "Dépollution", description: "Différence de pression amont/aval du filtre.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-dpf-soot", label: "Charge de suie FAP", system: "Dépollution", description: "Masse ou pourcentage de suie calculé.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-dpf-ash", label: "Charge de cendres FAP", system: "Dépollution", description: "Vieillissement non brûlable estimé du filtre.", source: "psa", applicability: "diesel", priority: 2 },
  { id: "psa-dpf-regeneration", label: "État de régénération FAP", system: "Dépollution", description: "Inactive, demandée, active, terminée ou interrompue.", source: "psa", applicability: "diesel", priority: 1 },
  { id: "psa-dpf-distance", label: "Distance depuis dernière régénération", system: "Dépollution", description: "Distance et durée depuis le dernier cycle réussi.", source: "psa", applicability: "diesel", priority: 2 },
  { id: "psa-eolys-level", label: "Niveau additif Eolys", system: "Dépollution", description: "Quantité estimée d'additif FAP.", source: "psa", applicability: "diesel", optional: true, priority: 2 },
  { id: "psa-adblue-level", label: "Niveau AdBlue", system: "Dépollution", description: "Niveau ou autonomie du réservoir SCR.", source: "psa", applicability: "diesel", optional: true, priority: 1 },
  { id: "psa-adblue-pressure", label: "Pression circuit AdBlue", system: "Dépollution", description: "Pression de pompe et dosage SCR.", source: "psa", applicability: "diesel", optional: true, priority: 1 },
  { id: "psa-nox-upstream", label: "NOx amont SCR", system: "Dépollution", description: "Concentration NOx avant catalyseur SCR.", source: "psa", applicability: "diesel", optional: true, priority: 1 },
  { id: "psa-nox-downstream", label: "NOx aval SCR", system: "Dépollution", description: "Concentration NOx après traitement.", source: "psa", applicability: "diesel", optional: true, priority: 1 },
  { id: "psa-lambda", label: "Sonde lambda réelle", system: "Dépollution", description: "Richesse ou excès d'air mesuré à l'échappement.", source: "psa", priority: 1 },

  { id: "can-current-gear", label: "Rapport engagé", system: "Transmission", description: "Rapport courant reconnu par le groupe motopropulseur.", source: "can", liveFields: ["current_gear"], priority: 1 },
  { id: "can-target-gear", label: "Rapport cible", system: "Transmission", description: "Rapport demandé pendant un changement.", source: "can", liveFields: ["target_gear"], priority: 2 },
  { id: "psa-gearbox-temperature", label: "Température d'huile de boîte", system: "Transmission", description: "Température interne de boîte automatique si équipée.", source: "psa", optional: true, priority: 1 },
  { id: "psa-clutch-slip", label: "Glissement embrayage / convertisseur", system: "Transmission", description: "Différence de régime entrée/sortie.", source: "psa", optional: true, priority: 2 },
  { id: "psa-selector", label: "Position détaillée du sélecteur", system: "Transmission", description: "P/R/N/D/M et demandes conducteur.", source: "psa", optional: true, priority: 2 },

  { id: "can-speed", label: "Vitesse véhicule", system: "Freinage / châssis", description: "Vitesse calculée à partir des roues ABS.", source: "can", liveFields: ["speed_kph"], priority: 1 },
  { id: "can-wheel-speeds", label: "Vitesses des quatre roues", system: "Freinage / châssis", description: "Vitesses individuelles avant/arrière gauche/droite.", source: "can", liveFields: ["wheel_front_left_kph", "wheel_front_right_kph", "wheel_rear_left_kph", "wheel_rear_right_kph"], priority: 1 },
  { id: "can-brake-state", label: "Pédale et état de freinage", system: "Freinage / châssis", description: "Contact de pédale et activation du freinage.", source: "can", liveFields: ["brake_active", "brake_system_state"], priority: 1 },
  { id: "can-brake-pressure", label: "Pression de freinage brute", system: "Freinage / châssis", description: "Signal observé mais pas encore calibré en bar.", source: "can", liveFields: ["brake_pressure_raw"], priority: 1 },
  { id: "can-longitudinal-accel", label: "Accélération longitudinale", system: "Freinage / châssis", description: "Accélération selon l'axe du véhicule.", source: "can", liveFields: ["longitudinal_accel_ms2"], priority: 2 },
  { id: "psa-brake-pressure-bar", label: "Pression de freinage calibrée", system: "Freinage / châssis", description: "Conversion validée en bar.", source: "psa", priority: 1 },
  { id: "can-lateral-accel", label: "Accélération latérale", system: "Freinage / châssis", description: "Accélération transversale ESP validée sur les captures de cette 308.", source: "can", liveFields: ["lateral_accel_ms2"], priority: 1 },
  { id: "can-yaw-rate", label: "Vitesse de lacet", system: "Freinage / châssis", description: "Rotation autour de l'axe vertical, validée par comparaison avec le volant et les roues.", source: "can", liveFields: ["yaw_rate_deg_s"], priority: 1 },
  { id: "can-esp-state", label: "Interventions ESP / antipatinage", system: "Freinage / châssis", description: "État brut et bits ESP/TCS disponibles; aucun état actif observé sur 477 639 trames.", source: "can", liveFields: ["esp_intervention_state", "esp_intervention", "tcs_intervention", "esp_exclusive_intervention"], priority: 1 },
  { id: "can-abs-intervention", label: "Intervention ABS", system: "Freinage / châssis", description: "Bit ABS disponible; état actif non observé sur 95 515 trames.", source: "can", liveFields: ["abs_intervention"], priority: 1 },
  { id: "psa-wheel-slip", label: "Glissement de chaque roue", system: "Freinage / châssis", description: "Écart roue/véhicule pendant ABS ou antipatinage.", source: "psa", priority: 2 },

  { id: "can-steering-angle", label: "Angle volant", system: "Direction", description: "Angle et sens du volant validés sur le véhicule.", source: "can", liveFields: ["steering_angle_deg"], priority: 1 },
  { id: "can-steering-rate", label: "Vitesse de rotation volant", system: "Direction", description: "Variation angulaire du volant.", source: "can", liveFields: ["steering_rate_deg_s"], priority: 1 },
  { id: "can-driver-torque", label: "Effort conducteur au volant", system: "Direction", description: "Effort brut mesuré sur la colonne.", source: "can", liveFields: ["driver_torque"], priority: 1 },
  { id: "psa-eps-assist", label: "Couple d'assistance EPS", system: "Direction", description: "Couple demandé et réellement fourni par la direction assistée.", source: "psa", priority: 2 },
  { id: "psa-rack-position", label: "Position de crémaillère", system: "Direction", description: "Position ou angle de route distinct de l'angle volant.", source: "psa", optional: true, priority: 3 },

  { id: "can-battery-voltage", label: "Tension batterie", system: "Électricité", description: "Tension du réseau 12 V.", source: "can", liveFields: ["battery_voltage_v"], priority: 1 },
  { id: "can-battery-charge", label: "État de charge batterie", system: "Électricité", description: "SOC calculé par le BSI.", source: "can", liveFields: ["battery_charge_pct"], priority: 1 },
  { id: "can-battery-temperature", label: "Température batterie", system: "Électricité", description: "Température estimée ou mesurée au niveau de la batterie.", source: "can", liveFields: ["battery_temperature_c"], priority: 2 },
  { id: "psa-battery-current", label: "Courant batterie", system: "Électricité", description: "Courant entrant ou sortant mesuré par l'IBS.", source: "psa", priority: 1 },
  { id: "psa-battery-health", label: "État de santé batterie", system: "Électricité", description: "SOH, résistance interne et tension à vide.", source: "psa", priority: 2 },
  { id: "psa-alternator", label: "Consigne et charge alternateur", system: "Électricité", description: "Tension cible et courant de production.", source: "psa", priority: 1 },

  { id: "can-turn-signals", label: "Clignotants", system: "Habitacle", description: "Commande gauche, droite et feux de détresse.", source: "can", liveFields: ["turn_signal"], priority: 1 },
  { id: "can-headlamps", label: "Feux de croisement et route", system: "Habitacle", description: "États d'éclairage avant.", source: "can", liveFields: ["low_beam", "high_beam"], priority: 1 },
  { id: "can-front-doors", label: "Portes avant", system: "Habitacle", description: "Conducteur validé sur 0x412 octet 6 masque 0x08; état passager issu de la même trame.", source: "can", liveFields: ["driver_door", "passenger_door"], priority: 1 },
  { id: "can-parking-brake", label: "Frein de stationnement", system: "Habitacle", description: "0x412 octet 0 masque 0x08; définition amont confirmée, état actif non encore observé localement.", source: "can", liveFields: ["parking_brake"], priority: 1 },
  { id: "can-driver-seatbelt", label: "Ceinture conducteur", system: "Habitacle", description: "0x572 octet 0 bits 7-6 : 1 débouclée, 2 bouclée, validé par bascules répétées à l'arrêt.", source: "can", liveFields: ["driver_seatbelt_state"], priority: 1 },
  { id: "can-wipers", label: "Essuie-glace avant", system: "Habitacle", description: "État de commande de l'essuie-glace.", source: "can", liveFields: ["front_wiper_status"], priority: 2 },
  { id: "psa-rear-doors", label: "Portes arrière", system: "Habitacle", description: "Ouverture arrière gauche et droite.", source: "psa", priority: 2 },
  { id: "psa-tailgate", label: "Coffre / hayon", system: "Habitacle", description: "État d'ouverture et de verrouillage.", source: "psa", priority: 2 },
  { id: "psa-bonnet", label: "Capot moteur", system: "Habitacle", description: "Contacteur d'ouverture de capot.", source: "psa", optional: true, priority: 2 },
  { id: "psa-windows", label: "Position des vitres", system: "Habitacle", description: "Position et mouvement des quatre lève-vitres.", source: "psa", priority: 3 },
  { id: "psa-central-locking", label: "Verrouillage centralisé", system: "Habitacle", description: "États de serrure et supercondamnation.", source: "psa", priority: 2 },
  { id: "psa-mirrors", label: "Rétroviseurs", system: "Habitacle", description: "Rabattement, réglage et chauffage gauche/droite.", source: "psa", optional: true, priority: 1 },
  { id: "psa-rain-light", label: "Capteur pluie / luminosité", system: "Habitacle", description: "Intensité de pluie et luminosité ambiante.", source: "psa", optional: true, priority: 2 },
  { id: "psa-washer-level", label: "Niveau de lave-glace", system: "Habitacle", description: "Alerte de niveau bas si le véhicule est équipé.", source: "psa", optional: true, priority: 3 },

  { id: "can-ambient-temperature", label: "Température extérieure", system: "Climatisation", description: "Température ambiante diffusée sur le réseau.", source: "can", liveFields: ["ambient_temperature_c"], priority: 2 },
  { id: "psa-cabin-temperature", label: "Température habitacle", system: "Climatisation", description: "Sonde intérieure utilisée par la régulation.", source: "psa", priority: 1 },
  { id: "psa-evaporator-temperature", label: "Température évaporateur", system: "Climatisation", description: "Protection contre le givrage.", source: "psa", priority: 2 },
  { id: "psa-refrigerant-pressure", label: "Pression réfrigérant", system: "Climatisation", description: "Pression du circuit haute pression.", source: "psa", priority: 1 },
  { id: "psa-sunlight", label: "Ensoleillement", system: "Climatisation", description: "Charge solaire gauche/droite si disponible.", source: "psa", optional: true, priority: 3 },
  { id: "psa-blower", label: "Vitesse pulseur", system: "Climatisation", description: "Consigne et retour du ventilateur habitacle.", source: "psa", priority: 2 },
  { id: "psa-flaps", label: "Position des volets de climatisation", system: "Climatisation", description: "Mixage, distribution et recyclage.", source: "psa", priority: 3 },

  { id: "can-lane-assist", label: "Maintien dans la voie", system: "ADAS / stationnement", description: "Commande de couple signée R2/EVO observée sur 0x3F2, état LKA/LPA, consigne d'angle et alerte de franchissement.", source: "can", liveFields: ["lka_active", "lka_mode", "lka_torque_command_raw", "lka_angle_setpoint_deg", "lka_torque_factor_raw", "lane_departure", "lane_assist_status"], optional: true, priority: 1 },
  { id: "can-cruise-stalk", label: "Commodo régulateur", system: "ADAS / stationnement", description: "ON, SET+, SET−, RESUME et CANCEL reconstruits depuis 0x50E et 0x208.", source: "can", liveFields: ["cruise_mode_raw", "cruise_on", "cruise_activation_request", "cruise_button_event", "cruise_setpoint_kph"], optional: true, priority: 1 },
  { id: "can-acc", label: "Régulation adaptative", system: "ADAS / stationnement", description: "Mode ACC, activation et consigne de vitesse.", source: "can", liveFields: ["acc_mode", "acc_requested", "speed_setpoint_kph"], optional: true, priority: 1 },
  { id: "psa-radar-target", label: "Cible radar principale", system: "ADAS / stationnement", description: "Distance, vitesse relative et angle de la cible.", source: "psa", optional: true, priority: 1 },
  { id: "psa-lane-model", label: "Modèle détaillé des lignes", system: "ADAS / stationnement", description: "Courbure, position et qualité des lignes gauche/droite.", source: "psa", optional: true, priority: 2 },
  { id: "psa-blind-spot", label: "Détection angle mort", system: "ADAS / stationnement", description: "Présence d'une cible gauche ou droite.", source: "psa", optional: true, priority: 1 },
  { id: "psa-collision-warning", label: "Alerte collision / freinage auto", system: "ADAS / stationnement", description: "Niveau d'alerte et demande AEB.", source: "psa", optional: true, priority: 1 },
  { id: "psa-parking-sensors", label: "Distances des capteurs de stationnement", system: "ADAS / stationnement", description: "Distance de chaque capteur ultrasonique avant/arrière.", source: "psa", optional: true, priority: 1 },
  { id: "psa-camera-state", label: "Caméra de recul", system: "ADAS / stationnement", description: "État, disponibilité et défauts de la caméra.", source: "psa", optional: true, priority: 2 },

  { id: "psa-tire-pressure", label: "Pression de chaque pneu", system: "Pneumatiques / position", description: "Pression individuelle si capteurs directs; sinon état indirect ABS.", source: "psa", optional: true, priority: 1 },
  { id: "psa-tire-temperature", label: "Température de chaque pneu", system: "Pneumatiques / position", description: "Température individuelle quand les valves la diffusent.", source: "psa", optional: true, priority: 2 },
  { id: "psa-gps-position", label: "Position GPS réelle", system: "Pneumatiques / position", description: "Latitude, longitude et précision de la navigation.", source: "psa", optional: true, priority: 1 },
  { id: "psa-gps-motion", label: "Cap, altitude et vitesse GPS", system: "Pneumatiques / position", description: "Mouvement absolu distinct de la trajectoire estimée.", source: "psa", optional: true, priority: 2 },
];

// Fiat 500 type 312 · 1.2 8V essence (véhicule 2010 actuellement utilisé).
// Les données OBD-II normalisées sont ajoutées séparément par le catalogue
// backend. Cette liste couvre les signaux CAN déjà prouvés et les grandeurs
// physiques que l'eLearn Fiat confirme au niveau du véhicule/ECU, sans
// prétendre connaître leur trame constructeur tant qu'elle n'a pas été captée.
export const fiat500SensorCandidates: VehicleSensorCandidate[] = [
  { id: "fiat-can-engine-rpm", label: "Régime moteur", system: "Moteur / injection", description: "Régime diffusé en CAN 29 bits et recoupé avec le PID EOBD 01/0C.", source: "can", liveFields: ["engine_rpm"], priority: 1 },
  { id: "fiat-map", label: "Pression collecteur d'admission", system: "Moteur / injection", description: "Mesure MAP testable en EOBD 01/0B; l'octet 4 de 0x0618A001 est conservé séparément comme charge d'air brute candidate.", source: "fiat", liveFields: ["manifold_pressure_kpa", "fiat_air_load_candidate_raw"], priority: 1 },
  { id: "fiat-intake-temperature", label: "Température d'air d'admission", system: "Moteur / injection", description: "Voie température du capteur d'admission combiné; testable en EOBD 01/0F.", source: "fiat", priority: 1 },
  { id: "fiat-coolant-temperature", label: "Température liquide de refroidissement", system: "Moteur / injection", description: "Sonde moteur utilisée par l'injection et le combiné; testable en EOBD 01/05.", source: "fiat", priority: 1 },
  { id: "fiat-throttle", label: "Position papillon motorisé", system: "Moteur / injection", description: "L'octet 7 de 0x0618A001 est un candidat papillon fortement corrélé; il doit être comparé aux positions EOBD 01/11, 01/45 et 01/47.", source: "fiat", liveFields: ["throttle_position_pct", "fiat_throttle_candidate_pct", "relative_throttle_position_pct", "throttle_position_b_pct"], priority: 1 },
  { id: "fiat-accelerator", label: "Pédale d'accélérateur · voies 1 et 2", system: "Moteur / injection", description: "Deux potentiomètres de demande conducteur; voies EOBD 01/49 et 01/4A lorsqu'elles sont exposées.", source: "fiat", priority: 1 },
  { id: "fiat-crank", label: "Capteur de régime vilebrequin", system: "Moteur / injection", description: "Source physique du régime et de la position vilebrequin; son état détaillé nécessite un paramètre constructeur.", source: "fiat", priority: 2 },
  { id: "fiat-cam", label: "Capteur de phase arbre à cames", system: "Moteur / injection", description: "Synchronisation de phase moteur; présence confirmée par l'architecture IAW5SF, valeur à décoder.", source: "fiat", priority: 2 },
  { id: "fiat-knock", label: "Capteur de cliquetis", system: "Moteur / injection", description: "Signal de détonation utilisé pour corriger l'avance; correction détaillée à identifier.", source: "fiat", applicability: "gasoline", priority: 2 },
  { id: "fiat-oil-switch", label: "Contacteur de pression d'huile", system: "Moteur / injection", description: "État logique d'alerte; ce moteur ne fournit pas nécessairement une pression analogique en bar.", source: "fiat", priority: 1 },
  { id: "fiat-brake-switch", label: "Contacteur de pédale de frein", system: "Commandes conducteur", description: "Deux états de frein transmis au calculateur moteur et au réseau CAN.", source: "fiat", priority: 1 },
  { id: "fiat-clutch-switch", label: "Contacteur de pédale d'embrayage", system: "Commandes conducteur", description: "Candidat 0x0628A001 octet 5 bit 5, présent dans la capture; à confirmer par trois appuis annotés.", source: "fiat", optional: true, priority: 2 },

  { id: "fiat-lambda-upstream", label: "Sonde lambda amont catalyseur", system: "Dépollution", description: "Sonde de régulation de richesse; tension EOBD candidate 01/14 selon les PID annoncés par l'ECU.", source: "fiat", applicability: "gasoline", priority: 1 },
  { id: "fiat-lambda-downstream", label: "Sonde lambda aval catalyseur", system: "Dépollution", description: "Contrôle de l'efficacité catalyseur; tension EOBD candidate 01/15.", source: "fiat", applicability: "gasoline", priority: 1 },
  { id: "fiat-fuel-trims", label: "Corrections de richesse court/long terme", system: "Dépollution", description: "Adaptations STFT/LTFT de la banque 1, normalisées par les PID 01/06 et 01/07.", source: "fiat", applicability: "gasoline", priority: 1 },
  { id: "fiat-evap-purge", label: "Commande purge canister", system: "Dépollution", description: "Commande de récupération des vapeurs d'essence; PID EOBD 01/2E si supporté.", source: "fiat", applicability: "gasoline", priority: 2 },
  { id: "fiat-catalyst-status", label: "État catalyseur et moniteurs OBD", system: "Dépollution", description: "Disponibilité et résultat des moniteurs antipollution issus du statut OBD normalisé.", source: "fiat", priority: 2 },

  { id: "fiat-vehicle-speed", label: "Vitesse véhicule", system: "Freinage / châssis", description: "Vitesse normalisée EOBD 01/0D, suffisante avec le GPS pour reconstruire un trajet.", source: "can", liveFields: ["speed_kph"], priority: 1 },
  { id: "fiat-wheel-speeds", label: "Vitesses des quatre roues", system: "Freinage / châssis", description: "Candidat 0x0218A006 observé : quatre mots 16 bits à résolution 1/16 km/h, avec 0x002C à l'arrêt; validation roulante requise.", source: "fiat", liveFields: ["wheel_front_left_kph", "wheel_front_right_kph", "wheel_rear_left_kph", "wheel_rear_right_kph"], priority: 1 },
  { id: "fiat-brake-pressure", label: "État / niveau brut de freinage", system: "Freinage / châssis", description: "Appui de pédale 0x0810A000 validé sur ce VIN; le niveau brut évolue avec l'appui mais n'est pas encore étalonné en bar.", source: "fiat", liveFields: ["brake_active", "brake_pressure_raw"], optional: true, priority: 2 },
  { id: "fiat-steering-angle", label: "Angle du volant", system: "Direction", description: "Disponible via le système ESP lorsque le véhicule en est équipé; indispensable à une reconstruction sans GPS.", source: "fiat", liveFields: ["steering_angle_deg"], optional: true, priority: 1 },
  { id: "fiat-yaw-lateral", label: "Lacet et accélération latérale", system: "Freinage / châssis", description: "Capteur combiné du système ESP; absent des versions sans ESP.", source: "fiat", liveFields: ["yaw_rate_deg_s", "lateral_accel_ms2"], optional: true, priority: 2 },

  { id: "fiat-battery-voltage", label: "Tension réseau 12 V", system: "Électricité", description: "Tension d'alimentation du calculateur, normalisée par le PID EOBD 01/42.", source: "can", liveFields: ["battery_voltage_v"], priority: 1 },
  { id: "fiat-charging", label: "État de charge alternateur", system: "Électricité", description: "Commande et état du circuit de charge; valeurs constructeur à identifier sur le CAN Fiat.", source: "fiat", priority: 2 },

  { id: "fiat-fuel-level", label: "Niveau de carburant", system: "Habitacle / Body Computer", description: "Flotteur traité par le Body Computer et le combiné; PID EOBD 01/2F seulement si l'ECU le relaie.", source: "fiat", liveFields: ["fuel_level_pct"], priority: 1 },
  { id: "fiat-doors", label: "Portes et hayon", system: "Habitacle / Body Computer", description: "Porte conducteur validée sur 0x0A18A000 octet 2 bit 3; autres ouvrants encore à identifier.", source: "fiat", liveFields: ["driver_door"], priority: 1 },
  { id: "fiat-lights", label: "Feux et clignotants", system: "Habitacle / Body Computer", description: "Commandes et retours d'éclairage nécessaires à l'animation de la vue du dessus.", source: "fiat", liveFields: ["turn_signal", "low_beam", "high_beam"], priority: 1 },
  { id: "fiat-wipers", label: "Essuie-glaces", system: "Habitacle / Body Computer", description: "Position du commodo et état de fonctionnement; trames B-CAN à identifier.", source: "fiat", liveFields: ["front_wiper_status"], priority: 2 },
  { id: "fiat-reverse-parking", label: "Marche arrière et frein à main", system: "Habitacle / Body Computer", description: "Frein à main candidat sur 0x0A18A000 octet 0 bit 5; marche arrière encore à identifier.", source: "fiat", liveFields: ["reverse", "parking_brake"], priority: 1 },
  { id: "fiat-city-defrost", label: "Mode City et dégivrage arrière", system: "Habitacle / Body Computer", description: "Bits candidats observés sur 0x0A18A000; à confirmer par actions annotées.", source: "fiat", priority: 2 },
  { id: "fiat-start-stop-state", label: "État et disponibilité Start&Stop", system: "Habitacle / Body Computer", description: "Candidats sur 0x0C1CA000, uniquement si la voiture est équipée du Start&Stop.", source: "fiat", optional: true, priority: 2 },
  { id: "fiat-network-clock", label: "Date et heure du véhicule", system: "Combiné d'instruments", description: "Horloge BCD candidate sur 0x0C28A000, cohérente avec la date de la capture.", source: "fiat", priority: 2 },
  { id: "fiat-odometer", label: "Kilométrage total", system: "Combiné d'instruments", description: "Valeur mémorisée par le combiné/Body Computer; lecture constructeur à documenter.", source: "fiat", priority: 2 },

  { id: "fiat-ambient-temperature", label: "Température extérieure", system: "Climatisation", description: "Sonde extérieure présente selon équipement; PID EOBD 01/46 seulement si relayé par le moteur.", source: "fiat", liveFields: ["ambient_temperature_c"], optional: true, priority: 2 },
  { id: "fiat-ac-pressure", label: "Pression de climatisation", system: "Climatisation", description: "Capteur de pression réfrigérant transmis à la gestion moteur; paramètre constructeur à identifier.", source: "fiat", optional: true, priority: 2 },
  { id: "fiat-ac-request", label: "Demande et activation climatisation", system: "Climatisation", description: "Demande conducteur, autorisation moteur et activation compresseur.", source: "fiat", optional: true, priority: 2 },

  { id: "fiat-gps-position", label: "Position GPS navigateur", system: "Trajet / position", description: "Latitude, longitude, précision et cap fournis par le navigateur pendant l'enregistrement.", source: "can", liveFields: ["latitude", "longitude", "gps_accuracy_m", "gps_heading_deg"], optional: true, priority: 1 },
];

export function sensorCandidatesForProfile(profileKey?: string | null): VehicleSensorCandidate[] {
  return profileKey === "fiat_500_generic" ? fiat500SensorCandidates : vehicleSensorCandidates;
}
