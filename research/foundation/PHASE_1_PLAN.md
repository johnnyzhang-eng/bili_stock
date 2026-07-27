# Phase 1 Plan — A1 Foundation Rerun + Verdict

**Author**: Claude (Opus 4.7) 2026-05-24
**Status**: DRAFT v0 — requires Codex sign-off + Johnny sign-off BEFORE /goal launch
**Stopping condition for `/goal until ...`**: items §6 all checked

---

## 1. Objective

Decide whether A1 ("avoid smart cubes") is **VALIDATED / REJECTED / INCONCLUSIVE** under `research/foundation/` framework, with all 4 CRITICAL bugs already fixed in patch branch.

We are NOT trying to make A1 work. We are testing whether, after rigorous methodology, A1 has any after-cost, after-survivorship, size/liq-controlled alpha.

---

## 2. Decision criteria (locked before run)

| Criterion | VALIDATE | REJECT | else INCONCLUSIVE |
|---|---|---|---|
| `Backtest.full_summary["t_stat"]` | > +2 | < +1 | mid |
| `Backtest.train_summary["t_stat"]` and test t_stat | both > +1, same sign | one ≤ 0 | mid |
| `alpha_mean` (per-period gross) | > 0.5% | < 0% | mid |
| After 1-3%/yr survivorship discount + size/liq match | net alpha > 1%/yr | net alpha < 0 | mid |
| Random control delta sign matches verdict thesis (avoid smart) | yes | no | mid |

Hard reject (override): any criterion fires REJECT → REJECT regardless of others.

**Annualization formula (per Codex review)**:
- `annualized_alpha = alpha_mean × (252 / hold_days)`, NOT `× 52` weekly.
- Survivorship discount (1-3%/yr) is subtracted from the **annualized** number, not from per-period alpha.
- **Anti-rooting clause**: if final annualized alpha > 10%/yr after fixes, that triggers **additional bug suspicion**, NOT automatic VALIDATE. The 8-round project history says 10%+ alpha post-audit is almost always still a hidden bug.

This is locked in `_sync/control.md` before launch so the model can't move goalposts.

---

## 3. Foundation-API mismatch fact-check (DONE)

I read `strategies.py` and `backtest.py`. Concrete facts:

- `CrossSectionalStrategy.factor_fn(row, price_cache, sig_date) -> float` — called once per (signal_date, stock).
- `Backtest._run_cross_sectional` iterates **quarterly** signal dates (Q_MONTH/Q_DAY hardcoded). `rebalance_freq: "Q"` in CrossSectionalStrategy is dataclass field but only "Q" path is implemented.
- `sig_date = data.get_signal_date(rpt_date)` ≈ quarter end + 45-130 days lag (REPORT_DELAY_DAYS).
- `hold_days` is the holding window (default 180). Foundation reports per-period gross/net + alpha vs random.
- `Universe.at(rpt_date, sig_date)` returns the investable universe for that quarter.
- `n_random_repeats=1` is default (B2 fix).

**Implication for A1**: foundation tests A1 at quarterly frequency. A1's original weekly verdict can NOT be reproduced one-to-one; we get a quarterly-rebalanced version of the contrarian thesis. Two paths:

- **Path A (recommended)**: accept quarterly. Pre-compute A1 signal panel once (using the patched build_signal.py), then `factor_fn` looks up the most recent in-pool stock signal as of `sig_date`. Lower turnover → lower cost drag → cleaner alpha-after-cost test.
- Path B (scope creep): extend `Backtest` to support monthly cycle. Not worth it for one strategy.

Path A. Locked.

---

## 4. Concrete deliverables

### 4.1 `research/foundation/strategies_a1.py` (new, ~80 lines, Claude writes)

Skeleton (executable, not pseudocode):

```python
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from research.foundation import DataBundle, Universe, CostModel, CrossSectionalStrategy, Backtest, StandardReport

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SIG_PATH = os.path.join(ROOT, "research", "smart_consensus", "output", "smart_consensus_ffill.csv")

_SIG_CACHE = {}

def _load_signal():
    if "df" not in _SIG_CACHE:
        df = pd.read_csv(SIG_PATH, index_col=0)
        df.index = pd.to_datetime(df.index)
        df = df[~df.index.duplicated(keep="first")].sort_index()
        _SIG_CACHE["df"] = df
    return _SIG_CACHE["df"]

def _stable_jitter(code: str, sig_date) -> float:
    """Deterministic jitter ∈ [0, 1) to break zero-exposure ties without bias.
    Hash(code, date) → float. Same input always returns same value (reproducible).
    """
    import hashlib
    key = f"{code}|{pd.Timestamp(sig_date).strftime('%Y-%m-%d')}".encode()
    h = int(hashlib.md5(key).hexdigest()[:12], 16)
    return (h % 10**9) / 10**9

def factor_a1_avoid(row, price_cache, sig_date):
    """A1 contrarian: HIGHER score = MORE avoid-able = LOWER smart_consensus exposure.
    Zero-exposure stocks get top score with deterministic jitter to avoid
    tie-order picking bias (Codex review fix).
    """
    sig = _load_signal()
    code = row["code"]
    if code not in sig.columns: return np.nan
    col = sig[code].loc[:sig_date]
    if col.empty: return np.nan
    s = float(col.iloc[-1])
    if s > 0:
        return -s  # exposed stocks: more exposure → lower score
    # zero-exposure stocks: top tier, jittered for tie-break determinism
    return 1.0 + _stable_jitter(code, sig_date) * 1e-6
```

**Codex review locked**: `+1.0 + jitter` is primary (matches "pick out-of-pool" verdict). `+0 + jitter` sensitivity run scheduled as secondary.

### 4.2 Driver script `research/foundation/run_a1_foundation.py` (new, ~50 lines, Claude writes)

```python
def main():
    data = DataBundle.load(verbose=False)
    uni = Universe.broad(data, mcap_range=(30, 500), min_turnover_20d=0.15)
    strat = CrossSectionalStrategy(
        name="A1 — avoid smart cubes (contrarian, rolling ex-ante skill)",
        factor_fn=factor_a1_avoid,
        top_pct=0.20, n_signal_cap=30,
        hold_days=63,  # one quarter (≈ foundation default 90 minus 30d buffer)
    )
    cost = CostModel.a_share_retail_quarterly()
    bt = Backtest(strategy=strat, universe=uni, cost_model=cost,
                  random_control=True,
                  train_test_split=("2021-12-31", "2022-01-01"),
                  year_start=2017, year_end=2026, seed=42)
    result = bt.run(verbose=True)
    StandardReport.from_result(result).print()
    # Apply 1-3%/yr survivorship discount to annualized alpha
    # (logged but not modified inline — analyst reads + decides)
```

### 4.3 Verdict `research/smart_consensus/verdict_2026-05-24_foundation.md`

Sections:
1. TL;DR (one line: VALIDATED | REJECTED | INCONCLUSIVE + headline number)
2. Decision matrix (§2 above + checked-or-not)
3. Foundation Backtest output (gross/net per-period, alpha mean, t-stat, train vs test)
4. Survivorship discount application (1-3%/yr off annualized)
5. Comparison to original verdict (verdict_2026-05-23.md retracted notice)
6. Open follow-ups

### 4.4 Retraction notice in `research/smart_consensus/verdict_2026-05-23.md`

Top-of-file banner block:
```
> ⚠️ RETRACTED 2026-05-24 — 4 CRITICAL methodology bugs found post-publication.
> See research/foundation/METHODOLOGY_AUDIT_2026-05-23.md +
> research/foundation/IC_DELTA_2026-05-23.md + verdict_2026-05-24_foundation.md.
> Numbers in this file (IC=-0.0164, t=-4.97, +13.91%/yr excess) are NOT to be cited.
```

### 4.5 PR #6 update (comment via `gh pr comment 6`)

One concise comment linking to METHODOLOGY_AUDIT + IC_DELTA + new verdict.

---

## 5. Division of labor (Claude + Codex)

| Task | Owner | Cross-check |
|---|---|---|
| 4.1 `strategies_a1.py` | Claude writes | Codex reviews diff before commit |
| 4.2 `run_a1_foundation.py` | Claude writes | Codex reviews |
| 4.3 verdict draft | **Codex writes** (he did ablation, has freshest numbers) | Claude reviews |
| 4.4 retraction banner | Claude (mechanical) | — |
| 4.5 PR #6 comment | Claude (mechanical) | Codex must read before posting |
| Size/liq match sensitivity (§2 criterion 4) | **Codex extends ablation.py** | Claude reviews |
| Run + log output | Whichever session is awake first | Other verifies |
| Disagreement on VALIDATE/REJECT call | Stop. `_sync/control.md STOP: <reason>` + wake Johnny | — |

---

## 6. /goal stopping condition (verbatim)

```
A1 Phase 1 complete: ALL of (1) research/foundation/strategies_a1.py exists and `git log --oneline | grep strategies_a1` shows a Claude commit;
(2) research/foundation/run_a1_foundation.py exists and was run successfully (log line "[+] 报告写入" present in commit comment);
(3) research/smart_consensus/verdict_2026-05-24_foundation.md exists with one of three TL;DR labels: VALIDATED / REJECTED / INCONCLUSIVE — must match decision matrix in PHASE_1_PLAN.md §2;
(4) research/smart_consensus/verdict_2026-05-23.md top-of-file banner contains "RETRACTED 2026-05-24";
(5) PR #6 has a comment posted by current branch's gh user containing the new verdict TL;DR;
(6) _sync/control.md phase = DONE AND last_update_by alternation between claude and codex appears in history.md (no single-author monologue).
```

---

## 7. Known risks + mitigations

| Risk | Mitigation |
|---|---|
| Quarterly rebalance changes A1's economic story | Disclosed in §3. Verdict file explains the deviation from weekly. |
| Universe.broad(mcap_range=(30,500)) excludes pure micro-caps that drove "+22pp test divergence" | Run a sensitivity with `Universe.broad(mcap_range=(5, 500))` once base run is done. Codex's ablation domain. |
| Cube event panel index mismatch with quarterly signal_date (panel has weekly Mondays, sig_date is +45-130 days after quarter end) | `factor_a1_avoid` uses `.loc[:sig_date].iloc[-1]` — most recent ≤ signal_date, robust to any cadence. |
| `panel_quarterly.csv` may have different column names than `Universe.broad` expects | Will surface in `DataBundle.load()`. If failure, log + ask Johnny. Don't hack. |
| /goal validator hangs (per v2.1.140 bug history) | Use `caffeinate -d` to prevent sleep. Hard timebox: any single iteration > 30 min triggers STOP. |
| Two sessions write same outbox file simultaneously | Git rebase + retry. Per PROTOCOL.md anti-thrash rules. |
| **Zero-exposure tie-order bias** (Codex new risk) | Without jitter, `sort_values()` on a huge cluster of `+1.0` zero-exposure stocks would tiebreak by code/universe order, embedding a hidden lexical bias. Mitigated by deterministic `_stable_jitter(code, sig_date) × 1e-6` added to the zero-exposure score. |

---

## 8. Mutual sanity check before /goal launch

This plan must pass BOTH:

### Claude self-check (already done before commit):
- [x] Read `research/foundation/strategies.py` — confirmed `factor_fn` signature
- [x] Read `research/foundation/backtest.py` — confirmed quarterly hardcoded
- [x] Read `research/foundation/strategies_lowvol.py` — confirmed working example pattern
- [x] Decision matrix has REJECT criteria, not just VALIDATE (no rooting for the strategy)
- [x] Stopping condition is verifiable by `gh / git / file existence`, not "agent says done"

### Codex review checkpoints (signed off in PLAN v1 with the following edits):
- [x] §4.1 zero-exposure: `+1.0 + stable_jitter × 1e-6` (Codex required); raw `+1.0` rejected as hidden tie-order bias.
- [x] §2 thresholds locked, with clarifications: annualization = `× (252/hold_days)`, survivorship discount applied to annualized number, **>10% annualized → MORE bug suspicion, NOT automatic VALIDATE**.
- [x] §3 quarterly Path A acceptable; verdict file must state "quarterly foundation variant", not imply it reproduces the weekly verdict.
- [x] §7 risk inventory: added zero-exposure tie-order risk.
- [x] §5 division of labor: no swap requested.

### Johnny final approval:
- [ ] Decision criteria (§2) match his expectations
- [ ] He understands quarterly ≠ weekly verdict
- [ ] He's OK with /goal running unattended

---

**Until all three checkpoints in §8 pass, do NOT launch `/goal`. Walk through the plan, push back, commit a v1 with changes.**

---

## 9. Phase 1++ — expanded scope (Johnny pushback "做量化这么怂的吗?")

A1 verdict alone is risk-management theatre. Real quant work is **multiple parallel hypotheses against the same foundation** to discover which slice of cubes data, if any, has genuine alpha. Three new hypothesis to run in **same `/goal` cycle**:

### H2 — Smart Cube Cluster-Buy Event (long, event-driven)
- **Thesis**: when ≥3 smart cubes simultaneously open new positions in the same stock within a 7-day window, that's consensus formation → outperform.
- **Detection** (`EventDrivenStrategy`):
  ```python
  def detect_cluster_buy(price_cache):
      # scan rebalancing_histories: for each event, find (stock, ts) with target_weight 0→>0
      # group by (stock, week); count distinct smart_cubes_at_bucket
      # return {stock_code: [event_idx_in_price_cache, ...]} where count ≥ 3
  ```
- **Entry/exit**: `next_open`, hold 5 trading days (matches B2 HORIZON_TRADING_DAYS).
- **Decision**: same §2 matrix, ALPHA sign expected POSITIVE.
- **Owner**: Codex (he wrote B2 entry-convention, knows event tooling).

### H3 — Smart Cube Mass-Exit Event (short / avoid, event-driven)
- **Thesis**: when ≥3 smart cubes simultaneously exit (target_weight → 0) within 7 days, insider info diffuses → underperform.
- **Detection**: symmetric to H2 but on weight>0→0 transitions.
- **Position**: A-share long-only → translate to **filter out** these stocks from broader portfolio. Foundation tests the "predicted-underperformer" cohort vs same-day random.
- **Decision**: alpha sign expected NEGATIVE for the predicted cohort.
- **Owner**: Claude.

### H4 — Skill-Weighted Buy-Intensity (cross-sectional)
- **Thesis**: in any quarter, stocks with high skill-weighted "fresh buy" activity from smart cubes outperform.
- **Factor**: `sum over smart cubes [skill_weight × max(0, target_weight - prev_weight_adjusted) in past 30 trading days]`. Normalize cross-sectionally.
- **Entry**: standard quarterly cross-sectional.
- **Decision**: positive correlation thesis. If A1's "smart cubes avoid alpha" was a mask bug, H4's "smart cubes buy alpha" might be the real direction.
- **Owner**: Claude.

### Common scaffolding (shared work)
- **Cube event extraction module** (`research/smart_consensus/cube_events.py`): one builder that produces both cluster_buy and mass_exit event lists per (stock, date). Claude writes once.
- **Smart cube membership at event time**: reuse `rolling_ann_gain.csv` — at each event, check whether the originating cube was "smart at that bucket" per existing definition. Skip events from non-smart cubes.

### Updated deliverables (replaces §4 § for the multi-hypothesis run)
- `strategies_a1.py` ← Claude (already specced in §4.1)
- `strategies_h2_cluster_buy.py` ← Codex
- `strategies_h3_mass_exit.py` ← Claude
- `strategies_h4_buy_intensity.py` ← Claude
- `cube_events.py` (shared event extractor) ← Claude
- `run_all_hypotheses.py` (runs A1+H2+H3+H4 sequentially, generates 4 verdicts) ← Codex
- `verdict_2026-05-24_foundation.md` (combined verdict) ← Codex
- `retraction banner on verdict_2026-05-23.md` ← Claude
- `gh pr comment 6` ← Claude

### Expanded stopping condition (replaces §6)
```
Phase 1++ complete: ALL of (a) self_test 7/7 PASS;
(b) 4 strategy files exist + each ran successfully in foundation.Backtest;
(c) verdict_2026-05-24_foundation.md contains 4 TL;DR lines, one per hypothesis,
   each labeled VALIDATED|REJECTED|INCONCLUSIVE per §2 matrix;
(d) verdict_2026-05-23.md has RETRACTED banner;
(e) PR #6 comment with combined verdict TL;DR posted;
(f) _sync/control.md phase = DONE AND history.md shows both authors contributing.
```

### Honest probability estimates (Claude, 2026-05-24)

| Hypothesis | Pr(VALIDATE) | Reasoning |
|---|---|---|
| A1 (avoid smart, weekly→quarterly) | **~15-25%** | mask-bug-driven IC framing dead; binary delta survives but ~50% odds it's size beta. Quarterly cycle smooths timing, so cost drag less. |
| H2 (cluster_buy long) | **~25%** | consensus formation effect is a real phenomenon in some markets, but A-share retail-driven attention can also mean exhaustion at buy point. Could go either way. |
| H3 (mass_exit avoid) | **~25-35%** | smart-money exit signal is a classic informed-trading thesis. If any of the 4 wins, this is the most plausible. |
| H4 (buy intensity quarterly) | **~10%** | momentum proxy without size control likely captures same small-cap beta. |
| **At least one VALIDATE** | **~50-60%** | parallel testing is the right shape of bet given uncertain priors. |

If all 4 REJECT, the conclusion is: **cubes data as-collected does not produce alpha under rigorous methodology**, and we should pivot to another data source for the next cycle. That's a valid and valuable result.
