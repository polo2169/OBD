#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if [[ ! -x "${BACKEND_DIR}/.venv/bin/uvicorn" ]]; then
  echo "Backend non installé : ${BACKEND_DIR}/.venv/bin/uvicorn est introuvable." >&2
  echo "Suis d'abord la section « Première installation » du README." >&2
  exit 1
fi

if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "Frontend non installé : ${FRONTEND_DIR}/node_modules est introuvable." >&2
  echo "Suis d'abord la section « Première installation » du README." >&2
  exit 1
fi

backend_pid=""
frontend_pid=""

stop_app() {
  trap - EXIT INT TERM
  echo
  echo "Arrêt du frontend et du backend…"
  [[ -n "${frontend_pid}" ]] && kill "${frontend_pid}" 2>/dev/null || true
  [[ -n "${backend_pid}" ]] && kill "${backend_pid}" 2>/dev/null || true
  [[ -n "${frontend_pid}" ]] && wait "${frontend_pid}" 2>/dev/null || true
  [[ -n "${backend_pid}" ]] && wait "${backend_pid}" 2>/dev/null || true
}

trap stop_app EXIT INT TERM

echo "Démarrage du backend : http://127.0.0.1:${BACKEND_PORT}"
(
  cd "${BACKEND_DIR}"
  exec ./.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "${BACKEND_PORT}"
) &
backend_pid=$!

echo "Démarrage du frontend : http://127.0.0.1:${FRONTEND_PORT}"
(
  cd "${FRONTEND_DIR}"
  VITE_API_URL="http://127.0.0.1:${BACKEND_PORT}" \
    exec npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
) &
frontend_pid=$!

echo "Application prête dès que FastAPI et Vite affichent leur message de démarrage."
echo "Appuie sur Ctrl+C pour arrêter les deux services."

wait "${backend_pid}" "${frontend_pid}"
