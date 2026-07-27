# Session Bootstrap — Alpha Discovery Engine Cycle 002

**You are Claude (Opus 4.7), continuing the Alpha Discovery Engine project at `~/jz_code/bili_stock`. Previous session ended after Cycle 001 closed (all 4 hypotheses REJECTED).**

This is the SINGLE source of truth for what to do. Read sections in order. Do not skip.

---

## §1 — Read these files BEFORE any action (in order)

```
1. /Users/johnnyzhang/.claude/projects/-Users-johnnyzhang/memory/MEMORY.md
   (Your auto-memory index. Includes user profile + Codex collab mode + A1 audit outcome.)

2. research/foundation/_engine/ENGINE_SPEC.md
   (Constitution. §3 hypothesis lifecycle, §6 hard kill criteria, §10 roles.)

3. research/foundation/_engine/cycles/cycle_001_2026-05-24.md
   (Retrospective. What worked, what didn't, what cycle 002 changes.)

4. research/foundation/_engine/negative_log.md (N1 entry)
   research/foundation/_engine/lessons_learned.md (L1-L10)
   research/foundation/_engine/attack_registry.yaml (B1-B8 + D1)
   (Engine immune memory. MUST clear against attack_registry before any VALIDATE.)

5. research/foundation/_engine/next_cycle_proposals.md
   (Cycle 002 selection LOCKED: H5 cubes-behavior + I-B1 可转债. Literature priors included.)

6. research/foundation/_sync/codex_outbox.md
   (Codex's last message before going offline. He may return mid-cycle.)
```

After reading these you know: cycle 001 closed; A1 family dead; cycle 002 = H5 + I-B1; B8 axis-stability gate is ACTIVE.

---

## §2 — Cycle 002 deliverables (13 bounded artifacts, HARDENED 2026-05-24)

You are working until ALL 13 exist OR a STOP condition fires. Token unlimited; ambition is now constructive output, not budget conservation. Every artifact must have HARD EVIDENCE (numbers, file paths, commit hashes), not "skeleton" placeholders.

### Strategy layer (verdicts + axis audits)

1. **H5 Behavioral Adverse Selection verdict** (`research/smart_consensus/verdict_2026-05-25_H5_foundation.md`):
   - TL;DR VALIDATED | REJECTED | INCONCLUSIVE per §6 matrix
   - Gross/net alpha, t-stat, train/test breakdown table, sub-period IC table, ablation against EACH attack registry entry (B1-B8 + D1), sensitivity to top_pct ∈ {0.10, 0.20, 0.30} and hold_days ∈ {5, 10, 20}
   - MUST include: B8 axis pass report, matched-control specification, sample size N per period
   - MUST be co-signed: commit messages from BOTH implementer AND attacker sessions reference this file before considered final

2. **H5 behavioral selector code**: `research/smart_consensus/cube_behavior_features.py` with at least 3 features (turnover percentile, lag vs leader, attention-spike entry). Each feature has unit test or empirical sanity check committed.

3. **H5 confirmation proxy verdict** (per Codex's phased D1 — H5 NOT VALIDATED until ≥2 proxies confirm):
   - Pick ONE of: 融资买入 (margin trading) OR 龙虎榜 (top-5 broker) — whichever has better data coverage
   - Same verdict format as #1
   - If primary proxy is INCONCLUSIVE_PENDING_CONFIRMATION, this proxy is the confirmation; if conflicts, H5 is REJECTED with cross-proxy disagreement noted

4. **I-B1 可转债套利 verdict** (`research/smart_consensus/verdict_2026-05-25_I_B1_foundation.md`):
   - Two sub-strategies tested: 双低 (low conversion premium × low absolute price) + 强赎博弈 (anti-callaway anticipation)
   - Per-strategy: full verdict format same as #1
   - Combined I-B1 family verdict with both sub-strategies' interaction analysis

5. **I-B1 data fetcher**: `research/data_prep/fetch_cb_data.py` — uses akshare `bond_zh_cov` (转债基本信息) + `bond_zh_cov_value_analysis` (估值) + historical price. Caches to `data/bonds_cb/`. Must run end-to-end on at least 50 转债 with output validated (not empty, dates 2018+).

6. **B8 gate enforcement evidence**: ALL hypotheses passing through cycle 002 must have `research/foundation/_engine/axis_stability_reports/<id>_axis.md` committed showing PASS. If any axis fails B8 → STOP with axis swap. H5 cube-behavior axis MUST be audited as a NEW axis (not the killed skill axis).

### Quality layer (cross-check + ablation)

7. **Agent red-team reviews per commit**: after each strategy commit, spawn `general-purpose` sub-agent with full attacker prompt (per §4). Sub-agent's finding appended to `research/foundation/_sync/auto_red_team.md` with header `## <commit-sha> <hypothesis-id> <verdict>`. **At least 1 per strategy commit, BLOCKING** — implementer cannot proceed to next commit until red-team writes SAFE or NEEDS-FIX (not BLOCK).

8. **Seed sensitivity per strategy**: attacker session independently re-runs each strategy with 5 different random seeds (42, 43, 44, 45, 46). Result table in `research/foundation/_engine/seed_sensitivity_<id>.csv`. Verdict t-stat must be stable across seeds (range < 1.0 σ), else flag as fragile.

9. **Ablation matrix**: for each VALIDATED or INCONCLUSIVE hypothesis, attacker session generates ablation matrix (each attack-registry mitigation rolled back individually, baseline magnitude reported). Saved to `research/smart_consensus/output/<id>_ablation.csv`. Cycle 001 already did this for A1 family; cycle 002 must do it for H5 + I-B1.

### Engine scaffolding (now REAL not skeleton)

10. **ML proposer ACTUAL run** (not just skeleton): `research/foundation/_engine/proposer.py` implemented with: AlphaForge-style expression mining over Alpha158 from `~/jz_code/qlib/` + Codex's guardrails (PROPOSED-only, prior 0.05, lineage logged, future-field auto-REJECT, max 10 per epoch). Run once → write `research/foundation/_engine/proposer_run_001.csv` with 10 candidate factors, B8 audit results, and lineage. NOT integrated into cycle yet; just proving the pipeline works.

11. **Paper tier with REAL READMEs + first entry**: `research/foundation/_engine/paper_book/README.md` + per-state docs (PAPER/, DEPLOYABLE/, FAILED_LIVE/). If H5 or I-B1 VALIDATEs in cycle 002, create the first PAPER/<id>/ directory with day-1 mock entry as proof of pipeline.

12. **Cross-market data-contract scout with REAL data sample**: `research/foundation/_engine/data_extensions/cross_market_late_chasing.md` — defines data contracts AND fetches 30-day sample of: (a) Binance BTC perpetual funding rate, (b) at least 1 active Polymarket prediction market open interest. Sample committed as `data_extensions/sample_funding_30d.csv` + `sample_polymarket_30d.csv`. Demonstrates pipeline reachable from this Mac before cycle 003 commits to using it.

13. **Cycle 002 retrospective + cycle 003 proposals**: `cycles/cycle_002_2026-05-25.md` retrospective filled with empirical numbers + lessons (L11+) + new attacks (B9+) if found. `next_cycle_proposals.md` updated with at least 3 cycle 003 candidates: (a) deeper H5 variants if H5 VALIDATEd, (b) I-A1 国债逆回购 (canonical, easy verify), (c) ML proposer top-3 candidates from #10. PR #6 comment posted with cycle 002 TL;DR + retraction confirmation for verdict_2026-05-23.md.

---

## §3 — Hard kill criteria (Engine §6, NON-NEGOTIABLE)

ANY one fires → write STOP in `_sync/control.md` + exit:

1. `research/foundation/self_test.py` not 7/7 PASS for current data state → STOP, fix infra first.
2. Train and Test alpha disagree in sign (any hypothesis) → REJECT that hypothesis.
3. Ablation: removing any single attack-registry mitigation returns ≥80% of artifact magnitude → REJECT.
4. Net annualized alpha after survivorship discount (1-3%/yr) and cost < 0 → REJECT.
5. Soft: post-fix annualized alpha > 10% → MORE bug suspicion, demand extra ablation before VALIDATE.
6. **B8 axis-stability**: any hypothesis whose selection axis has median quarter-over-quarter rotation > 20% → BLOCKED from RUNNING.

Hard token cap: 5M total across this session. Self-report usage in cycle file at each commit.
Hard wall-time cap: 24 hours. Past this, STOP regardless.

---

## §4 — How to use single-brain tools to compensate for Codex offline

### Agent sub-agent red-team pattern (REQUIRED per deliverable §2.4)

After each strategy commit, run:

```python
Agent(
    description="Red-team review of <hypothesis> commit",
    subagent_type="general-purpose",
    prompt="""You are an adversarial code auditor. Read commit <sha> on
branch patch/methodology-audit-2026-05-23. Goal: find weaknesses that
would invalidate the strategy's eventual verdict.

Specifically check:
1. Selector look-ahead (using future data to define historical cohort)?
2. Mask logic on raw vs rank (B3-i pattern repeat)?
3. Tie-order bias (B7) — does factor_fn return ties without jitter?
4. Universe contamination (CB/STAR/B-shares leaking in)?
5. Train/test split honored (no leakage)?
6. Cost model + survivorship discount applied?
7. Selection-axis stability (B8) — is this on the rolling skill axis again?

Report findings as: SAFE / NEEDS-FIX / BLOCK + concrete file:line.
If BLOCK, the engine cannot proceed. Under 500 words."""
)
```

Append output to `research/foundation/_sync/auto_red_team.md` with header `## <commit-sha> <hypothesis-id>`. Commit.

### Skill invocations (use when applicable)

- **`/code-review`** — invoke after each strategy code commit before backtest.
- **`/verify`** — invoke after each Backtest to confirm output is real (not silently NaN).
- **`/security-review`** — invoke if you touch any credentials / API keys / network config.

### Parallel sub-agent dispatch

Use a single message with multiple Agent tool calls when doing independent work (e.g., simultaneously: implement H5 + draft cross-market scout + audit B8 on H5 axis). Each runs in own context window. Returns to you for integration.

---

## §5 — Cycle 002 execution sequence (recommended)

```
1. Read §1 files. Then read this entire bootstrap.
2. Self_test sanity: `bash scripts/overnight/pulse.sh` then if green
   `.venv/bin/python research/foundation/self_test.py` confirms 7/7.
3. Pre-work: write B8 audit reports for both H5 and I-B1 axes:
   - H5 axis = cube behavioral features (turnover percentile, lag vs leader).
     This is a NEW axis; you must compute it first, then audit.
     If it fails B8 → switch to "rolling 90-day turnover percentile only"
     as fallback selector, audit that.
   - I-B1 axis = 转债 universe (no skill-cube axis); B8 N/A or trivial.
4. Implement H5:
   a. Write research/smart_consensus/cube_behavior_features.py
      (turnover_percentile, lag_vs_leader, attention_spike features).
   b. Write research/foundation/strategies_h5.py wrapping EventDriven
      with matched control (board+liq+size+momentum+industry).
   c. Commit. Spawn Agent red-team (§4 pattern). Append to auto_red_team.md.
   d. Run via run_all_hypotheses.py.
   e. Apply §6 kill criteria. Write verdict.
5. Implement I-B1:
   a. research/data_prep/fetch_cb_data.py (akshare 转债 + 集思录).
   b. research/foundation/strategies_i_b1_double_low.py.
   c. Same commit + red-team + backtest + verdict cycle.
6. Scaffolding (parallel sub-agents OK):
   - proposer.py skeleton
   - paper_book/README.md
   - data_extensions/cross_market_late_chasing.md
7. Retrospective + cycle 003 proposals.
8. PR #6 update: post comment with cycle 002 verdict TL;DR.
```

---

## §6 — Sync protocol (still active even with Codex offline)

Each major action:

```
1. Write _sync/claude_outbox.md with what you just did + open Qs.
2. Update _sync/control.md (phase, who-acts-next, last_sha).
3. Append _sync/history.md (one line).
4. git add _sync/* && git commit -m 'sync(claude): ...'
```

If Codex comes back mid-cycle (`_sync/codex_outbox.md` updated by him), read his outbox before next action. He may push back on something you committed.

---

## §7 — STOP triggers and how to STOP gracefully

If any hard criterion fires:

```
1. Write _sync/control.md:
   phase: STOP
   who_acts_next: johnny
   notes: "STOP reason: <specific kill criterion + which file/line/data>"
2. Update _sync/claude_outbox.md with full diagnosis.
3. Append _sync/history.md.
4. Commit with message starting 'STOP(cycle_002): <reason>'.
5. Exit /goal cleanly.
```

DO NOT keep working past a STOP. The STOP is the deliverable in that case.

---

## §8 — Memory hygiene

Use the memory system per the project CLAUDE.md instructions. Specifically:
- Save NEW feedback memory if Johnny corrects you in this session.
- Save NEW project memory for cycle 002 final state.
- DO NOT save ephemeral "in progress" notes — that's what cycle files are for.

---

## §9 — When done

When all 13 deliverables in §2 exist AND no STOP fired:

```
1. Final commit with message: 'verdict(cycle_002): <H5 + I-B1 + I-B1-confirm outcomes>'
2. _sync/control.md phase = DONE, who_acts_next = johnny.
3. Write a fresh MORNING_BRIEF.md (overwrite) with:
   - One-line TL;DR per verdict
   - List of all 13 deliverables with sha references
   - Cycle 003 candidate ranking
   - Anything Johnny needs to immediately action vs nice-to-know
4. Exit /goal.
```

Johnny reviews on wake-up.

---

## §10 — Dual-session role discrimination (read your role from GOAL_STRING)

Cycle 002 runs as **dual Claude sessions** (no Codex/wwcloud right now). Your GOAL_STRING starts with either `role: IMPLEMENTER` or `role: ATTACKER`. Determine role at session start:

### Role: IMPLEMENTER
- Owns: writing strategy code (`research/foundation/strategies_*.py`, `research/smart_consensus/cube_behavior_features.py`, `research/data_prep/fetch_cb_data.py`), running backtests via `run_all_hypotheses.py`, drafting verdict files, updating `_sync/implementer_outbox.md`.
- Cannot self-approve a commit — must wait for attacker session to write SAFE/NEEDS-FIX (not BLOCK) on each strategy commit before next major step.
- Runs Agent sub-agent inline for routine sanity checks (not the same as attacker session's red-team).
- Owns deliverables §2.1, §2.2, §2.4, §2.5, §2.10, §2.11, §2.12, §2.13.

### Role: ATTACKER
- Owns: red-teaming every implementer commit (`_sync/auto_red_team.md` append-only), running B8 axis-stability audits (`axis_stability_reports/<id>_axis.md`), seed sensitivity verification (`seed_sensitivity_<id>.csv`), ablation matrices (`<id>_ablation.csv`), updating `_sync/attacker_outbox.md`.
- Runs git rebase/pull frequently to pick up implementer's commits.
- Can issue BLOCK if a commit fails attack-registry check → implementer must fix before proceeding.
- Owns deliverables §2.3, §2.6, §2.7, §2.8, §2.9. Co-signs §2.1, §2.4 (verdicts require both signatures).

### Coordination (file ownership to avoid conflict)

| File | Owner | Reader |
|---|---|---|
| `research/foundation/strategies_*.py` | IMPL | ATK reads |
| `research/smart_consensus/cube_behavior_features.py` | IMPL | ATK |
| `research/data_prep/fetch_cb_data.py` | IMPL | ATK |
| `_sync/implementer_outbox.md` | IMPL | ATK |
| `_sync/attacker_outbox.md` | ATK | IMPL |
| `_sync/auto_red_team.md` | ATK (append-only) | IMPL |
| `_sync/control.md` | BOTH | BOTH (rebase) |
| `_sync/history.md` | BOTH (append-only) | BOTH |
| `axis_stability_reports/<id>.md` | ATK | IMPL |
| `seed_sensitivity_*.csv` | ATK | IMPL |
| `<id>_ablation.csv` | ATK | IMPL |
| `verdict_2026-05-25_*.md` | IMPL drafts, ATK co-signs | BOTH |

Workflow per IMPL commit:
1. IMPL: write code → commit → `_sync/implementer_outbox.md` update → push (or just rebase-base if no remote)
2. ATK: pull → read commit diff → red-team → append `_sync/auto_red_team.md` → write SAFE/NEEDS-FIX/BLOCK + commit
3. IMPL: pull → if BLOCK, fix and recommit; if NEEDS-FIX, address and recommit; if SAFE, proceed to next strategy
4. Repeat

---

## §11 — Success criteria for "constructive results" (per Johnny 2026-05-24)

Johnny said "我醒来一定要看到建设性的成果" + "token 无限". This translates to:

**Acceptable cycle 002 outcomes** (in order of preference):

🥇 **One+ VALIDATED hypothesis**: H5 or I-B1 sub-strategy passes all §6 kill criteria with net annualized alpha > 1%/yr post-discount. Triggers paper_book/ first entry (§2.11). This is the WIN case — it means cycle 002 produced a real candidate alpha.

🥈 **All REJECTED but with rich diagnosis**: H5 and I-B1 die for SPECIFIC and INSTRUCTIVE reasons (not just "noise"). Each REJECT adds a new attack-registry entry OR confirms an existing one in production. Cycle 003 has 3+ concrete next candidates based on what failed.

🥉 **STOP with hard methodology lesson**: a hard kill fires that EXPOSES a new attack family (e.g., "B9 — turnover-feature look-ahead in behavioral selector"). Even if no verdicts complete, the engine immune system grew. Add to attack_registry as production attack.

❌ **UNACCEPTABLE outcomes**:
- Silent hang (no commits in 30+ min) → trigger STOP not silent stall
- "Skeleton" deliverables with no actual content (cycle 002's whole point is HARDENED §2 with empirical numbers)
- Verdicts without co-sign (implementer-only verdict is invalid per §10)
- Token usage without verdict outputs (since token unlimited, no excuse to give up)
- Skipping B8 axis audit (engine immune system blocks this)

**Acceptable runtime**: 4-10 hours wall time. 24h hard cap per §3.

---

**Last updated**: 2026-05-24 HARDENED for cycle 002 dual-session execution.
**Next session**: read this file (full), check your role from GOAL_STRING, start at §1.
