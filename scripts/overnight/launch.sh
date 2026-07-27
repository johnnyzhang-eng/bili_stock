#!/bin/bash
# scripts/overnight/launch.sh
# Launches Claude + Codex /goal sessions for unattended overnight execution.
# Goals:
#   - macOS does not sleep / no display dim
#   - Both AI sessions run with permissions bypassed
#   - All output logged for morning audit
#   - PIDs saved so stop.sh can clean up
#
# Usage: bash scripts/overnight/launch.sh
# Then close the terminal. Use scripts/overnight/pulse.sh to peek progress.

set -euo pipefail

REPO="$HOME/jz_code/bili_stock"
cd "$REPO"

# Verify we're on the right branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" != "patch/methodology-audit-2026-05-23" ]]; then
  echo "WARN: current branch is $BRANCH, expected patch/methodology-audit-2026-05-23"
  echo "Press Enter to continue anyway, or Ctrl-C to abort."
  read
fi

# Verify uncommitted work
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "WARN: working tree has uncommitted changes. Commit or stash first."
  git status -s
  echo "Press Enter to continue anyway, or Ctrl-C to abort."
  read
fi

LOG_DIR="$REPO/logs/overnight_$(date +%Y%m%d_%H%M)"
mkdir -p "$LOG_DIR"
LATEST_LINK="$REPO/logs/overnight_latest"
ln -sfn "$LOG_DIR" "$LATEST_LINK"

# Cycle 002 HARDENED dual-session mode per Johnny 2026-05-24 ("加难度 + 不管 token"):
# 13 verifiable deliverables, TWO Claude sessions playing IMPLEMENTER + ATTACKER roles.
# Each session reads SESSION_BOOTSTRAP.md §10 to determine its role from GOAL_STRING.
# Token unlimited; ambition is constructive output, not budget conservation.

GOAL_IMPL='role: IMPLEMENTER. Read research/foundation/_engine/SESSION_BOOTSTRAP.md §1-11 fully then start cycle 002. Own deliverables §2.1, §2.2, §2.4, §2.5, §2.10, §2.11, §2.12, §2.13 per §10 role split. Wait for ATTACKER session SAFE/NEEDS-FIX (not BLOCK) on each strategy commit before next major step. Use Agent sub-agent inline for routine sanity checks. Cycle 002 closed when all 13 §2 deliverables exist with HARD EVIDENCE (numbers + file paths + commit hashes, no skeletons) AND ATTACKER co-signs verdicts §2.1 + §2.4 OR §3 STOP fires. Final commit must rewrite MORNING_BRIEF.md per §9. Token unlimited.'

GOAL_ATK='role: ATTACKER. Read research/foundation/_engine/SESSION_BOOTSTRAP.md §1-11 fully then start cycle 002. Own deliverables §2.3, §2.6, §2.7, §2.8, §2.9 per §10 role split. After each IMPLEMENTER strategy commit (pull frequently): (a) red-team review → write to _sync/auto_red_team.md with SAFE/NEEDS-FIX/BLOCK verdict, (b) run B8 axis-stability gate on any new axis → write report, (c) run 5-seed sensitivity re-runs → CSV, (d) compute ablation matrix per attack-registry entry → CSV. Co-sign verdicts §2.1 + §2.4 only when all evidence checks pass. Issue STOP via _sync/control.md if any §3 hard kill fires. Token unlimited.'

echo "============================================================"
echo "  Overnight launch"
echo "============================================================"
echo "  Repo:    $REPO"
echo "  Branch:  $BRANCH"
echo "  Goal:    cycle_001 (see ENGINE_SPEC §6)"
echo "  Logs:    $LOG_DIR"
echo "  Latest:  $LATEST_LINK"
echo "============================================================"

# 1. caffeinate forever — prevents sleep, display dim, idle, disk idle
nohup caffeinate -dimsu > "$LOG_DIR/caffeinate.log" 2>&1 &
CAFFEINATE_PID=$!
echo "$CAFFEINATE_PID" > "$LOG_DIR/caffeinate.pid"
echo "[1/3] caffeinate started (PID $CAFFEINATE_PID) — Mac will stay awake"

# Small delay so caffeinate is properly active before spawning compute
sleep 1

# 2. IMPLEMENTER Claude session — /goal in non-interactive, permissions bypassed via alias + global settings
nohup claude -p "/goal until '$GOAL_IMPL'" > "$LOG_DIR/implementer.log" 2>&1 &
IMPL_PID=$!
echo "$IMPL_PID" > "$LOG_DIR/implementer.pid"
echo "[2/3] IMPLEMENTER session started (PID $IMPL_PID)"

sleep 2

# 3. ATTACKER Claude session — second independent /goal, different role prompt
nohup claude -p "/goal until '$GOAL_ATK'" > "$LOG_DIR/attacker.log" 2>&1 &
ATK_PID=$!
echo "$ATK_PID" > "$LOG_DIR/attacker.pid"
echo "[3/3] ATTACKER session started (PID $ATK_PID)"

# Note: both sessions share the same Mac + same git working tree. They coordinate via
# _sync/ files + git rebase. File ownership specified in SESSION_BOOTSTRAP.md §10.
# Token usage doubles (2 parallel Claude sessions) — Johnny accepts this (token unlimited).

# Disown processes so they survive terminal close
disown -a 2>/dev/null || true

echo ""
echo "============================================================"
echo "  All three processes detached. Safe to close terminal."
echo "============================================================"
echo ""
echo "Peek progress later:    bash $REPO/scripts/overnight/pulse.sh"
echo "Stop everything:        bash $REPO/scripts/overnight/stop.sh"
echo ""
echo "Logs:"
echo "  $LOG_DIR/caffeinate.log"
echo "  $LOG_DIR/implementer.log"
echo "  $LOG_DIR/attacker.log"
echo ""
echo "Symlink to latest: $LATEST_LINK"
