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

gopro_ip="${GOPRO_IP:-172.28.152.51}"
stream_port="${GOPRO_STREAM_PORT:-8554}"
camera_base="http://${gopro_ip}:8080"
duration_s=""
display_scale="0.65"
model_hz="20"
can_port="${LKA_CAN_PORT:-}"
with_can=false
rotate_180=true
record=false
record_overlay=false
headless=false
output_dir="${PROJECT_DIR}/data/runtime/openpilot_live"

usage() {
  cat <<'EOF'
Lance driving_supercombo en direct sur le flux USB d'une GoPro HERO9.

Usage:
  scripts/run_openpilot_gopro.sh [options]

Options:
  --with-can          Ajoute la télémétrie CAN Peugeot en lecture seule
  --port CHEMIN       Port série de l'ESP32 véhicule (implique --with-can)
  --duration SEC      Arrêt automatique après SEC secondes
  --record            Enregistre route, perception et CAN éventuel
  --overlay           Enregistre aussi overlay.mp4 (implique --record)
  --headless          N'ouvre pas la fenêtre d'affichage
  --no-rotate-180     Désactive la correction de la GoPro montée à l'envers
  --display-scale N   Taille de la fenêtre (0.65 par défaut)
  --model-hz N        Cadence demandée au modèle (20 par défaut)
  --output-dir DIR    Dossier parent des sessions enregistrées
  -h, --help          Affiche cette aide

Sans --with-can, aucune interface véhicule n'est ouverte. Avec --with-can, le
lecteur série reste strictement passif et ne transmet aucune trame CAN.
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
    --with-can)
      with_can=true
      shift
      ;;
    --port)
      require_value "$@"
      can_port="$2"
      with_can=true
      shift 2
      ;;
    --duration)
      require_value "$@"
      duration_s="$2"
      shift 2
      ;;
    --record)
      record=true
      shift
      ;;
    --overlay)
      record=true
      record_overlay=true
      shift
      ;;
    --headless)
      headless=true
      shift
      ;;
    --no-rotate-180)
      rotate_180=false
      shift
      ;;
    --display-scale)
      require_value "$@"
      display_scale="$2"
      shift 2
      ;;
    --model-hz)
      require_value "$@"
      model_hz="$2"
      shift 2
      ;;
    --output-dir)
      require_value "$@"
      output_dir="$2"
      shift 2
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

for required in curl mkfifo; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "Commande requise introuvable: ${required}" >&2
    exit 1
  fi
done

find_udp_ffmpeg() {
  local path_ffmpeg=""
  local candidate=""
  local candidates=()
  if [[ -n "${FFMPEG_BIN:-}" ]]; then
    candidates+=("${FFMPEG_BIN}")
  fi
  candidates+=(/opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg)
  path_ffmpeg="$(command -v ffmpeg 2>/dev/null || true)"
  if [[ -n "${path_ffmpeg}" ]]; then
    candidates+=("${path_ffmpeg}")
  fi
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]] && \
      "${candidate}" -hide_banner -protocols 2>/dev/null | grep -Eq '^[[:space:]]+udp$'; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

if ! ffmpeg_bin="$(find_udp_ffmpeg)"; then
  echo "Aucun FFmpeg compatible UDP n'a été trouvé." >&2
  echo "Le FFmpeg du virtualenv openpilot ne suffit pas; installe celui de Homebrew." >&2
  exit 1
fi
for required in "${OPENPILOT_PYTHON}" "${BACKEND_PYTHON}" "${RUNNER}" "${DBC}" "${CALIBRATION}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Fichier requis introuvable: ${required}" >&2
    exit 1
  fi
done

if [[ -n "${duration_s}" && ! "${duration_s}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "--duration doit être un nombre de secondes positif." >&2
  exit 2
fi

if ! curl -fsS --max-time 4 "${camera_base}/gopro/camera/state" >/dev/null; then
  echo "GoPro inaccessible sur ${camera_base}. Vérifie USB Connection > GoPro Connect." >&2
  exit 1
fi

live_dir="$(mktemp -d /tmp/gopro-openpilot-live.XXXXXX)"
video_pipe="${live_dir}/gopro-upright.ts"
udp_pid=""
http_pid=""
ffmpeg_pid=""

cleanup() {
  for pid in "${ffmpeg_pid}" "${udp_pid}" "${http_pid}"; do
    if [[ -n "${pid}" ]]; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  curl -fsS --max-time 3 "${camera_base}/gopro/webcam/stop" >/dev/null 2>&1 || true
  if [[ "${live_dir}" == /tmp/gopro-openpilot-live.* ]]; then
    rm -f "${video_pipe}"
    rmdir "${live_dir}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

mkfifo "${video_pipe}"
curl -fsS --max-time 5 "${camera_base}/gopro/webcam/stop" >/dev/null 2>&1 || true
curl -fsS --max-time 5 "${camera_base}/gopro/webcam/start?port=${stream_port}" >/dev/null

python3 -c 'import socket,sys,time
camera_ip, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = b"_GPHD_:1:0:2:0.000000\n"
while True:
    sock.sendto(payload, (camera_ip, port))
    time.sleep(1)' "${gopro_ip}" "${stream_port}" &
udp_pid=$!

(
  while true; do
    curl -fsS --max-time 2 "${camera_base}/gopro/camera/keep_alive" >/dev/null || true
    sleep 1
  done
) &
http_pid=$!

"${ffmpeg_bin}" -hide_banner -loglevel fatal -y \
  -fflags nobuffer -flags low_delay -probesize 500000 -analyzeduration 0 \
  -i "udp://0.0.0.0:${stream_port}?overrun_nonfatal=1&fifo_size=50000000&timeout=6000000" \
  -map 0:v:0 -an -c:v copy \
  -f mpegts -muxdelay 0 -muxpreload 0 -flush_packets 1 "${video_pipe}" &
ffmpeg_pid=$!
sleep 0.25
if ! kill -0 "${ffmpeg_pid}" >/dev/null 2>&1; then
  ffmpeg_status=0
  wait "${ffmpeg_pid}" || ffmpeg_status=$?
  ffmpeg_pid=""
  echo "Le flux GoPro n'a pas pu démarrer (FFmpeg code ${ffmpeg_status})." >&2
  exit 1
fi

command=(
  env -u DEBUG PYTHONUNBUFFERED=1
  "${OPENPILOT_PYTHON}"
  "${RUNNER}"
  --openpilot-root "${OPENPILOT_DIR}"
  --backend-python "${BACKEND_PYTHON}"
  --dbc "${DBC}"
  --calibration "${CALIBRATION}"
  --stream "${video_pipe}"
  --model-backend onnx-cpu
  --model-hz "${model_hz}"
  --display-scale "${display_scale}"
  --output-dir "${output_dir}"
)
if [[ "${rotate_180}" == true ]]; then
  command+=(--rotate-180)
else
  command+=(--no-rotate-180)
fi
if [[ "${with_can}" == true ]]; then
  if [[ -n "${can_port}" ]]; then
    command+=(--port "${can_port}")
  fi
else
  command+=(--no-can)
fi
if [[ -n "${duration_s}" ]]; then
  command+=(--duration "${duration_s}")
fi
if [[ "${record}" == true ]]; then
  command+=(--record)
fi
if [[ "${record_overlay}" == true ]]; then
  command+=(--record-overlay)
fi
if [[ "${headless}" == true ]]; then
  command+=(--headless)
fi

echo "openpilot sur GoPro — observation passive"
echo "  GoPro : ${gopro_ip}, flux 1080p30 USB"
echo "  FFmpeg: ${ffmpeg_bin} (UDP disponible)"
echo "  image : rotation 180° ${rotate_180}"
echo "  CAN   : $([[ "${with_can}" == true ]] && echo 'lecture seule' || echo 'désactivé')"
echo "  arrêt : Q, Échap ou Ctrl+C"
echo

"${command[@]}"
