#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

backend_pid=""
frontend_pid=""
stopping=false

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

port_is_used() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

show_port_owner() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

# Tue d'abord les descendants, puis leur parent.
kill_process_tree() {
  local pid="${1:-}"
  local signal="${2:-TERM}"
  local child=""

  [[ -z "${pid}" ]] && return 0
  kill -0 "${pid}" 2>/dev/null || return 0

  while read -r child; do
    [[ -n "${child}" ]] && kill_process_tree "${child}" "${signal}"
  done < <(pgrep -P "${pid}" 2>/dev/null || true)

  kill "-${signal}" "${pid}" 2>/dev/null || true
}

stop_app() {
  if [[ "${stopping}" == true ]]; then
    return
  fi

  stopping=true
  trap - EXIT INT TERM

  echo
  echo "Arrêt du frontend et du backend…"

  kill_process_tree "${frontend_pid}" TERM
  kill_process_tree "${backend_pid}" TERM

  # Laisse aux processus le temps de s'arrêter proprement.
  sleep 1

  # Force uniquement ceux qui seraient encore présents.
  kill_process_tree "${frontend_pid}" KILL
  kill_process_tree "${backend_pid}" KILL

  [[ -n "${frontend_pid}" ]] && wait "${frontend_pid}" 2>/dev/null || true
  [[ -n "${backend_pid}" ]] && wait "${backend_pid}" 2>/dev/null || true

  echo "Application arrêtée."
}

trap stop_app EXIT INT TERM

if port_is_used "${BACKEND_PORT}"; then
  echo "Erreur : le port backend ${BACKEND_PORT} est déjà utilisé :" >&2
  show_port_owner "${BACKEND_PORT}" >&2
  echo >&2
  echo "Pour libérer ce port :" >&2
  echo "  kill \$(lsof -tiTCP:${BACKEND_PORT} -sTCP:LISTEN)" >&2
  exit 1
fi

if port_is_used "${FRONTEND_PORT}"; then
  echo "Erreur : le port frontend ${FRONTEND_PORT} est déjà utilisé :" >&2
  show_port_owner "${FRONTEND_PORT}" >&2
  echo >&2
  echo "Pour libérer ce port :" >&2
  echo "  kill \$(lsof -tiTCP:${FRONTEND_PORT} -sTCP:LISTEN)" >&2
  exit 1
fi

echo "Démarrage du backend : http://127.0.0.1:${BACKEND_PORT}"
(
  cd "${BACKEND_DIR}"

  export ENVIRONMENT="${ENVIRONMENT:-development}"
  export FRONTEND_HOST="127.0.0.1"
  export FRONTEND_PORT

  exec ./.venv/bin/uvicorn \
    app.main:app \
    --reload \
    --host 127.0.0.1 \
    --port "${BACKEND_PORT}"
) &
backend_pid=$!

echo "Démarrage du frontend : http://127.0.0.1:${FRONTEND_PORT}"
(
  cd "${FRONTEND_DIR}"
  export VITE_API_URL="http://127.0.0.1:${BACKEND_PORT}"
  exec npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
) &
frontend_pid=$!

echo "Application prête dès que FastAPI et Vite affichent leur message de démarrage."
echo "Appuie sur Ctrl+C pour arrêter les deux services."

# Un seul wait permet au trap de reprendre correctement la main.
wait