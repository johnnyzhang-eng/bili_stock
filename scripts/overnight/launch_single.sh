#!/bin/bash
# scripts/overnight/launch_single.sh
# Single-brain variant of launch.sh after 2026-05-24 dual-session session-cap incident.
# Spawns ONE `claude -p /goal` that owns BOTH IMPL + ATK roles per
# SESSION_BOOTSTRAP.md §10, using Agent(general-purpose) sub-agent for the
# red-team cross-check (sub-agent has its own context window — that IS the
# independent review now). Halves Claude.ai session-quota burn vs launch.sh.
#
# Usage: bash scripts/overnight/launch_single.sh
# Peek:  bash scripts/overnight/pulse.sh
# Stop:  bash scripts/overnight/stop.sh

set -euo pipefail

REPO="$HOME/jz_code/bili_stock"
cd "$REPO"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" != "patch/methodology-audit-2026-05-23" ]]; then
  echo "WARN: current branch is $BRANCH, expected patch/methodology-audit-2026-05-23"
  echo "Press Enter to continue anyway, or Ctrl-C to abort."
  read
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "WARN: working tree has uncommitted (tracked) changes."
  git status -s
  echo "Press Enter to continue anyway, or Ctrl-C to abort."
  read
fi

LOG_DIR="$REPO/logs/overnight_$(date +%Y%m%d_%H%M)"
mkdir -p "$LOG_DIR"
LATEST_LINK="$REPO/logs/overnight_latest"
ln -sfn "$LOG_DIR" "$LATEST_LINK"

GOAL_SINGLE='role: SINGLE_BRAIN (dual-session collapsed to one after 2026-05-24 session-cap incident at 04:19 — see logs/overnight_20260524_0349/). Read research/foundation/_engine/SESSION_BOOTSTRAP.md §1-11 fully then start cycle 002. Own ALL 13 §2 deliverables yourself (no second session to delegate to). For each strategy commit, spawn Agent(subagent_type="general-purpose") with the §4 red-team prompt — the sub-agent runs in its own context window, that IS the independent cross-check. Sub-agent verdict appended to _sync/auto_red_team.md MUST be SAFE or NEEDS-FIX before proceeding; if BLOCK, fix first then retry. Verdicts §2.1 and §2.4 are considered co-signed when the sub-agent red-team for that hypothesis reports SAFE. Run B8 axis audits, 5-seed sensitivity, and ablation matrices yourself per §2.6/2.8/2.9 (these were originally ATK-owned). Cycle 002 closes when all 13 §2 deliverables exist with HARD EVIDENCE (numbers + file paths + commit hashes — no skeletons) OR §3 STOP fires. Final commit MUST rewrite MORNING_BRIEF.md per §9. Token unlimited but session-aware — do not re-read the same files repeatedly, cache in working memory.'

echo "============================================================"
echo "  Overnight launch (SINGLE-BRAIN)"
echo "============================================================"
echo "  Repo:    $REPO"
echo "  Branch:  $BRANCH"
echo "  Mode:    1× /goal session (IMPL+ATK merged), Agent sub-agent for red-team"
echo "  Logs:    $LOG_DIR"
echo "  Latest:  $LATEST_LINK"
echo "============================================================"

nohup caffeinate -dimsu > "$LOG_DIR/caffeinate.log" 2>&1 &
CAFFEINATE_PID=$!
echo "$CAFFEINATE_PID" > "$LOG_DIR/caffeinate.pid"
echo "[1/2] caffeinate started (PID $CAFFEINATE_PID) — Mac stays awake"

sleep 1

nohup claude -p "/goal until '$GOAL_SINGLE'" > "$LOG_DIR/single_brain.log" 2>&1 &
SB_PID=$!
echo "$SB_PID" > "$LOG_DIR/single_brain.pid"
echo "[2/2] SINGLE_BRAIN session started (PID $SB_PID)"

disown -a 2>/dev/null || true

echo ""
echo "============================================================"
echo "  Detached. Safe to close terminal."
echo "============================================================"
echo "  Peek:  bash $REPO/scripts/overnight/pulse.sh"
echo "  Stop:  bash $REPO/scripts/overnight/stop.sh"
echo ""
echo "  Logs:"
echo "    $LOG_DIR/caffeinate.log"
echo "    $LOG_DIR/single_brain.log"
