#!/usr/bin/env bash
# Stops a LeadSweep server started by ./run.sh
set -uo pipefail

cd "$(dirname "$0")"
PID_FILE=".leadsweep.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "LeadSweep is not running (no $PID_FILE)."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  echo "Stopping LeadSweep (pid $PID)..."
  kill "$PID"
  for _ in $(seq 1 10); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$PID" 2>/dev/null; then
    echo "Still running; forcing stop."
    kill -9 "$PID" 2>/dev/null || true
  fi
  echo "LeadSweep stopped."
else
  echo "LeadSweep was not running (stale pid file)."
fi
rm -f "$PID_FILE"
