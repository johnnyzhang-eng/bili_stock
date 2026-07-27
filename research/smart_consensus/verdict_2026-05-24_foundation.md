# A1 Family — Foundation Cycle 001 Verdict (2026-05-24)

**Branch**: `patch/methodology-audit-2026-05-23`
**Engine**: research/foundation/_engine/ENGINE_SPEC.md v0.1
**Cycle file**: research/foundation/_engine/cycles/cycle_001_2026-05-24.md
**Runs**: research/foundation/run_all_hypotheses.py → research/smart_consensus/output/cycle001_foundation_reports.md
**Old verdict (RETRACTED)**: research/smart_consensus/verdict_2026-05-23.md

**Variant note (per Codex review)**: this is the **quarterly foundation variant**. Does NOT reproduce the original weekly verdict construction; it is the methodologically valid test of the same hypothesis family at the cadence foundation framework supports.

---

## Closure verification

Codex re-ran both gates on 2026-05-24 before co-signing Cycle 001 closure:

- `python research/foundation/self_test.py` → **7/7 PASS** for the current data/framework state.
- `python research/foundation/run_all_hypotheses.py` → reproduced the table below and wrote `research/smart_consensus/output/cycle001_foundation_reports.md`.
- `python research/foundation/cycle001_matched_baseline.py` → wrote the stricter size/liquidity-matched audit at `research/smart_consensus/output/cycle001_matched_baseline.md`.

Random-control / matching evidence:

- A1 and H4 use `Universe.broad(mcap_range=(30, 500), min_turnover_20d=0.15)` and foundation `Backtest(random_control=True)`. The supplemental matched audit then re-scores each pick against a random non-pick from the same market-cap decile and 20-day-turnover decile. Result: A1 `+0.57%/period, t=+0.70`; H4 `-1.66%/period, t=-1.31`. Both remain REJECT.
- H2 and H3 are event-driven and use same-stock random non-event days within a ±90 trading-day regime window, so size/liquidity/board are fixed by stock identity while market-regime drift is bounded.
- All four runs apply foundation cost models and train/test splits before verdict assignment.

---

## TL;DR — all four REJECT

| ID | Thesis | n | α/period | t | Verdict |
|---|---|---|---|---|---|
| **A1** | Smart cube avoidance | 35 | +0.15% | **+0.12** | **REJECT** |
| **H2** | Smart cube cluster-buy long | 109 | +0.90% | **+0.71** | **REJECT** |
| **H3** | Smart cube mass-exit avoid cohort | 111 | +0.33% | **+0.29** | **REJECT** |
| **H4** | Skill-weighted buy-intensity | 35 | -1.17% | **-0.99** | **REJECT** |

**Skill axis is dead on cubes data.** No formulation tested — static holding (A1), event-flow buy (H2), event-flow exit (H3), or weighted intensity (H4) — produces alpha that survives foundation framework's hard kill criteria (§6).

---

## Engine §6 kill criteria fired per hypothesis

### A1 (smart cube avoidance, quarterly)

- **Train alpha -1.84%/期 (t=-0.99) vs Test alpha +2.51%/期 (t=+1.49)** — signs disagree → §6 criterion 2 fires.
- Full t=+0.12 → §6 criterion 4 (alpha effectively zero, post-cost negligible).
- Original weekly verdict reported IC=-0.0164 / t=-4.97 / +13.91%/yr excess. After 4 CRITICAL bug fixes and foundation framework, all three numbers gone.

### H2 (cluster-buy, event-driven)

- **Train alpha +2.70%/期 (t=+1.58) vs Test alpha -2.44%/期 (t=-1.40)** — signs disagree → §6 criterion 2 fires.
- Full t=+0.71 → §6 criterion 4.
- Cluster-buy "consensus formation" thesis dies on OOS.

### H3 (mass-exit avoid cohort, event-driven)

- Full t=+0.29 with **wrong sign for thesis** (positive alpha when thesis predicted negative for the predicted-underperformer cohort).
- Train +1.18 / Test -1.37 — partial sign disagreement; the "wrong-sign" reading on Train is the harder kill.
- Mass-exit "insider info diffusion" thesis dies; smart-cube exits do NOT systematically signal underperformance.

### H4 (skill-weighted buy intensity, cross-sectional)

- **Full alpha -1.17%/期 / t=-0.99** — negative alpha → §6 criterion 4 fires.
- **Test alpha -3.63%/期 / t=-2.70** — significantly negative IN THE OOS PERIOD. Could read as "skill-weighted buying is wrong-way at quarterly horizon". Either way, no positive alpha thesis.

---

## Common pattern: skill axis exhausted

All 4 hypotheses share two architectural choices:

1. **Skill filter via `rolling_ann_gain.csv`** — cubes must pass ex-ante 25-200%/yr rolling 12M gain at signal time.
2. **Quarterly (or 5-trading-day event) cadence** — imposed by foundation framework.

The pattern across verdicts is **temporal instability**: every hypothesis has Train and Test diverging. The skill-axis selection criterion is itself unstable — cubes that satisfy 25%-200% rolling ann at one date often don't at another, so the "smart cohort" rotates faster than any signal it generates can persist.

**Implication**: it is not just that the 9-month-old A1 was buggy. The class of strategies that use cube quality as the selection axis is fundamentally unsuited to cube data's signal-to-noise ratio. Cycle 002 must abandon the skill axis entirely.

---

## Negative log entry (cross-reference)

See `research/foundation/_engine/negative_log.md` for the canonical entry. Root cause: **rolling skill axis on cubes data is unstable enough that any signal derived from it shows Train/Test sign reversal**.

---

## What this verdict does NOT claim

- It does NOT claim the Xueqiu cubes data itself is worthless.
- It does NOT claim there is no anti-signal in retail/social trading data.
- It does NOT claim H5 (Codex's Behavioral Adverse Selection) is doomed; H5 explicitly abandons the skill axis and is the cycle 002 resurrection candidate.

What it DOES claim: **the specific skill-axis-driven hypothesis family (A1+H2+H3+H4) is exhausted on this data**. Future cube-based hypotheses must use behavioral observables (turnover, lag, abnormal-attention timing) not cumulative skill metrics.

---

## Honest comparison to verdict_2026-05-23.md (RETRACTED)

| Metric | Original verdict (2026-05-23) | Foundation cycle 001 |
|---|---|---|
| IC reported | -0.0164 (t=-4.97) | not applicable (foundation reports per-period alpha) |
| Mean alpha excess | +13.91%/yr | +0.15% / 63-day period → ~+0.86%/yr at quarterly |
| Train OOS direction | "Train + Test 同号" | Train -1.84, Test +2.51 — disagree |
| Survivorship-adjusted | claimed +10-12%/yr | post-fix close to zero, post-discount negative |
| Verdict | VALIDATED_FOR_NEXT_STAGE | **REJECTED** |
| Status | RETRACTED 2026-05-24 | This file is the canonical replacement |

The single largest correction came from B3-i (rank.pct mask bug): per Codex ablation (`research/smart_consensus/ABLATION_RESULTS.md`), B3-i alone moved the 2022+ window IC t from -4.76 → -0.52. The original "IC=-4.97 cross-sectional rank skill" was effectively 100% selection-effect dressed as IC. See `research/foundation/IC_DELTA_2026-05-23.md` for the empirical sequence.

---

## Cycle 002 spawn (locked in `next_cycle_proposals.md`)

Default selection per `cycles/cycle_001_2026-05-24.md` spawn rules:

1. **H5 — Behavioral Adverse Selection** (Codex's proposal). Cubes resurrection via behavior axis (turnover percentile, lag vs leader cubes, entry timing relative to abnormal attention) + strict matched control (board+liq+size+momentum+industry). Per Codex's phased D1: cycle 002 H5 = cubes + 1 additional A-share proxy (preferably 融资买入 or 龙虎榜), not 4 proxies at once.
2. **I-B1 可转债套利** (canonical catalog kickoff from `~/jz_code/research_log/inefficiency_hunting.md`). Highest-evidence (✓✓ mechanism) alternative path. Owner: Claude.

External feed pulls for cycle 003+:
- arxiv "A-share retail sentiment", "Chinese mutual fund herding"
- ~/jz_code/research_log/repo_scout.py for execution infrastructure
- ML proposer (AlphaForge + qlib Alpha158) as quarantined PROPOSED-only source for cycle 003+

---

## Sign-off

- **Implementer (Claude)**: implementations + Backtest runs verified; numbers reproducible via `python research/foundation/run_all_hypotheses.py`.
- **Attacker (Codex)**: independently re-ran `self_test.py`, `run_all_hypotheses.py`, and `cycle001_matched_baseline.py` on 2026-05-24; co-signs all four REJECT verdicts. Residual caveat is not directionally material: the quarterly foundation variant is the valid framework test, not a weekly reconstruction of the retracted artifact.
- **Arbitrator (Johnny)**: D1-D4 super-brain judgments delivered 2026-05-24 03:35 align with Codex's refinements; engine spec captures them.

**Cycle 001 closed. Cycle 002 spawn pending Johnny launch authorization.**
