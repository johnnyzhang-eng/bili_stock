# Lessons Learned — Cross-Cycle Methodology Insights

Distinct from `attack_registry.yaml` (technical bug list). This file captures higher-order patterns: how to think about A-share alpha discovery, what kinds of theses tend to die, what kinds tend to survive.

---

## L1 — Cross-sectional rank skill vs binary held-vs-not-held selection effect (2026-05-24)

The A1 audit revealed these are **two distinct quantities**, often confused:
- **Rank skill**: among held stocks, does signal order predict return order? Tested by IC on raw-signal-mask + in-pool re-rank.
- **Selection effect**: does the "held set" itself have different mean return than not-held? Tested by binary cohort comparison with size/liq controls.

A signal can have one without the other. A1's reported IC=-4.97 conflated them. Future hypotheses must report BOTH separately and apply different controls (rank skill needs in-pool comparison; selection needs cohort matching).

## L2 — Snapshot data is forward-looking by default (2026-05-24)

Any cube/trader/fund identifier whose attributes are computed as of TODAY is contaminated when applied to historical periods. The default assumption must be "this list embodies survivor selection until proven otherwise". Codex's required ex-ante rolling reconstruction is the only safe path.

Generalizes beyond cubes: any third-party scoring (Morningstar fund rating, S&P credit rating, broker analyst recommendations) carries the same issue.

## L3 — Foundation framework requires tie-breaking jitter on all factor_fn (2026-05-24)

A constant factor (`return 0.0`) does NOT produce alpha=0 in foundation because `sort_values()` tie-break uses DataFrame order. NULL self_test gave t=+2.93 before jitter. All factor_fn implementations must include deterministic stable_jitter on any tied segment until foundation refactors `select()` to add internal jitter.

## L4 — Annualization formula must match cycle (2026-05-24)

`alpha_mean × 52` is wrong when the per-period horizon is not 1 week. Use `alpha_mean × (252 / hold_days)`. Original A1 verdict mixed weekly IC and monthly CAGR formulations and lost track.

## L5 — Survivorship discount applies to annualized number (2026-05-24)

The 1-3%/yr survivorship inflation correction (per AUDIT_FINDINGS_2026_04_27 §A股退市 6/150) subtracts from the ANNUALIZED alpha, not from per-period. Forgetting this makes the discount look smaller than it is.

## L6 — Anti-rooting clause: high alpha after fixes = more suspicion, not less (2026-05-24)

If the post-audit annualized alpha exceeds 10%, the prior probability that another bug is still hiding is HIGHER than the prior that we just discovered a 10%/yr alpha. The 8-round project history validates this; the median backtest deflates 70% on rigorous audit. Bake this into kill criteria.

## L7 — The alpha library is `inefficiency_hunting.md`, not whatever data we have lying around (2026-05-24)

The 9 months on cubes data were exploratory — using available data to fish for alpha. That's an OK approach if you don't have a curated library. Johnny's `~/jz_code/research_log/inefficiency_hunting.md` IS such a library, with 6 ✓✓-grade canonical inefficiencies. Cycle 002+ should default to verifying canonical entries before fishing in held data.

This inverts the workflow:
- Wrong: "I have cubes data → what alpha can I extract?"
- Right: "Catalog says I-B1 可转债套利 has ✓✓ mechanism + 5-15%/yr historical → use foundation engine to verify on current data → deploy or REJECT"

The engine framework doesn't care which entry it's verifying — foundation.Backtest treats them identically. The bottleneck is hypothesis selection. The catalog already did that selection work.

## L8 — Engine does not stand alone; it composes with existing infrastructure (2026-05-24)

`~/jz_code/` has 23 repos including qlib (CSI300 data preloaded), AlphaForge (factor mining), and 5+ alert/monitor scripts. Engine cycles should COMPOSE with these (e.g., qlib generates factor candidates → engine verifies them) rather than reinvent. ENGINE_SPEC §8 Tier 0-5 lists the leverage chain.

## L9 — Selection-axis instability is a category of bug above individual hypothesis bugs (2026-05-24)

Cycle 001 killed all 4 hypotheses (A1/H2/H3/H4) that shared the same "rolling skill" cube-selection axis. The shared death pattern was Train/Test sign divergence, NOT hypothesis-specific issues.

This tells us that BEFORE testing a hypothesis family, we should audit whether the SELECTION AXIS (the criterion used to pick whose signal to listen to) is itself stable enough. An unstable axis pollutes every hypothesis built on it.

Concrete diagnostic: if the cohort selected by the axis rotates more than ~20% per quarter, no signal derived from the cohort can have OOS stability greater than that rotation. The "smart cube" cohort here rotated faster than that.

**Implication for engine**: add `axis_stability` audit to attack_registry (proposed B8) — for any hypothesis family with shared selection axis, audit cohort overlap across periods before running individual hypothesis backtests.

## L10 — Train/Test sign divergence is the canonical death signature for axis instability (2026-05-24)

All 4 cycle 001 hypotheses showed Train/Test alpha signs disagreeing. Not coincidence; this is the diagnostic. A truly stable signal (positive or negative) maintains direction OOS, with magnitude possibly attenuated. A sign FLIP means the signal didn't generalize.

Reading the audit literature pre-engine, this pattern was already present — `strategies_lowvol.py` 2026-04-27 had Train +1.79 / Test -0.71 and was correctly rejected. We just hadn't elevated "Train/Test sign flip = axis instability" to engine-level pattern.

§6 kill criterion 2 already encodes "Train and Test alpha disagree in sign → REJECT". Lesson L10 reinforces it.

## L11 — Cube-identity selection is the wrong granularity for stable H5 (2026-05-24)

Cycle 002 tested H5 on the full 926-cube pool with point-in-time behavior features: trailing turnover, lag-vs-leader, attention-spike rate, and concentration intensity. This removed the Cycle 001 "smart cube" skill/snapshot contamination.

The result still failed B8 before any alpha backtest: composite cube-behavior axis median rotation `54.4%/Q`; turnover-only fallback `43.7%/Q`. That means the cube cohort itself changes too quickly for a strategy whose first step is "select suspect cubes" to generalize.

This does **not** kill Xueqiu behavioral data. It kills cube-identity selection as the primary axis. The next reformulation should be stock-level: identify stocks receiving abnormal pressure from high-turnover / late-entry / attention-chasing cubes, then B8-audit the stock cohort and compare against board + size + liquidity + momentum + industry matched controls.

---

(future cycles append here)
