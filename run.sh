#!/usr/bin/env bash
# Starts backend (:8000) and frontend (:5173) for the demo.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example"; }

# --- backend ---
if [ ! -d backend/venv ]; then
  echo "Creating Python venv..."
  python -m venv backend/venv 2>/dev/null || python3 -m venv backend/venv
fi
if [ -f backend/venv/Scripts/activate ]; then . backend/venv/Scripts/activate; else . backend/venv/bin/activate; fi
if [ ! -f backend/venv/.deps_installed ] || [ backend/requirements.txt -nt backend/venv/.deps_installed ]; then
  echo "Installing backend dependencies..."
  pip install -q -r backend/requirements.txt
  touch backend/venv/.deps_installed
fi

# --- frontend ---
if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm install)
fi

PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000) &
PIDS+=($!)
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5173) &
PIDS+=($!)

echo
echo "  QR Wapsi is starting"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000   (health: http://localhost:8000/api/health)"
echo "  Press Ctrl+C to stop both."
echo
wait
