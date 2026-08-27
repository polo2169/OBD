#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
FIRMWARE_DIR="${PROJECT_DIR}/firmware/esp32-gateway"
OPENPILOT_LAB_DIR="${PROJECT_DIR}/openpilot"
PSA_BRIDGE_DIR="${OPENPILOT_LAB_DIR}/firmware/psa-obdc-bridge"
SENSOR_FIRMWARE_DIR="${OPENPILOT_LAB_DIR}/firmware/sensor-logger"
CHECK_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/opendiag-check.XXXXXX")"

cleanup() {
  rm -rf -- "${CHECK_TMP_DIR}"
}

trap cleanup EXIT

if [[ ! -x "${BACKEND_DIR}/.venv/bin/pytest" ]]; then
  echo "Backend non installé : ${BACKEND_DIR}/.venv/bin/pytest est introuvable." >&2
  echo "Suis d'abord la section « Première installation » du README." >&2
  exit 1
fi

if [[ ! -x "${FRONTEND_DIR}/node_modules/.bin/tsc" ]] ||
   [[ ! -x "${FRONTEND_DIR}/node_modules/.bin/vite" ]]; then
  echo "Frontend non installé : lance npm install dans ${FRONTEND_DIR}." >&2
  exit 1
fi

echo "== Backend : tests =="
(
  cd "${BACKEND_DIR}"
  PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/pytest -p no:cacheprovider -q
)

echo
echo "== Laboratoire OpenPilot : tests Python =="
(
  cd "${OPENPILOT_LAB_DIR}"
  PYTHONDONTWRITEBYTECODE=1 "${BACKEND_DIR}/.venv/bin/pytest" -p no:cacheprovider -q
)

echo
echo "== Laboratoire OpenPilot : barrières de sécurité natives =="
c++ -std=c++17 -Wall -Wextra -Werror \
  -I"${PSA_BRIDGE_DIR}/include" \
  "${PSA_BRIDGE_DIR}/test/mads_state_test.cpp" \
  -o "${CHECK_TMP_DIR}/mads-state-test"
"${CHECK_TMP_DIR}/mads-state-test"
c++ -std=c++17 -Wall -Wextra -Werror \
  -I"${PSA_BRIDGE_DIR}/test/stubs" -I"${PSA_BRIDGE_DIR}/include" \
  "${PSA_BRIDGE_DIR}/test/lka_mads_safety_test.cpp" \
  -o "${CHECK_TMP_DIR}/lka-mads-test"
"${CHECK_TMP_DIR}/lka-mads-test"
c++ -std=c++17 -Wall -Wextra -Werror \
  -I"${PSA_BRIDGE_DIR}/include" \
  "${PSA_BRIDGE_DIR}/test/rvv_safety_test.cpp" \
  -o "${CHECK_TMP_DIR}/rvv-safety-test"
"${CHECK_TMP_DIR}/rvv-safety-test"

echo
echo "== Frontend : TypeScript strict et build =="
(
  cd "${FRONTEND_DIR}"
  npm run typecheck
  ./node_modules/.bin/vite build \
    --outDir "${CHECK_TMP_DIR}/frontend-dist" \
    --emptyOutDir
)

echo
if command -v pio >/dev/null 2>&1; then
  echo "== Firmware OBD : profil passif par défaut =="
  (
    cd "${FIRMWARE_DIR}"
    pio run -e esp32-waveshare-wifi-readonly
  )
  echo
  echo "== Firmware OpenPilot : profils sûrs et capteurs =="
  (
    cd "${PSA_BRIDGE_DIR}"
    pio run -e psa-obdc-master-zero-torque -e psa-obdc-satellite
  )
  (
    cd "${SENSOR_FIRMWARE_DIR}"
    pio run -e esp32-sensor-logger
  )
else
  echo "== Firmware : ignoré (commande pio absente) =="
  echo "La CI compile les profils firmware de référence avec PlatformIO."
fi

echo
echo "Tous les contrôles disponibles ont réussi."
