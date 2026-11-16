#!/usr/bin/env bash
set -e

# LeadSweep container entrypoint.
#   studio | api   - dashboard + API on :8000 (default)
#   run-once       - one scheduled pipeline run, then exit
#   loop | daemon  - pipeline every RUN_INTERVAL_S seconds (default 14400 = 4h)
#   mcp-server     - MCP server for agent integrations
#   anything else  - executed as a command

case "$1" in
  "run-once")
    echo "[leadsweep] Starting single pipeline execution..."
    exec python -m scripts.run_pipeline
    ;;

  "cron")
    # The image runs as a non-root user without a cron daemon, so a real crontab
    # cannot be installed. Fall through to the interval loop instead.
    echo "[leadsweep] 'cron' mode is an alias for 'loop' (set RUN_INTERVAL_S to change the interval)."
    exec "$0" loop
    ;;

  "daemon"|"loop")
    INTERVAL_SECONDS="${RUN_INTERVAL_S:-14400}"
    echo "[leadsweep] Starting continuous runner loop (Interval: ${INTERVAL_SECONDS}s)..."
    while true; do
      echo "[leadsweep $(date -u +'%Y-%m-%d %H:%M:%SZ')] Starting scheduled pipeline run..."
      python -m scripts.run_pipeline || echo "[leadsweep] Run completed with errors (check log)"
      echo "[leadsweep] Sleeping for ${INTERVAL_SECONDS}s..."
      sleep "${INTERVAL_SECONDS}"
    done
    ;;

  "mcp-server")
    echo "[leadsweep] Starting MCP server..."
    shift
    exec python -m leadsweep.mcp_server "$@"
    ;;

  "studio"|"api")
    echo "[leadsweep] Starting LeadSweep Studio API server on port 8000..."
    exec uvicorn leadsweep.api:app --host 0.0.0.0 --port 8000
    ;;

  *)
    exec "$@"
    ;;
esac
