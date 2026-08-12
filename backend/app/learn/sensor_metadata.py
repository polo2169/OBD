from __future__ import annotations

from pathlib import Path
import json
import re
import threading

from app.config import settings
from app.learn.models import PassiveSensorOverride


_LOCK = threading.Lock()


# Libellés vérifiés ou suffisamment explicites pour l'atelier. Les signaux non
# répertoriés restent visibles avec une explication générique et leur nom DBC.
SENSOR_METADATA: dict[str, tuple[str, str, bool]] = {
    "STEERING_ALT.ANGLE": (
        "Angle du volant",
        "Position angulaire du volant. Zéro proche des roues droites; le signe indique le sens.",
        True,
    ),
    "STEERING_ALT.RATE": (
        "Vitesse de rotation du volant",
        "Vitesse instantanée à laquelle le volant est tourné.",
        True,
    ),
    "STEERING.DRIVER_TORQUE": (
        "Effort du conducteur au volant",
        "Effort détecté sur la colonne de direction; ce n'est pas un couple calibré en N·m.",
        True,
    ),
    "Dyn_CMM.P000_Com_nEng": (
        "Régime moteur",
        "Vitesse de rotation du moteur mesurée par le calculateur moteur.",
        True,
    ),
    "Dyn_CMM.P002_Com_rAPP": (
        "Pédale d'accélérateur",
        "Enfoncement demandé par le conducteur, exprimé en pourcentage.",
        True,
    ),
    "Dyn_CMM.P003_Com_trqActOut": (
        "Couple moteur réel",
        "Estimation du couple actuellement fourni par le moteur.",
        True,
    ),
    "Dat_CMM.P022_Com_nSetPLo": (
        "Consigne de ralenti",
        "Régime de ralenti demandé par le calculateur moteur; concordance validée avec le régime réel sur cette 308.",
        True,
    ),
    "Dyn2_FRE.P226_Com_stBrkActv": (
        "Frein actif",
        "État logique indiquant une demande ou une action de freinage.",
        True,
    ),
    "Dyn2_FRE.BRAKE_PRESSURE": (
        "Pression de freinage brute",
        "Mesure de pression du circuit de freinage. L'échelle exacte reste à valider sur cette 308.",
        True,
    ),
    "Dyn2_FRE.LATERAL_ACCELERATION": (
        "Accélération latérale",
        "Accélération transversale du véhicule, validée sur cette 308 par comparaison avec les quatre roues et le volant.",
        True,
    ),
    "Dyn2_FRE.YAW_RATE": (
        "Vitesse de lacet",
        "Rotation du véhicule autour de l’axe vertical, validée sur cette 308 par deux références CAN indépendantes.",
        True,
    ),
    "Dyn2_CMM.P026_Com_bESPAck": (
        "ESP reconnu par le moteur",
        "Acquittement moteur/ESP présent dans les 469 307 trames locales examinées; aucune transition n'a été observée.",
        False,
    ),
    "Dyn2_CMM.P025_Com_stESPErr": (
        "État de défaut ESP côté moteur",
        "État brut sur deux bits. Il est resté à 0 dans les captures locales; aucun défaut réel n'a permis de valider les autres états.",
        False,
    ),
    "Dyn_CDS.P047_Com_stESPIntv": (
        "État brut d'intervention ESP",
        "État 0 presque constant et état 6 observé sur deux trames. L'énumération détaillée reste inconnue.",
        False,
    ),
    "Dyn_CDS.P147_Com_bESPIntvActv": (
        "Intervention ESP active",
        "Bit documenté mais resté inactif dans 477 639 trames locales; l'état actif n'est pas encore testé sur cette voiture.",
        False,
    ),
    "Dyn_CDS.P352_StbIntv_bTCSIntvActv": (
        "Antipatinage TCS actif",
        "Bit documenté mais resté inactif dans 477 639 trames locales; une perte d'adhérence contrôlée serait nécessaire pour le valider.",
        False,
    ),
    "Dyn_CDS.P353_StbIntv_bESPExclvIntvActv": (
        "Correction ESP exclusive active",
        "Bit documenté mais resté inactif dans 477 639 trames locales; état actif non testé.",
        False,
    ),
    "Dat_ABR.P351_Com_bABSIntvActv": (
        "Intervention ABS active",
        "Bit documenté mais resté inactif dans 95 515 trames locales; aucun freinage déclenchant l'ABS n'a été enregistré.",
        False,
    ),
    "HS2_DYN_ABR_38D.VITESSE_VEHICULE_ROUES": (
        "Vitesse véhicule par les roues",
        "Vitesse calculée par l'ABS à partir des capteurs de roues.",
        True,
    ),
    "Dyn2_CMM.P152_Gearbx_stGear": ("Rapport EAT6 engagé", "Codage T9 validé sur 0x348 : 0 neutre/aucun rapport avant, 1 à 6 marche avant, 9 marche arrière.", True),
    "Dyn4_FRE.P263_VehV_VPsvValWhlFrtL": ("Vitesse roue avant gauche", "Vitesse individuelle mesurée par l'ABS.", True),
    "Dyn4_FRE.P264_VehV_VPsvValWhlFrtR": ("Vitesse roue avant droite", "Vitesse individuelle mesurée par l'ABS.", True),
    "Dyn4_FRE.P265_VehV_VPsvValWhlBckL": ("Vitesse roue arrière gauche", "Vitesse individuelle mesurée par l'ABS.", True),
    "Dyn4_FRE.P266_VehV_VPsvValWhlBckR": ("Vitesse roue arrière droite", "Vitesse individuelle mesurée par l'ABS.", True),
    "Dat_BSI.P103_Com_bRevGear": ("Marche arrière", "Indique que la marche arrière est engagée.", True),
    "Dyn_EasyMove.P337_Com_stPrkBrk": ("Frein de stationnement", "État 0x3AD validé sur la 308 : 0 relâché, 1 serré, 2 réservé/transition et 3 actionneur en mouvement.", True),
    "Dat_BSI.PARKING_BRAKE": ("Frein de stationnement (secours)", "Bit 0x412 source-confirmé mais jamais actif dans les captures locales; 0x3AD est la source T9 prioritaire.", False),
    "Dat_BSI.P013_MainBrake": ("Pédale de frein", "Contact principal de la pédale de frein.", True),
    "Dat_BSI.DRIVER_DOOR": ("Porte conducteur", "État d'ouverture validé dans 0x412, octet 6 masque 0x08.", True),
    "Dat_BSI.PASSENGER_DOOR": ("Porte passager", "État d'ouverture de la porte passager.", True),
    "HS2_DAT_MDD_CMD_452.TURN_SIGNAL_STATUS": ("Clignotants", "État de la commande des clignotants.", True),
    "HS2_DAT_MDD_CMD_452.FRONT_WIPER_STATUS": ("Essuie-glace avant", "État courant de l'essuie-glace avant.", True),
    "HS2_DAT7_BSI_612.ETAT_FEUX_ROUTE": ("Feux de route", "État des feux de route.", True),
    "HS2_DAT7_BSI_612.ETAT_FEUX_CROIST": ("Feux de croisement", "État des feux de croisement.", True),
    "HS2_DAT7_BSI_612.INFO_NIV_CARB": (
        "Niveau carburant brut",
        "Mesure du flotteur sensible au ballottement : sa forte corrélation avec l’accélération longitudinale impose un filtrage avant affichage.",
        True,
    ),
    "Dat_CMM.P021_Com_volFlCons": (
        "Consommation passive — décodage rejeté",
        "Ne suit ni le régime, ni la pédale, ni le couple sur cette 308; ce champ ne doit pas être interprété comme une consommation.",
        False,
    ),
    "Dat2_CMM.P316_FlSys_volFlConsVirt": (
        "Consommation virtuelle — indisponible",
        "Champ constamment nul pendant l’essai routier; aucune information de consommation n’est fournie.",
        False,
    ),
    "Dat2_CMM.P278_Oil_stPSwmp": (
        "Alerte de pression d’huile",
        "Contacteur logique validé; actif moteur arrêté, inactif moteur tournant. Il ne fournit aucune pression en bar.",
        True,
    ),
    "LANE_KEEP_ASSIST.STATUS": ("État maintien dans la voie", "État diffusé par la fonction : 0 indisponible, 1 non sélectionné, 2 sélectionné, 3 autorisé, 4 actif, 5 défaut, 6 collision.", True),
    "LANE_KEEP_ASSIST.LANE_DEPARTURE": ("Alerte franchissement de ligne", "Indique une détection de sortie de voie.", True),
    "LANE_KEEP_ASSIST.LXA_ACTIVATION": ("Mode d'aide de voie", "Sélection de fonction : 0 = LKA, 1 = LPA. Ce bit ne signifie pas que la direction est active.", True),
    "LANE_KEEP_ASSIST.SET_ANGLE": ("Consigne d'angle LKA", "Angle de colonne demandé par la chaîne caméra/BSI/EPS. Sur les captures locales en défaut, il reste à zéro car STATUS n'atteint jamais l'état 4 actif.", True),
    "LANE_KEEP_ASSIST.TORQUE_FACTOR": ("Facteur de couple LKA brut", "Facteur de limitation associé à la commande LKA. Son échelle physique n'est pas encore validée sur cette 308.", True),
    "Dat_CLIM.P221_Speed_setPoint_Typ": ("Mode régulateur / limiteur", "Position du sélecteur validée sur cette 308 : 0 arrêt, 1 régulateur RVV, 2 limiteur LVV.", True),
    "RESTRAINTS.DRIVER_SEATBELT": ("Ceinture conducteur", "État validé dans 0x572 : 1 débouclée, 2 bouclée; 0 et 3 restent réservés.", True),
    "RESTRAINTS.PASSENGER_SEATBELT": ("Ceinture passager", "État de boucle de la ceinture passager.", True),
    "Dyn5_CMM.P334_ACCPed_Position": ("Position accélérateur", "Position de la pédale d'accélérateur diffusée par le moteur.", True),
}


TOKEN_LABELS = {
    "ANGLE": "Angle",
    "RATE": "Vitesse de variation",
    "SPEED": "Vitesse",
    "PRESSURE": "Pression",
    "TORQUE": "Couple",
    "STATUS": "État",
    "FAULT": "Défaut",
    "FRONT": "avant",
    "REAR": "arrière",
    "LEFT": "gauche",
    "RIGHT": "droite",
    "DRIVER": "conducteur",
    "PASSENGER": "passager",
    "DOOR": "porte",
}


def _path() -> Path:
    path = settings.sensor_overrides_file
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


def load_overrides() -> dict[str, PassiveSensorOverride]:
    path = _path()
    with _LOCK:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, PassiveSensorOverride] = {}
    for key, value in payload.items():
        try:
            result[key] = PassiveSensorOverride.model_validate({"key": key, **value})
        except (TypeError, ValueError):
            continue
    return result


def save_override(override: PassiveSensorOverride) -> PassiveSensorOverride:
    overrides = load_overrides()
    overrides[override.key] = override
    _write_overrides(overrides)
    return override


def delete_override(key: str) -> bool:
    overrides = load_overrides()
    existed = overrides.pop(key, None) is not None
    if existed:
        _write_overrides(overrides)
    return existed


def _write_overrides(overrides: dict[str, PassiveSensorOverride]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: value.model_dump(exclude={"key"}, exclude_none=True)
        for key, value in sorted(overrides.items())
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)


def metadata_for(key: str, message: str, signal: str) -> tuple[str, str, bool]:
    known = SENSOR_METADATA.get(key)
    if known:
        return known
    cleaned = re.sub(r"^P\d+_", "", signal)
    tokens = [TOKEN_LABELS.get(token.upper(), token.lower()) for token in cleaned.split("_") if token]
    label = " ".join(tokens).strip().capitalize() or signal
    return (
        label,
        f"Signal {signal} du message CAN {message}. Interprétation OpenDBC à confirmer sur Peugeot 308 T9.",
        False,
    )
