#!/usr/bin/env bash
# LeadSweep launcher for macOS and Linux (Windows: RUN.bat).
# First run: creates .venv, installs dependencies + Chromium, builds the dashboard.
# Later runs: just starts the server. Stop it with ./stop.sh
set -euo pipefail

cd "$(dirname "$0")"

PORT="${LEADSWEEP_PORT:-8000}"
HOST="127.0.0.1"
PID_FILE=".leadsweep.pid"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

echo "========================================"
echo "               LEADSWEEP"
echo "========================================"

# ---------------------------------------------------------------- already running?
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  say "LeadSweep is already running (pid $(cat "$PID_FILE")) at http://$HOST:$PORT"
  exit 0
fi

# ---------------------------------------------------------------- requirements
PY=""
for cand in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 &&
     "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
[[ -n "$PY" ]] || die "Python 3.11+ not found. Install it (macOS: 'brew install python@3.12', Debian/Ubuntu: 'sudo apt install python3.12 python3.12-venv')."
command -v node >/dev/null 2>&1 || die "Node.js 20+ not found. Install it from https://nodejs.org/"
command -v npm  >/dev/null 2>&1 || die "npm not found. Install Node.js from https://nodejs.org/"

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  say "Created .env from .env.example"
fi

# ---------------------------------------------------------------- backend
VENV_PY=".venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  say "Creating virtual environment with $("$PY" --version)..."
  "$PY" -m venv .venv || die "Could not create .venv (Debian/Ubuntu: sudo apt install python3-venv)."
fi

# Reinstall only when requirements.txt changes.
REQ_HASH="$("$VENV_PY" -c 'import hashlib,sys; print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
if [[ "$(cat .venv/.leadsweep-req 2>/dev/null || true)" != "$REQ_HASH" ]]; then
  say "Installing backend dependencies (log: $LOG_DIR/startup.log)..."
  "$VENV_PY" -m pip install --upgrade pip >>"$LOG_DIR/startup.log" 2>&1
  "$VENV_PY" -m pip install -r requirements.txt >>"$LOG_DIR/startup.log" 2>&1 \
    || die "pip install failed. See $LOG_DIR/startup.log"
  say "Installing Playwright Chromium (used for X scraping)..."
  if ! "$VENV_PY" -m playwright install chromium >>"$LOG_DIR/startup.log" 2>&1; then
    warn "Chromium install failed; X scraping will not work until it succeeds."
    [[ "$(uname -s)" == "Linux" ]] && warn "On Linux you may need system libraries: sudo .venv/bin/python -m playwright install-deps chromium"
  fi
  echo "$REQ_HASH" > .venv/.leadsweep-req
fi

# Interactive owner setup on the very first run (skipped when not attached to a terminal).
if [[ ! -f .setup_done && -f scripts/first_time_setup.py && -t 0 ]]; then
  "$VENV_PY" scripts/first_time_setup.py
fi

# ---------------------------------------------------------------- dashboard
if [[ ! -d project/node_modules ]]; then
  say "Installing dashboard dependencies..."
  (cd project && npm ci >>"../$LOG_DIR/startup.log" 2>&1) || die "npm ci failed. See $LOG_DIR/startup.log"
fi
if [[ ! -f project/dist/index.html ]] || [[ -n "$(find project/src project/index.html -newer project/dist/index.html -print -quit 2>/dev/null)" ]]; then
  say "Building dashboard..."
  (cd project && npm run build >>"../$LOG_DIR/startup.log" 2>&1) || die "Dashboard build failed. See $LOG_DIR/startup.log"
fi

# ---------------------------------------------------------------- start
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  die "Port $PORT is already in use. Stop that process or run: LEADSWEEP_PORT=8010 ./run.sh"
fi

say "Starting LeadSweep on http://$HOST:$PORT (log: $LOG_DIR/backend.log)..."
LEADSWEEP_WEB_DIST="project/dist" PYTHONPATH="$PWD" nohup "$VENV_PY" -m uvicorn leadsweep.api:app \
  --host "$HOST" --port "$PORT" >>"$LOG_DIR/backend.log" 2>&1 &
echo $! > "$PID_FILE"

for _ in $(seq 1 60); do
  if curl -sf "http://$HOST:$PORT/health?minimal=1" >/dev/null 2>&1; then
    say "Ready: http://$HOST:$PORT"
    if command -v open >/dev/null 2>&1; then open "http://$HOST:$PORT" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://$HOST:$PORT" >/dev/null 2>&1 || true
    fi
    echo "Stop it with: ./stop.sh"
    exit 0
  fi
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    rm -f "$PID_FILE"
    tail -n 20 "$LOG_DIR/backend.log" >&2
    die "Server exited during startup (last log lines above)."
  fi
  sleep 1
done
die "Server did not become healthy within 60s. See $LOG_DIR/backend.log"
