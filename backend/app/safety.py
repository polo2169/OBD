from dataclasses import dataclass

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
    0x7E0,
}


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str


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
