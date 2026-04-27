#!/usr/bin/env bash
# Spustí backend v mock módu a statický server pro frontend.
# Použití:   ./dev.sh            -> backend na :8000 + frontend na :3000, MOCK_MODE=true
#            MOCK_MODE=false ./dev.sh   -> reálný backend (potřebuje .env)
#            BACKEND_PORT=8001 FRONTEND_PORT=4000 ./dev.sh
#
# Ctrl+C ukončí oba procesy najednou.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MOCK_MODE="${MOCK_MODE:-true}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

echo "==> experience-app dev launcher"
echo "    MOCK_MODE=$MOCK_MODE"
echo "    backend:  http://localhost:$BACKEND_PORT"
echo "    frontend: http://localhost:$FRONTEND_PORT"
echo

# -----------------------------------------------------------------
# Backend setup
# -----------------------------------------------------------------
cd "$ROOT_DIR/backend"

if [[ ! -d ".venv" ]]; then
  echo "==> Creating virtualenv at backend/.venv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Install only if uvicorn is not already present, to keep reruns fast.
if ! python -c "import uvicorn" >/dev/null 2>&1; then
  echo "==> Installing backend dependencies ..."
  pip install -e ".[dev]" >/dev/null
fi

# -----------------------------------------------------------------
# Start both processes; forward SIGINT/TERM to the group.
# -----------------------------------------------------------------
pids=()
cleanup() {
  trap - INT TERM EXIT
  echo
  echo "==> Shutting down (pids: ${pids[*]:-none})"
  for pid in "${pids[@]:-}"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "==> Starting backend (uvicorn) ..."
MOCK_MODE="$MOCK_MODE" uvicorn app.main:app \
  --reload \
  --host 127.0.0.1 \
  --port "$BACKEND_PORT" &
pids+=($!)

cd "$ROOT_DIR/frontend"
echo "==> Starting frontend (python -m http.server) ..."
python3 -m http.server "$FRONTEND_PORT" --bind 127.0.0.1 &
pids+=($!)

echo
echo "==> Ready. Open http://localhost:$FRONTEND_PORT"
echo "    Press Ctrl+C to stop both servers."
echo

# Wait on whichever process exits first, then cleanup kills the rest.
wait -n "${pids[@]}" || true
