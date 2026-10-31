#!/usr/bin/env bash

# ============================================================
# QR Wapsi - Development Demo Launcher
# Starts FastAPI backend (:8000) and Vite frontend (:5173)
# ============================================================

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Colors (automatically disabled if output is redirected)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    RESET='\033[0m'
else
    GREEN=''
    BLUE=''
    YELLOW=''
    RED=''
    RESET=''
fi

log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${RESET} $*"
}

success() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')] [OK]${RESET} $*"
}

warn() {
    echo -e "${YELLOW}[$(date '+%H:%M:%S')] [WARN]${RESET} $*"
}

fail() {
    echo -e "${RED}[$(date '+%H:%M:%S')] [ERROR]${RESET} $*" >&2
}

section() {
    echo
    echo "============================================================"
    echo " $*"
    echo "============================================================"
}

PIDS=()

cleanup() {
    echo
    warn "Stopping QR Wapsi servers..."

    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done

    wait 2>/dev/null || true
    success "Shutdown complete."
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ------------------------------------------------------------
# 1. Check prerequisites
# ------------------------------------------------------------

section "QR Wapsi Startup"

log "Project root: $ROOT"

if ! command -v python >/dev/null 2>&1 &&
   ! command -v python3 >/dev/null 2>&1; then
    fail "Python is not installed or not available on PATH."
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    fail "npm is not installed or not available on PATH."
    exit 1
fi

success "Python and npm are available."

# ------------------------------------------------------------
# 2. Environment configuration
# ------------------------------------------------------------

section "Environment Configuration"

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        success "Created .env from .env.example"
        warn "Check .env and set DEMO_MODE=replay before the offline demo."
    else
        fail ".env and .env.example are both missing."
        exit 1
    fi
else
    success ".env file found."
fi

if grep -Eq '^[[:space:]]*DEMO_MODE[[:space:]]*=[[:space:]]*replay([[:space:]]|$)' .env; then
    success "DEMO_MODE=replay found in .env."
else
    warn "DEMO_MODE=replay was not found in .env."
    warn "Check your configuration before running the offline demo."
fi

# ------------------------------------------------------------
# 3. Backend environment
# ------------------------------------------------------------

section "Preparing Backend"

if [ ! -d backend/venv ]; then
    log "Creating Python virtual environment..."

    if command -v python >/dev/null 2>&1; then
        python -m venv backend/venv
    else
        python3 -m venv backend/venv
    fi

    success "Python virtual environment created."
else
    success "Python virtual environment already exists."
fi

if [ -f backend/venv/Scripts/activate ]; then
    # Windows Git Bash
    source backend/venv/Scripts/activate
elif [ -f backend/venv/bin/activate ]; then
    # Linux/macOS
    source backend/venv/bin/activate
else
    fail "Could not find the virtual environment activation script."
    exit 1
fi

success "Python environment activated."

if [ ! -f backend/venv/.deps_installed ] ||
   [ backend/requirements.txt -nt backend/venv/.deps_installed ]; then

    log "Installing backend dependencies..."
    log "pip output is enabled so installation progress is visible."

    python -m pip install -r backend/requirements.txt

    touch backend/venv/.deps_installed
    success "Backend dependencies installed."
else
    success "Backend dependencies appear up to date."
fi

log "Python version: $(python --version 2>&1)"

# ------------------------------------------------------------
# 4. Frontend dependencies
# ------------------------------------------------------------

section "Preparing Frontend"

if [ ! -d frontend/node_modules ]; then
    log "Installing frontend dependencies..."
    (cd frontend && npm install)
    success "Frontend dependencies installed."
else
    success "Frontend node_modules already exists."
fi

log "Node version: $(node --version 2>&1)"
log "npm version: $(npm --version 2>&1)"

# ------------------------------------------------------------
# 5. Port checks
# ------------------------------------------------------------

section "Checking Ports"

if command -v curl >/dev/null 2>&1; then
    if curl --silent --max-time 1 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        fail "Port 8000 already has a responding backend."
        fail "Stop the existing server before starting another instance."
        exit 1
    fi

    if curl --silent --max-time 1 http://127.0.0.1:5173/ >/dev/null 2>&1; then
        fail "Port 5173 already has a responding frontend."
        fail "Stop the existing server before starting another instance."
        exit 1
    fi
fi

success "No responding server found on the demo ports."

# ------------------------------------------------------------
# 6. Start backend and frontend
# ------------------------------------------------------------

section "Starting Servers"

mkdir -p logs

BACKEND_LOG="logs/backend.log"
FRONTEND_LOG="logs/frontend.log"

log "Backend log:  $BACKEND_LOG"
log "Frontend log: $FRONTEND_LOG"

log "Starting FastAPI backend on http://127.0.0.1:8000 ..."

(
    cd backend
    exec python -u -m uvicorn app.main:app \
        --host 127.0.0.1 \
        --port 8000 \
        --log-level info
) > >(tee -a "$BACKEND_LOG" | sed 's/^/[BACKEND] /') 2>&1 &

BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

log "Backend process started (PID: $BACKEND_PID)."

log "Starting Vite frontend on http://127.0.0.1:5173 ..."

(
    cd frontend
    exec npm run dev -- --host 127.0.0.1 --port 5173
) > >(tee -a "$FRONTEND_LOG" | sed 's/^/[FRONTEND] /') 2>&1 &

FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")

# ------------------------------------------------------------
# 7. Wait for the servers to become available
# ------------------------------------------------------------

section "Waiting for Servers"

wait_for_url() {
    local name="$1"
    local url="$2"
    local attempts=0
    local max_attempts=30

    while [ "$attempts" -lt "$max_attempts" ]; do
        if curl --silent --fail --max-time 1 "$url" >/dev/null 2>&1; then
            success "$name is responding: $url"
            return 0
        fi

        if ! kill -0 "${3}" 2>/dev/null; then
            fail "$name process exited before becoming ready."
            return 1
        fi

        attempts=$((attempts + 1))
        echo -ne "\rWaiting for $name... ($attempts/$max_attempts)"
        sleep 1
    done

    echo
    fail "$name did not become ready within $max_attempts seconds."
    warn "Check the corresponding log file under ./logs/"
    return 1
}

if ! command -v curl >/dev/null 2>&1; then
    warn "curl is unavailable; skipping automatic HTTP readiness checks."
else
    wait_for_url "Backend" \
        "http://127.0.0.1:8000/api/health" "$BACKEND_PID" || exit 1

    wait_for_url "Frontend" \
        "http://127.0.0.1:5173/" "$FRONTEND_PID" || exit 1
fi

# ------------------------------------------------------------
# 8. Ready
# ------------------------------------------------------------

section "QR WAPSI IS READY"

echo -e "${GREEN}"
echo "  Frontend:       http://localhost:5173/"
echo "  Demo script:    http://localhost:5173/demo"
echo "  Backend:        http://127.0.0.1:8000/"
echo "  API docs:       http://127.0.0.1:8000/docs"
echo "  Backend health: http://127.0.0.1:8000/api/health"
echo -e "${RESET}"

echo "  Backend PID:  $BACKEND_PID"
echo "  Frontend PID: $FRONTEND_PID"
echo
echo "  Logs:"
echo "    Backend:  $BACKEND_LOG"
echo "    Frontend: $FRONTEND_LOG"
echo
echo "  Press Ctrl+C to stop both servers."
echo

# Keep the launcher alive and detect a server that exits.
while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        fail "Backend process has stopped. Check $BACKEND_LOG"
        exit 1
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        fail "Frontend process has stopped. Check $FRONTEND_LOG"
        exit 1
    fi
    sleep 2
done
