#!/bin/bash
# scripts/overnight/stop.sh
# Gracefully stop the overnight sessions. Removes the symlink.

set -uo pipefail

REPO="$HOME/jz_code/bili_stock"
LOG_DIR="$REPO/logs/overnight_latest"

if [[ ! -d "$LOG_DIR" ]]; then
  echo "No overnight session symlink found."
  exit 0
fi

echo "Stopping overnight sessions..."

for proc in implementer attacker caffeinate; do
  PID_FILE="$LOG_DIR/$proc.pid"
  if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "  Killing $proc (PID $PID)..."
      kill "$PID" 2>/dev/null || true
      sleep 1
      kill -9 "$PID" 2>/dev/null || true
    else
      echo "  $proc (PID $PID) already exited"
    fi
  fi
done

echo "Done. Logs preserved at: $(readlink "$LOG_DIR")"
echo "Removing 'latest' symlink so launch.sh can start fresh next time."
rm -f "$LOG_DIR"  # this only removes the symlink, not the actual log dir
