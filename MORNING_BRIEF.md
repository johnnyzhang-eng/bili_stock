# Morning Brief — 2026-05-24

When you wake up. One-minute snapshot of where we are.

## Yesterday's headline

**Cycle 001 closed: all 4 hypotheses (A1, H2, H3, H4) REJECT.**

A1 verdict_2026-05-23.md ("smart cube avoidance +13.91%/yr") is officially retracted. Foundation cycle 001 rerun gave α=+0.15%/period, t=+0.12 → noise. The original number was 100% artifact of 4 compounding bugs (B1+B2+B3-i+B5-i, all locked in attack_registry).

Canonical replacement: `research/smart_consensus/verdict_2026-05-24_foundation.md`.

## What worked

- Two-brain cross-check (Claude+Codex) found 0-overlap 4 CRITICAL bugs.
- Engine immune system (kill criteria §6) caught every false-positive.
- Codex's ablation isolated B3-i mask as the single largest driver (-4.24σ alone of -4.76 total collapse).

## What changed overnight (while you slept)

**Engine got smarter, not the model.** 4 durable upgrades:

1. **B8 axis-stability gate** (`research/foundation/_engine/axis_stability_audit.py`) — executable code that BLOCKS hypothesis families from RUNNING if their shared selection axis has cohort rotation > 20%/Q. Tested on cubes rolling_ann_gain: median 33.7%/Q → automatic BLOCK (which is exactly what we would have wanted at cycle 001 start to skip 4 cycles of wasted effort).
2. **fetch_fundamentals.py D1 patch** — pre-filters panel to A-share prefixes at source. Next time `panel_quarterly.csv` is built, no manual filtering required.
3. **External literature ingestion for H5** — 5 academic priors (Barber-Odean attention, PLOS One 2025 Xueqiu, Demirer-Kutan A-share herding, Liu et al follower lag theory). Wrote into `_engine/next_cycle_proposals.md`. H5 prior_pr_alpha revised 0.30 → 0.40 given external corroboration.
4. **This morning brief** so you don't need to read 16 commits to know where we are.

## Current state

```
Branch:   patch/methodology-audit-2026-05-23 (local, not pushed to remote)
HEAD:     ~30 commits since branch creation
Cycle 001: CLOSED (all REJECT)
Cycle 002: PROPOSED (H5 cubes-behavior + I-B1 可转债)
Codex:    OFFLINE (last commit 7a7b2da, then his outbox)
wwcloud:  OFFLINE (504 gateway, account pool exhausted as of 03:30)
```

## Next action menu (you pick)

### Option A — Launch cycle 002 single-brain via /goal
```bash
bash scripts/overnight/launch.sh
```
Risks: no cross-check on H5 or I-B1. B8 gate will catch axis-instability automatically, but methodology bugs in H5 selector design have no peer review. Suggest only if you accept "REJECT is fine" outcome.

### Option B — Wait for Codex / wwcloud, do nothing-risky in meantime
Run `bash scripts/overnight/pulse.sh` periodically to see if either comes back. Engine state is fully durable in git; nothing decays.

### Option C — Do prep work that doesn't need cross-check
- Write H5 `cube_behavior_features.py` (turnover percentile, lag vs leader cubes, attention spike detection) — pure feature engineering, can be audited later
- Pull I-B1 转债 data via `research/data_prep/...` similar pattern
- Run `repo_scout.py` on cycle 002 infrastructure needs

### Option D — Sleep more, decide later
Engine state is fully captured. Branch can stay local indefinitely.

## What to ask Codex when he returns

His last 4 outbox asks (in `research/foundation/_sync/codex_outbox.md` line 139+):
1. Accept/reject my D1 phased H5-multi counter-spec → I accepted in 03:30 outbox
2. Accept/reject D3 Track C as data-contract scout → I accepted
3. Claude begin A1/H3/H4 implementation → DONE (commit 36a6791)
4. Expose `run(data, verbose) -> BacktestResult` in each strategy → DONE

He'll also want to review:
- The new B8 axis-stability gate (he had related Codex review patches earlier)
- H5 prior bump from 0.30 → 0.40
- Whether single-brain cycle 002 launch is OK or hold

## Files to skim if you want depth (in order)

1. `research/smart_consensus/verdict_2026-05-24_foundation.md` — cycle 001 verdict
2. `research/foundation/_engine/negative_log.md` — N1 entry (what we learned)
3. `research/foundation/_engine/lessons_learned.md` — L9 / L10 (axis instability)
4. `research/foundation/_engine/axis_stability_reports/cubes_rolling_ann_gain.md` — B8 verdict on the cubes axis
5. `research/foundation/_engine/next_cycle_proposals.md` — H5 + I-B1 spec with literature

## My honest read

Cycle 001 worked as engine designed. **You got a clean negative**, not a missed positive. The repo is now smarter than 24 hours ago: 4 CRITICAL bugs documented + axis-stability gate enforces the highest-level lesson. Even if every future cycle rejects, the engine compounds.

Cycle 002 is **not urgent**. Without Codex, single-brain is suboptimal but B8 gate gives one safety net. Decide A-D when you're rested.

— Claude (Opus 4.7), 2026-05-24 ~04:00
