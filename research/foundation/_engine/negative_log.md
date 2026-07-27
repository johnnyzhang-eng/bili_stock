# Negative Log — Alpha Discovery Engine

Append-only record of REJECTED hypotheses with root-cause attribution. The point: future cycles read this and avoid replaying the same death.

Each entry must answer:
1. What did we think we were testing?
2. What was the result?
3. What attack(s) from `attack_registry.yaml` killed it?
4. What did we learn that informs the next hypothesis?

---

## N1 — Cycle 001: A1+H2+H3+H4 all REJECT (2026-05-24)

**What we tested**: Four formulations of the "Xueqiu smart cube → A-share alpha" thesis family, all using rolling 12M ann_gain as the cube-selection axis (skill axis).

- **A1** static holding avoidance, cross-sectional quarterly
- **H2** smart-cube cluster-buy event, long
- **H3** smart-cube mass-exit event, predict underperformer cohort
- **H4** skill-weighted buy-intensity, cross-sectional quarterly

**Result**: all four REJECT.

| ID | n | α/period | t | Why killed |
|---|---|---|---|---|
| A1 | 35 | +0.15% | +0.12 | §6 #4 alpha ≈ 0; Train −1.84 / Test +2.51 signs disagree |
| H2 | 109 | +0.90% | +0.71 | §6 #2 Train +2.70 / Test −2.44 signs disagree; OOS negative |
| H3 | 111 | +0.33% | +0.29 | Wrong sign for thesis (wanted negative); Train +1.18 / Test −1.37 disagree |
| H4 | 35 | −1.17% | −0.99 | §6 #4 negative alpha; Test t=−2.70 wrong-way at quarterly |

Supplemental size/liquidity-matched audit (`cycle001_matched_baseline.py`) does not rescue the cross-sectional cases: A1 `+0.57%/period, t=+0.70`; H4 `-1.66%/period, t=-1.31`.

**Root cause**: **the skill axis on cubes data is too unstable to generate persistent signal**. Every hypothesis showed Train/Test sign divergence. Cubes that satisfy 25–200%/yr rolling ann at one date frequently don't at another, so the "smart cohort" rotates faster than any derivative signal can persist. This is an axis problem, not a per-hypothesis bug.

**Skill-axis hypothesis family is exhausted on cubes data.** Future cube hypotheses must use behavioral observables (turnover, lag, abnormal-attention timing — see H5 in `hypothesis_registry.yaml`) and abandon cumulative skill metrics.

**Lessons added to lessons_learned.md**: L9 — "skill axis is unstable" + L10 — "Train/Test sign divergence is the canonical death signature for axis instability, not just for hypothesis-specific bugs".

**Cycle 002 spawn**:
- H5 (Codex's Behavioral Adverse Selection) — owner Codex
- I-B1 可转债套利 (canonical inefficiency_hunting catalog) — owner Claude

## N2 — Cycle 002: H5 cube-behavior axis BLOCKED before RUNNING (2026-05-24)

**What we tested**: H5 Behavioral Adverse Selection as a per-cube behavior-selection axis over the full 926-cube Xueqiu universe. V2 explicitly removed `smart_cubes_v1.csv`, current `annualized_gain_rate`, follower count, and owner profile fields. Eligibility was point-in-time: cube has at least 8 successful rebalancing events in the trailing 180 days.

**Result**: **REJECTED-PRE-RUNNING / STOPPED for H5 in Cycle 002**. No alpha backtest was allowed because B8 fired before strategy construction.

| Axis | Pool | Features | Median rotation | P75 rotation | B8 verdict |
|---|---:|---|---:|---:|---|
| H5 V2 composite | 926 cubes | turnover, lag-vs-leader, attention-spike rate, concentration intensity | 54.4%/Q | 65.6%/Q | BLOCK |
| H5 turnover-only fallback | 926 cubes | turnover percentile only | 43.7%/Q | 56.8%/Q | BLOCK |

**Attack(s) that killed it**: B8 selection-axis instability. The pre-agreed fallback axis also failed, so H5 cannot enter RUNNING this cycle.

**Root cause**: cube-identity cohorts are too unstable even when defined by point-in-time behavior rather than current skill. The problem is not only the old "smart cube" skill axis; the cube unit itself is a volatile selector.

**Lesson**: future Xueqiu/cube hypotheses should avoid selecting *which cubes* to follow/fade. The viable reformulation is stock-level pressure: which stocks are over-bought by unstable/high-turnover/late-entry cubes, with a B8 audit on the stock cohort and matched stock controls.

Negative log open; cycle 002 continues with I-B1.
