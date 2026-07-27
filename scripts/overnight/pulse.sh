#!/bin/bash
# scripts/overnight/pulse.sh
# Quick status check of overnight sessions. Safe to run repeatedly.

set -uo pipefail

REPO="$HOME/jz_code/bili_stock"
LOG_DIR="$REPO/logs/overnight_latest"

if [[ ! -d "$LOG_DIR" ]]; then
  echo "No overnight session found (logs/overnight_latest missing)."
  echo "Run scripts/overnight/launch.sh first."
  exit 1
fi

cd "$REPO"

echo "============================================================"
echo "  Overnight pulse — $(date)"
echo "============================================================"

# Process status
echo ""
echo "[Processes]"
for proc in caffeinate implementer attacker; do
  PID_FILE="$LOG_DIR/$proc.pid"
  if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "  $proc (PID $PID): RUNNING"
    else
      echo "  $proc (PID $PID): EXITED"
    fi
  fi
done

# Git state
echo ""
echo "[Git: last 8 commits on $(git rev-parse --abbrev-ref HEAD)]"
git log --oneline -8

# Sync state
echo ""
echo "[Sync: control.md head]"
head -15 research/foundation/_sync/control.md 2>/dev/null

# STOP check
if grep -q "^phase: STOP\|STOP:" research/foundation/_sync/control.md 2>/dev/null; then
  echo ""
  echo "============================================================"
  echo "  ⚠️  STOP detected in control.md"
  echo "============================================================"
fi

# Cycle artifacts
echo ""
echo "[Cycle 001 artifacts]"
for f in \
  "research/foundation/strategies_a1.py" \
  "research/foundation/strategies_h2_cluster_buy.py" \
  "research/foundation/strategies_h3_mass_exit.py" \
  "research/foundation/strategies_h4_buy_intensity.py" \
  "research/foundation/run_all_hypotheses.py" \
  "research/smart_consensus/verdict_2026-05-24_foundation.md" \
; do
  if [[ -f "$f" ]]; then
    SIZE=$(wc -l < "$f")
    echo "  ✓ $f ($SIZE lines)"
  else
    echo "  ✗ $f (not yet)"
  fi
done

# Last lines of each log
echo ""
echo "[Tail: implementer.log last 8]"
tail -8 "$LOG_DIR/implementer.log" 2>/dev/null || echo "  (empty or missing)"

echo ""
echo "[Tail: attacker.log last 8]"
tail -8 "$LOG_DIR/attacker.log" 2>/dev/null || echo "  (empty or missing)"

# Sync activity
echo ""
echo "[Sync activity in last hour]"
if [[ -f research/foundation/_sync/auto_red_team.md ]]; then
  echo "  red-team entries: $(grep -c '^## ' research/foundation/_sync/auto_red_team.md 2>/dev/null)"
fi
if [[ -f research/foundation/_sync/history.md ]]; then
  echo "  history tail:"
  tail -5 research/foundation/_sync/history.md 2>/dev/null
fi
