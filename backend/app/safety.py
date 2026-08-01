from dataclasses import dataclass
from typing import Literal

READ_ONLY_UDS_SERVICES = {0x19, 0x22, 0x3E}
BLOCKED_UDS_SERVICES = {0x11, 0x14, 0x27, 0x2E, 0x2F, 0x31, 0x34, 0x36, 0x37}
READ_ONLY_DIAGNOSTIC_SESSIONS = {0x01, 0x03}
DIAGNOSTIC_REQUEST_IDS = {
    0x6A8,
    0x6A9,
    0x6AD,
    0x6B5,
    0x744,
    0x74A,
    0x752,
    0x75D,
    0x75F,
    0x764,
    0x76D,
    0x7B0,
    0x7E0,
}

TxSafetyProfile = Literal["diagnostic_read_only", "psa_lab"]

# Only named NAC/RCC actuator payloads documented by the referenced PSA
# diagnostic project are allowed in the experimental lab profile. Keeping the
# complete UDS payloads here prevents this mode from becoming a raw CAN sender.
PSA_LAB_NAC_REQUEST_ID = 0x764
PSA_LAB_ACTION_PAYLOADS = {
    bytes.fromhex("2FD6000300"),  # black screen
    bytes.fromhex("2FD60000"),    # restore screen
    bytes.fromhex("2FD66003"),    # camera display
    bytes.fromhex("2FD66000"),    # stop camera display
    bytes.fromhex("2FD6700330"),  # camera standard view
    bytes.fromhex("2FD6700340"),  # camera zoom view
    bytes.fromhex("2FD6700350"),  # camera lateral view
}
PSA_LAB_SECURITY_REQUEST_IDS = {0x752, 0x764}


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str


def authorize_transport_can_frame(
    profile: TxSafetyProfile,
    arbitration_id: int,
    extended: bool,
    data: bytes,
) -> SafetyDecision:
    if profile == "psa_lab":
        return authorize_psa_lab_can_frame(arbitration_id, extended, data)
    return authorize_diagnostic_can_frame(arbitration_id, extended, data)


def authorize_diagnostic_can_frame(
    arbitration_id: int,
    extended: bool,
    data: bytes,
) -> SafetyDecision:
    """Mirror the ESP32 read-only ISO-TP policy before bytes reach USB/Wi-Fi."""
    if extended:
        return SafetyDecision(False, "Identifiants CAN étendus verrouillés.")
    if arbitration_id not in DIAGNOSTIC_REQUEST_IDS:
        return SafetyDecision(False, f"Identifiant diagnostic 0x{arbitration_id:X} non autorisé.")
    if not data or len(data) > 8:
        return SafetyDecision(False, "Longueur de trame ISO-TP invalide.")

    pci_type = data[0] >> 4
    if pci_type == 0x3:
        if len(data) < 3 or (data[0] & 0x0F) > 0x02:
            return SafetyDecision(False, "Trame de contrôle de flux ISO-TP invalide.")
        return SafetyDecision(True, "Contrôle de flux ISO-TP autorisé.")
    if pci_type != 0x0:
        return SafetyDecision(False, "Requêtes diagnostic multi-trames verrouillées.")

    application_length = data[0] & 0x0F
    if application_length == 0 or application_length > 7 or len(data) < application_length + 1:
        return SafetyDecision(False, "Trame ISO-TP simple invalide.")
    service = data[1]

    if arbitration_id == 0x7E0:
        if service in {0x01, 0x09} and application_length == 2:
            return SafetyDecision(True, "Lecture OBD autorisée.")
        return SafetyDecision(False, "Seules les lectures OBD 01 et 09 sont autorisées sur 0x7E0.")

    uds_payload = data[1 : application_length + 1]
    return authorize_uds(uds_payload, read_only=True)


def authorize_psa_lab_can_frame(
    arbitration_id: int,
    extended: bool,
    data: bytes,
) -> SafetyDecision:
    """Authorize the firmware-mirrored PSA lab subset at CAN-frame level."""
    if extended:
        return SafetyDecision(False, "Identifiants CAN étendus verrouillés en mode PSA lab.")
    if arbitration_id not in DIAGNOSTIC_REQUEST_IDS:
        return SafetyDecision(False, f"Identifiant diagnostic 0x{arbitration_id:X} non autorisé.")
    if not data or len(data) > 8:
        return SafetyDecision(False, "Longueur de trame ISO-TP invalide.")

    pci_type = data[0] >> 4
    if pci_type == 0x3:
        if len(data) < 3 or (data[0] & 0x0F) > 0x02:
            return SafetyDecision(False, "Trame de contrôle de flux ISO-TP invalide.")
        return SafetyDecision(True, "Contrôle de flux ISO-TP autorisé.")
    if pci_type != 0x0:
        return SafetyDecision(False, "Requêtes diagnostic multi-trames verrouillées en mode PSA lab.")

    application_length = data[0] & 0x0F
    if application_length == 0 or application_length > 7 or len(data) < application_length + 1:
        return SafetyDecision(False, "Trame ISO-TP simple invalide.")
    payload = data[1 : application_length + 1]
    return authorize_psa_lab_uds(arbitration_id, payload)


def authorize_psa_lab_uds(arbitration_id: int, payload: bytes) -> SafetyDecision:
    """Allow reads plus an exact, named PSA/NAC experimental command set."""
    if not payload:
        return SafetyDecision(False, "Payload UDS vide.")

    readonly = authorize_uds(payload, read_only=True)
    if readonly.allowed:
        return readonly

    service = payload[0]
    if service == 0x27 and arbitration_id in PSA_LAB_SECURITY_REQUEST_IDS:
        if len(payload) == 2 and payload[1] == 0x03:
            return SafetyDecision(True, "Demande de seed de configuration PSA autorisée.")
        if len(payload) == 6 and payload[1] == 0x04:
            return SafetyDecision(True, "Réponse key de configuration PSA autorisée.")
        return SafetyDecision(False, "Seul l'accès sécurité PSA configuration 0x27/03-04 est autorisé.")

    if (
        service == 0x2F
        and arbitration_id == PSA_LAB_NAC_REQUEST_ID
        and payload in PSA_LAB_ACTION_PAYLOADS
    ):
        return SafetyDecision(True, "Commande NAC nommée autorisée par l'allowlist PSA lab.")

    return SafetyDecision(
        False,
        f"Service/payload UDS 0x{service:02X} absent de l'allowlist PSA lab.",
    )


def authorize_uds(
    payload: bytes,
    read_only: bool = True,
    *,
    maintenance: bool = False,
) -> SafetyDecision:
    if not payload:
        return SafetyDecision(False, "Payload UDS vide.")

    service = payload[0]
    if service == 0x14 and maintenance and not read_only:
        if len(payload) != 4:
            return SafetyDecision(False, "ClearDiagnosticInformation attend un groupe DTC sur 3 octets.")
        return SafetyDecision(True, "Effacement DTC autorisé par le mode maintenance explicite.")
    if service in BLOCKED_UDS_SERVICES:
        return SafetyDecision(False, f"Service UDS 0x{service:02X} bloqué.")

    if service == 0x10:
        if len(payload) < 2:
            return SafetyDecision(False, "Sous-fonction DiagnosticSessionControl manquante.")
        session = payload[1] & 0x7F
        if session not in READ_ONLY_DIAGNOSTIC_SESSIONS:
            return SafetyDecision(
                False,
                f"Session UDS 0x{session:02X} non autorisée en lecture seule.",
            )
        return SafetyDecision(True, "Session de diagnostic autorisée.")

    if read_only and service not in READ_ONLY_UDS_SERVICES:
        return SafetyDecision(False, f"Service UDS 0x{service:02X} non autorisé en lecture seule.")

    return SafetyDecision(True, "Commande autorisée.")


def authorize_obd(payload: bytes) -> SafetyDecision:
    if not payload:
        return SafetyDecision(False, "Payload OBD vide.")
    if payload[0] not in {0x01, 0x09}:
        return SafetyDecision(
            False,
            f"Mode OBD 0x{payload[0]:02X} non autorisé dans le mode capteurs.",
        )
    if len(payload) != 2:
        return SafetyDecision(False, "Une requête PID OBD doit contenir le mode et le PID.")
    return SafetyDecision(True, "Lecture PID OBD autorisée.")
