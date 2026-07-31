from dataclasses import dataclass

READ_ONLY_UDS_SERVICES = {0x19, 0x22, 0x23, 0x24, 0x3E}
BLOCKED_UDS_SERVICES = {0x11, 0x14, 0x27, 0x2E, 0x2F, 0x31, 0x34, 0x36, 0x37}
READ_ONLY_DIAGNOSTIC_SESSIONS = {0x01, 0x03}


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str


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
