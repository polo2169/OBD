#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
FIRMWARE_DIR="${PROJECT_DIR}/firmware/esp32-gateway"
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
  echo "== Firmware : profil passif par défaut =="
  (
    cd "${FIRMWARE_DIR}"
    pio run -e esp32-waveshare-wifi-readonly
  )
else
  echo "== Firmware : ignoré (commande pio absente) =="
  echo "La CI compile les profils firmware de référence avec PlatformIO."
fi

echo
echo "Tous les contrôles disponibles ont réussi."
