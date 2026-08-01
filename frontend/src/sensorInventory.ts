export type PowertrainProfile = "unknown" | "gasoline" | "diesel";
export type InventorySource = "can" | "psa";

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
  { id: "psa-lateral-accel", label: "Accélération latérale", system: "Freinage / châssis", description: "Accélération transversale utilisée par l'ESP.", source: "psa", priority: 1 },
  { id: "psa-yaw-rate", label: "Vitesse de lacet", system: "Freinage / châssis", description: "Rotation du véhicule autour de l'axe vertical.", source: "psa", priority: 1 },
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
  { id: "can-front-doors", label: "Portes avant", system: "Habitacle", description: "Ouverture conducteur et passager.", source: "can", liveFields: ["driver_door", "passenger_door"], priority: 1 },
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

  { id: "can-lane-assist", label: "Maintien dans la voie", system: "ADAS / stationnement", description: "Activation et alerte de franchissement.", source: "can", liveFields: ["lka_active", "lane_departure", "lane_assist_status"], optional: true, priority: 1 },
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

