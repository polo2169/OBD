#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
OPENPILOT_DIR="${PROJECT_DIR}/../openpilot"
OPENPILOT_PYTHON="${OPENPILOT_DIR}/.venv/bin/python"
BACKEND_PYTHON="${BACKEND_DIR}/.venv/bin/python"
RUNNER="${BACKEND_DIR}/tools/run_openpilot_live.py"
DBC="${PROJECT_DIR}/database/psa/dbc/peugeot_308_t9_2018.dbc"
CALIBRATION="${OPENPILOT_DIR}/camera_intrinsics.json"
TRANSPORT_SELECTION="${PROJECT_DIR}/data/runtime/transport_selection.json"

camera_index=0
can_port="${LKA_CAN_PORT:-}"
duration_s="900"
rotation_arg="--rotate-180"
output_dir="${PROJECT_DIR}/data/runtime/openpilot_live"
record_overlay=false
headless=false
list_cameras=false
dry_run=false

usage() {
  cat <<'EOF'
Enregistre une vidéo route et le CAN Peugeot synchronisés, sans aucune émission CAN.

Usage:
  scripts/record_peugeot_lka.sh [options]

Options:
  --port CHEMIN       Port de l'ESP32 véhicule (préférence mémorisée par défaut)
  --camera INDEX      Index caméra OpenCV (0 par défaut)
  --duration SEC      Arrêt automatique (900 s / 15 min par défaut)
  --until-stop        Enregistre jusqu'à Q, Échap ou Ctrl+C
  --rotate-180        Caméra route montée à l'envers (défaut)
  --no-rotate-180     Ne retourne pas l'image
  --overlay           Enregistre aussi l'interface annotée (plus d'espace disque)
  --headless          N'ouvre pas de fenêtre; arrêter avec Ctrl+C
  --output-dir DIR    Dossier parent des sessions
  --list-cameras      Liste les caméras disponibles puis quitte
  --dry-run           Affiche la commande finale sans enregistrer
  -h, --help          Affiche cette aide

Pendant l'enregistrement avec fenêtre, Q ou Échap assure un arrêt propre.
EOF
}

require_value() {
  if [[ $# -lt 2 || -z "${2:-}" ]]; then
    echo "Valeur manquante après $1" >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      require_value "$@"
      can_port="$2"
      shift 2
      ;;
    --camera)
      require_value "$@"
      camera_index="$2"
      shift 2
      ;;
    --duration)
      require_value "$@"
      duration_s="$2"
      shift 2
      ;;
    --until-stop)
      duration_s=""
      shift
      ;;
    --rotate-180)
      rotation_arg="--rotate-180"
      shift
      ;;
    --no-rotate-180)
      rotation_arg="--no-rotate-180"
      shift
      ;;
    --overlay)
      record_overlay=true
      shift
      ;;
    --headless)
      headless=true
      shift
      ;;
    --output-dir)
      require_value "$@"
      output_dir="$2"
      shift 2
      ;;
    --list-cameras)
      list_cameras=true
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Option inconnue: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for required in "${OPENPILOT_PYTHON}" "${BACKEND_PYTHON}" "${RUNNER}" "${DBC}" "${CALIBRATION}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Fichier requis introuvable: ${required}" >&2
    exit 1
  fi
done

if [[ ! "${camera_index}" =~ ^[0-9]+$ ]]; then
  echo "--camera doit être un entier positif ou nul." >&2
  exit 2
fi
if [[ -n "${duration_s}" && ! "${duration_s}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "--duration doit être un nombre de secondes positif." >&2
  exit 2
fi

if [[ "${list_cameras}" == true ]]; then
  exec env -u DEBUG "${OPENPILOT_PYTHON}" "${RUNNER}" --list-cameras
fi

if [[ -z "${can_port}" && -f "${TRANSPORT_SELECTION}" ]]; then
  can_port="$("${BACKEND_PYTHON}" -c '
import json
import sys
from pathlib import Path

selection = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if selection.get("transport") == "esp32_serial":
    print(selection.get("endpoint") or "")
' "${TRANSPORT_SELECTION}")"
fi

if [[ -z "${can_port}" ]]; then
  echo "Aucun port CAN sélectionné. Utilise --port /dev/cu..." >&2
  exit 1
fi
if [[ ! -e "${can_port}" ]]; then
  echo "Port CAN introuvable: ${can_port}" >&2
  exit 1
fi
if command -v lsof >/dev/null 2>&1 && lsof "${can_port}" >/dev/null 2>&1; then
  echo "Le port CAN est déjà utilisé: ${can_port}" >&2
  lsof "${can_port}" >&2 || true
  echo "Arrête l'application OBD, le HIL ou tout autre lecteur série avant de recommencer." >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg est requis pour finaliser correctement les horodatages vidéo." >&2
  exit 1
fi

mkdir -p "${output_dir}"
available_kb="$(df -Pk "${output_dir}" | awk 'NR==2 {print $4}')"
if [[ "${available_kb}" =~ ^[0-9]+$ && "${available_kb}" -lt 20971520 ]]; then
  echo "Attention: moins de 20 Gio sont disponibles dans ${output_dir}." >&2
fi

command=(
  env -u DEBUG
  "${OPENPILOT_PYTHON}"
  "${RUNNER}"
  --openpilot-root "${OPENPILOT_DIR}"
  --backend-python "${BACKEND_PYTHON}"
  --dbc "${DBC}"
  --calibration "${CALIBRATION}"
  --camera "${camera_index}"
  "${rotation_arg}"
  --port "${can_port}"
  --baud 921600
  --model-backend onnx-cpu
  --model-hz 20
  --record
  --output-dir "${output_dir}"
)
if [[ -n "${duration_s}" ]]; then
  command+=(--duration "${duration_s}")
fi
if [[ "${record_overlay}" == true ]]; then
  command+=(--record-overlay)
fi
if [[ "${headless}" == true ]]; then
  command+=(--headless)
fi

echo "Enregistrement Peugeot LKA strictement passif"
echo "  caméra : ${camera_index} (${rotation_arg})"
echo "  CAN    : ${can_port} à 921600 bauds, lecture seule"
echo "  durée  : ${duration_s:-jusqu’à arrêt manuel}"
echo "  sortie : ${output_dir}/live-YYYYMMDDTHHMMSSZ"
echo
echo "Attends les messages '[model] prêt', '[CAN] prêt' et '[live]' avant de démarrer le trajet."
if [[ "${headless}" == false ]]; then
  echo "Appuie sur Q ou Échap à la fin pour fermer et synchroniser proprement les fichiers."
fi
echo

if [[ "${dry_run}" == true ]]; then
  printf 'Commande: '
  printf '%q ' "${command[@]}"
  printf '\n'
  exit 0
fi

"${command[@]}"

latest_session="$(find "${output_dir}" -maxdepth 1 -type d -name 'live-*' -print | sort | tail -1)"
if [[ -z "${latest_session}" ]]; then
  echo "Aucune session enregistrée n'a été trouvée dans ${output_dir}." >&2
  exit 1
fi

"${BACKEND_PYTHON}" -c '
import json
import sys
from pathlib import Path

session = Path(sys.argv[1])
required = ("road.mp4", "frames.jsonl", "can.jsonl", "meta.json")
missing = [name for name in required if not (session / name).is_file()]
if missing:
    raise SystemExit("Capture incomplète, fichiers absents: " + ", ".join(missing))
meta = json.loads((session / "meta.json").read_text(encoding="utf-8"))
summary = meta.get("summary") or {}
can = summary.get("can") or {}
frames = int(meta.get("frame_count") or 0)
can_frames = int(can.get("frames_total") or 0)
anchor = meta.get("sync_anchor")
rate = can.get("frames_per_second")
dropped = can.get("gateway_dropped")
sequence_gaps = can.get("sequence_gaps")
if frames < 10 or can_frames < 100 or not anchor:
    raise SystemExit(
        f"Capture non validée: vidéo={frames} images, CAN={can_frames} trames, synchronisation={bool(anchor)}"
    )
print(f"Capture validée: {session}")
print(f"  vidéo: {frames} images")
print(f"  CAN: {can_frames} trames, débit final={rate} tr/s")
print("  synchronisation caméra/CAN: présente")
print(f"  pertes passerelle: {dropped}")
print(f"  trous de séquence: {sequence_gaps}")
' "${latest_session}"
