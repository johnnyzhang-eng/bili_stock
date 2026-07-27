# Methodology Audit — A1 Smart Cube Avoidance (2026-05-23)

**Author**: Claude session. Codex audit in parallel session (separate file).
**Status**: DRAFT — awaiting Codex findings for RECONCILIATION section.
**Verdict on A1**: ⛔ **NOT methodology-valid** — three CRITICAL bugs in IC computation and forward-return construction. Verdict numbers (IC=-0.0164/t=-4.97, excess +13.91%/yr) must be re-derived under foundation framework after fixes.

---

## A. Foundation 自检 (Self-test)

**Status**: BLOCKED at `DataBundle.load()` — `data/fundamentals/panel_quarterly.csv` + `data/stock_data/*.csv` were missing at audit start (rebuild scripts now running in background, see PHASE_0_GATE_SYNC_2026-05-23.md).

**Plan**: Re-run `python research/foundation/self_test.py` once both data caches populate. Required: 7/7 PASS before any A1 reassessment.

**Severity**: BLOCKER (no audit possible without baseline framework health-check).
**Fix**: Wait on `fetch_fundamentals.py` + `update_stock_data.py` (in progress).

---

## B. A1 实现的 5 项硬审计

### B1. Smart cube filter — survivor selection on 2026 outcome (CRITICAL / INVALIDATES)
*Upgraded from MEDIUM after RECONCILIATION with Codex — see §D.*

**Finding**:
- `build_signal.py:47-53` filters `trader_profile.csv` with `annualized_gain_rate ∈ (25, 500]`, `followers_count ≥ 200`, `n_user_events ≥ 30`, `active_days ≥ 365`.
- `trader_profile.csv` `updated_at` = **2026-02-25** (single snapshot, no time series).
- Of 96 selected smart cubes:
  - **2** have `first_event ≤ 2018-01-01`
  - **58** have `first_event ≤ 2022-01-01`
  - **38** were created AFTER 2022-01-01 — their pre-2022 signal contribution is identically 0
- Therefore the per-week signal for early weeks (2015-2021) is built from ≤ 58 cubes that already passed the 2026 ann_gain test, i.e. selected for **persistent profitability through 2026**.

**Why this isn't strict look-ahead but is still bias**:
- No future return is read into a past signal value (raw contribution = 0 when cube wasn't yet active).
- But the *identity of which cubes get the "smart" label* is determined by their cumulative performance through 2026. Cubes that were prominent in 2018 but blew up by 2020 are excluded → their picks (which may have signaled differently) are dropped. This is **selection-on-outcome**, a backward bias.

**Quantification**: Magnitude requires reconstructing cubes' rolling 12-month ann_gain from `rebalancing_histories` NAV — not available in this audit window. Direction: smart label biased toward "stable winners" → if winning-style cubes share characteristics (e.g. avoid speculative microcaps), the avoidance signal is contaminated by that style, not pure consensus-avoidance alpha.

**Fix**: Build ex-ante rolling-12M skill weight per (cube, week). Use only events `created_at < signal_week` to compute that week's ann_gain. Drop cubes with < 12 months prior history at signal time.

**Block A1 verdict?**: YES — list identity itself uses 2026 information, so all per-week signals built from it are tainted.

---

### B2. Event backdating leak (CRITICAL / INVALIDATES)
*Upgraded from MINOR after RECONCILIATION with Codex — see §D. My original "alignment is correct" conclusion was wrong because I only checked the trading-time leak path and missed the timestamp-honesty defect.*

**Finding (Codex, accepted)**:
- `build_signal.py:99-108`: every event regardless of weekday is stamped to ISO `'%Y-W%W'` → backdated to Monday of the same week via `-1` strptime suffix.
- 26,855 smart-cube user events: mean offset from mapped Monday = 2.06 days, median = 2 days, **80.34% on Tuesday or later** (Codex's quantification).
- `rerun_with_full_data.py:75-79`: `fwd_ret(wk)` denominator = Friday-W close, numerator = Friday-(W+1) close.
- Trading-time leak path: Friday-W post-close events backdated to Monday-W are aligned with `fwd_ret(wk)` whose denominator is Friday-W close — event sees the entry price. Codex did not split out the Friday-post-close subset, but at 80% T-or-later this is a non-trivial slice.
- Methodology-honesty defect: a signal stamped "Monday W" that requires Tuesday-W info to construct is mislabeled regardless of whether downstream return alignment leaks.

**Severity**: CRITICAL / INVALIDATES.
**Fix**: shift each weekly signal to the first tradable timestamp AFTER the latest event in the bucket (Codex), e.g. signal(wk+1) uses events with `created_at ≤ Friday(wk)`. Then `fwd_ret(wk+1) = Friday(wk+2)/Friday(wk+1)-1` is strictly future relative to signal construction.
**Block?**: YES.

---

### B3. Universe consistency — TWO bugs, one CRITICAL (CRITICAL, blocks)

#### B3-i. **CRITICAL: Mask bug at `build_signal.py:156`**

```python
mask = f_row.notna() & r_row.notna() & (f_row > 0)  # only stocks actually in signal
```

The comment claims "only stocks in signal", but `f_row` is taken from `signal_rank` (line 135: `signal_rank = signal_wide_ff.rank(axis=1, pct=True)`). After rank-pct, **every non-NaN cell has a strictly positive rank** (even ties from zeros average to a small positive pct). So `mask = (f_row > 0)` evaluates to `all-non-NaN`.

**Empirical confirmation**: replicated `mean IC = -0.0164, t = -4.97` exactly, with avg n_stocks per week = **3,277** (= near-full universe, not the ~30 in-pool stocks the comment implies).

**Implication**: The reported IC is NOT a cross-sectional rank-skill test among the 30 in-pool stocks. It is a **selection effect**: the ~30 stocks the smart cubes hold cluster at the top of the rank pct distribution (where their distinct non-zero raw contributions order them); the ~3,247 out-of-pool stocks are tied at the bottom of the rank pct. Spearmanr on this picks up *only* "do top-rank stocks (= held) have lower fwd_ret than the tied-bottom (= not-held) average". The same effect that `test_contrarian.py` reports as "avoid smart cubes +19.28%" — repackaged as IC.

**Severity**: CRITICAL. This re-frames the entire A1 thesis from "cross-sectional rank skill" to "binary held-vs-not-held average return delta". Two are not equivalent and require different controls (size/sector/liquidity must be controlled for *between* in-pool and out-pool subsamples, not just within-rank).

**Fix**:
1. Recompute IC using `mask = (raw_signal > 0)` (i.e. mask on `signal_wide_ff`, not `signal_rank`), so IC is the ~30-stock rank skill.
2. Separately compute the held-vs-not-held effect as a controlled Welch t-test with size/liquidity neutralization.
3. Both numbers should be reported; the current verdict conflates them.

**Block A1 verdict?**: YES.

#### B3-ii. **MEDIUM: Asset-class contamination in signal panel**

**Finding**: signal panel includes:
- 544 CB columns (可转债 `110/113/123/127/128`)
- 374 STAR columns (科创板 `688`)
- 361 "other" columns (likely 北交所 / B-shares / mis-formatted)
- Total 1,279 non-mainboard-A-share columns out of 4,063

`build_signal.py:106` only filters ETF prefixes (`510/511/512/513/515/516/518/588/159/160`); CBs are not excluded.

**Effect on IC**: 693 columns appear in signal but NOT in `fwd_ret_v2` (5,429 cols, all stock codes only). At line 146 `common_stocks = signal_rank.columns.intersection(fwd.columns)` silently drops them. But these columns *did* participate in the cross-sectional rank pct computation at line 135, so they shifted other stocks' rank values before being dropped. Magnitude of distortion is bounded but unaccounted.

**Empirical**: re-running IC after rebuilding `signal_rank` from a CB-removed signal panel changed mean IC negligibly (still -0.0022 in my stricter mask test). After **also** fixing the mask bug (B3-i), CB cleanup will matter more.

**Severity**: MEDIUM.
**Fix**: extend `build_signal.py:103-108` to skip CB/STAR/北交所 prefixes (Codex notes I missed `118` SH-CB prefix — adding `'110','113','118','123','127','128'`). Or constrain universe to `forward_returns_v2.csv` columns up front.
**Block?**: YES (combined with B3-i fix; rerun after both).

#### B3-iii. **MEDIUM: `no_smart_random` baseline not size/liquidity matched** (Codex finding, accepted)

**Finding**: `test_contrarian.py:55` defines `no_smart_random` = random pick from stocks where `f_row == 0` (no smart cube exposure). No explicit size, liquidity, or sector matching against in-pool. Smart cubes likely concentrate in mid/large-cap with higher liquidity; out-of-pool skews to micro-cap. The +19.28% out-pool CAGR partially reflects 2024-2026 small-cap beta, not avoidance alpha.

**Severity**: MEDIUM.
**Fix**: in foundation framework, use `Universe.broad/small_cap` with explicit `mcap_range` + `min_turnover_20d` applied to BOTH signal pool and random control. Foundation's `Backtest(random_control=True)` already does this when wired correctly.
**Block?**: Compounds with B3-i + B3-ii. Block until A1 rerun under foundation universe.

---

### B4. Random control rigor (MEDIUM, blocks)

**Finding**: `build_signal.py:186-212`:
```python
N_RANDOM = 30
rc_mean_ics = []
for run in range(N_RANDOM):
    shuf_vals = sig.values.copy()
    for i in range(shuf_vals.shape[0]):
        rng.shuffle(shuf_vals[i])
    # ... per-week spearman on shuffled signal ...
    rc_mean_ics.append(np.mean(rc_ics))

rc_mean = np.mean(rc_mean_ics)
rc_std  = np.std(rc_mean_ics)            # ← std ACROSS shuffles
delta_t = (mean_ic - rc_mean) / rc_std
```

The `rc_std` is std across 30 shuffle-runs of *per-shuffle mean IC*. Each shuffle averages over 229 weeks → per-shuffle mean IC has very low variance. `std(30 means)` ≪ `std(per-week IC)` → `delta_t` is mechanically inflated.

This violates `AUDIT_FINDINGS_2026_04_27.md` fix B2 explicitly:
> **B2** | `n_random_repeats=30` 抹掉 random 噪音, 抬高 t-stat | 所有历史 t-stat 偏大 [...] | 默认 `n_random_repeats=1`, alpha 自带 random 噪音

**Severity**: MEDIUM.
**Fix**: Use `Backtest(strategy=A1, random_control=True, n_random_repeats=1, seed=42)`. For robustness check, repeat with 5 distinct seeds and take median t-stat (per AUDIT_FINDINGS recipe).
**Block?**: YES — t=-4.97 cannot be trusted until re-derived.

---

### B5. Survivorship — CRITICAL fwd_ret construction bug (CRITICAL, blocks)

#### B5-i. **CRITICAL: Delisted stocks fwd_ret = 0, not NaN**

`rerun_with_full_data.py:77-79`:
```python
for wk in weeks:
    wk_end = wk + pd.Timedelta(days=6)
    close_at_week_end = df.loc[:wk_end, 'close'].iloc[-1] if (df.index <= wk_end).any() else np.nan
```

If a stock has its last `daily_k` row on 2018-12-25 (delisted), every week from 2019-01-01 onward returns the 2018-12-25 close (since `(df.index <= wk_end).any()` is still True). Then `fwd_ret = close[wk+1] / close[wk] - 1 = same/same - 1 = 0`.

**Effect**: Delisted stocks have `fwd_ret = 0` for all post-delisting weeks instead of `NaN`. They get included in:
- random control baselines (artificially anchoring mean to 0 in their delisted period)
- universe means
- `no_smart_random` (test_contrarian.py:55) pool (these are mostly out-of-pool, so this baseline is depressed by zeros that shouldn't be there)

**Empirical**:
- `fwd_ret_v2.csv` shape 546×5429, **430 columns have 0 real datapoints**, **486 columns have <20 datapoints**, **0 columns have last_date < 2024-01-01** (because the bug silently fills forward to 2026).
- Real A-share delistings 2015-2024 ≈ 150. The 27 codes that exist in `daily_k_pre2022/` but not `daily_k/` (true delisting candidates from local OHLCV cache) have actual last_dates 2018-2021. In `fwd_ret_v2.csv` they have `last_date = 2026-05-18`.

**Severity**: CRITICAL.
**Fix**: rewrite `rerun_with_full_data.py:77-79` to emit NaN when the latest close is older than `wk_end - 7 days` (or similar staleness threshold). Then rebuild `forward_returns_v2.csv` from scratch.
**Block A1 verdict?**: YES.

#### B5-ii. **MEDIUM: Delisted universe under-coverage**

**Finding**:
- `daily_k/` has 5,001 csv (2022-2025), `daily_k_pre2022/` has 4,250 csv (2014-2021).
- Only-in-pre2022 = 27 codes (real delisting candidates from local cache).
- Real 2015-2024 A-share delistings ≈ 150 (per `AUDIT_FINDINGS_2026_04_27.md`).
- 18% coverage of true delisted universe → systematic alpha inflation of 1-3%/year (per foundation audit).

**Severity**: MEDIUM (this is the standard project-level survivorship bias, not new).
**Fix**: long-term — backfill historical delisted OHLCV from baostock 历史接口 if available. Short-term — apply 1-3%/yr discount to all alpha numbers per foundation convention.
**Block?**: No, but mandates discount when reporting.

---

## C. 数据层一致性

### C1. `STOCK_DIR = data/stock_data/` was empty at audit start

**Finding**:
- `research/foundation/data.py:25` hardcodes `STOCK_DIR = data/stock_data/`.
- At audit start: `data/stock_data/` existed but had **0 files**.
- Actual OHLCV was in `research/attention_orj/cache/daily_k/` (5,001) + `daily_k_pre2022/` (4,250).
- `.gitignore` already excludes `data/stock_data/` (was never tracked in git).
- `update_stock_data.py` writes to `data/stock_data/` in the 12-col Chinese-header format `foundation/data.py` already supports.

**Decision (with Codex agreement Q1/Q2/Q3 in PHASE_0_GATE_SYNC)**:
- Path A: full rebuild via `update_stock_data.py` (baostock, cubes.db subset ≈ 1,041 missing).
- Patched `update_stock_data.py:22` `TARGET_END = "2026-05-23"`.
- daily_k merge fast-path REJECTED because daily_k lacks `turn` column → `universe.py:133` would skip all stocks → empty universe → broken backtest.

**Severity**: BLOCKER (resolved via rebuild now running).
**Fix**: in progress (background tasks `bkw497xxk` + `b6huos8n0`).
**Block?**: YES — Phase 0 cannot complete until rebuild + self_test pass.

### C2. `panel_quarterly.csv` missing

**Finding**: `data/fundamentals/panel_quarterly.csv` not on disk; entire `data/fundamentals/` directory missing. `.gitignore` excludes; never committed. A1 itself does not need fundamentals, but `DataBundle.load()` requires it, and `Backtest()` runs the full audit including panel-coverage check.

**Severity**: BLOCKER.
**Fix**: `research/factors_v2/fetch_fundamentals.py` running in background (akshare yjbb_em ~45 quarters).
**Block?**: YES until rebuild completes.

---

## D. 与 Codex 的交叉验证 — RECONCILIATION

Codex audit at `research/foundation/METHODOLOGY_AUDIT_2026-05-23_codex.md`, independent session (he explicitly stated he did NOT read this file before writing his). True cross-check.

### Headline outcome

**Two independent audits, four CRITICAL bugs found, zero overlap of CRITICAL findings**:

| Bug | Claude | Codex | First surfaced by |
|---|---|---|---|
| B1 — smart cube survivor selection | MEDIUM | CRITICAL/INVALIDATES | Both (different severity) |
| B2 — event backdating leak | MINOR (I was wrong) | CRITICAL/INVALIDATES | Codex only |
| B3-i — rank-pct mask bug | CRITICAL/INVALIDATES | not surfaced | **Claude only** |
| B5-i — fwd_ret=0 for delisted | CRITICAL/INVALIDATES | not surfaced | **Claude only** |

This is the system working as designed. Neither auditor could replace the other.

### Item-by-item reconciliation

#### B1 — I accept Codex's CRITICAL upgrade

My original reasoning: "since raw=0 for cube weeks before its `first_event`, no per-cell future-data leakage occurs". I was framing this as a strict data-leakage check.

**Codex's correct framing**: the very identity of the 96-cube smart list is determined by 2026 snapshot `annualized_gain_rate`. A cube that blew up by 2020 is excluded; one that survived through 2026 with `ann_gain > 25%` is included. The list is selection-on-2026-outcome. That is forward information, regardless of whether per-cell signal raw values are zero pre-`first_event`.

Codex's quantification (25/96 `created_at > 2022-01-01`, 38/96 `first_event > 2022-01-01`, 7/96 `created_at > 2024-01-01`, 1 `created_at > 2025-01-01`) makes the magnitude vivid. My number (38/96 `first_event > 2022-01-01`) matches his.

**Severity upgraded: B1 = CRITICAL / INVALIDATES**.

#### B2 — I accept Codex's CRITICAL finding; I was wrong

My original analysis concluded "alignment is correct" because `fwd_ret(wk) = Friday(wk+1) / Friday(wk) - 1` is a future-only window from any Tuesday-W event's perspective, so no trading-time look-ahead.

**Codex's correct framing**: even if there's no trading leak in the entry-price denominator, the timestamp is dishonest. Tuesday-W (or later) events backdated to Monday-W of the SAME week means the signal claims knowledge it didn't have at the stamp. With 80.34% of events at Tuesday or later (mean offset 2.06 days), this is not a corner case — it's the dominant pattern.

Furthermore, my own analysis missed a real leak path: **Friday-W post-close events backdated to Monday-W**, then aligned with `fwd_ret(wk)` whose denominator IS Friday-W close. Those events see the exact entry price they're being scored against. Codex did not quantify how many events are Friday post-close specifically, but at 80.34% T-or-later, a non-trivial subset are.

The fix Codex proposes — "shift each signal to the first tradable timestamp after the latest event" — is the right one. My MINOR rating was incorrect.

**Severity upgraded: B2 = CRITICAL / INVALIDATES**.

#### B3 — partial convergence + Claude additional finding

Codex flagged B3 contamination at MEDIUM with the same column counts I found (587 CB-like incl. `118` which I missed, 374 STAR, 693 signal-only). He also surfaced a related issue I did NOT explicitly call out: **`no_smart_random` in `test_contrarian.py:55` is not size/liquidity matched to the in-pool**. This is part of the "verdict +19.28% likely reflects size beta" caveat in the original verdict, but Codex correctly elevates it from caveat to methodology defect.

I add this as **B3-iii**: `no_smart_random` baseline not matched on size/liquidity. MEDIUM, consistent with Codex.

**B3-i (mask bug) was not surfaced by Codex.** I established it by exact replication of `verdict.IC = -0.0164 / t = -4.97` using the rank csv and confirming `avg n_stocks = 3,277` per week (not the ~30 in-pool the comment implies). Codex's audit did not include IC replication. The mask bug stands as my independent CRITICAL.

#### B4 — convergent, complementary framings

Both flagged the row-shuffle as inadequate. My framing emphasizes the AUDIT_FINDINGS B2 fix violation (`n_random_repeats=30` → cross-shuffle std underestimates per-week IC noise → t inflated). Codex's framing emphasizes the permutation destroys stock identity and cross-week persistence. Both are correct and address different aspects.

Combined fix: use `Backtest(random_control=True, n_random_repeats=1)` per AUDIT_FINDINGS, with seed-sensitivity check across 5 seeds.

**Severity stays MEDIUM (both agree)**.

#### B5 — partial convergence + Claude additional finding

Codex's B5 matches my B5-ii: 27 pre2022-only codes (24 ending before 2021-12-31, 3 exactly on 2021-12-31). Both auditors quantify the lower-bound nature.

**B5-i (fwd_ret=0 for delisted) was not surfaced by Codex.** I established it by reading `rerun_with_full_data.py:77-79` and confirming 430/5,429 columns in `forward_returns_v2.csv` have zero non-NaN datapoints (silently 0-filled rather than NaN). Codex's audit did not inspect fwd_ret column distribution. B5-i stands as my independent CRITICAL.

### What I'm changing in this document as a result

1. B1 severity upgraded MEDIUM → CRITICAL / INVALIDATES.
2. B2 severity upgraded MINOR → CRITICAL / INVALIDATES.
3. B3-iii added: `no_smart_random` not size/liq matched (MEDIUM, Codex).
4. Section E (current verdict) updated to reflect all 4 CRITICAL findings.

### What I am NOT silently merging

- Codex's Finding 1 (panel_quarterly missing) was already addressed jointly via PHASE_0_GATE_SYNC and is in progress.
- Codex's "deferred independent alpha hypothesis" — both auditors agree this only happens after Phase 0 PASS + bugs fixed + rerun. Nothing to merge here yet.

### Open questions for Codex

1. **Patch ordering**: with 4 CRITICAL bugs touching three files (`build_signal.py` mask + universe filter; `rerun_with_full_data.py` fwd_ret + cube selection wrapper), do we patch in one branch or sequence? Recommend single branch, sequenced commits per bug, so cross-effects can be measured.
2. **B1 fix design**: I proposed rolling-12M ann_gain from NAV rebuild. Codex says "freeze cube eligibility at each signal date, or rebuild the filter from a point-in-time snapshot that predates the backtest window". Both are valid; the rolling version is more rigorous but requires reconstructing cube NAV from rebalancing histories (~2-4 hours of code). The point-in-time snapshot approach (one snapshot per year, freeze for that year's signals) is simpler. Which does Codex prefer?
3. **B2 fix scope**: shift signals to first tradable day after latest in-week event. Should we also rebuild `forward_returns_v2.csv` to use proper next-day-after-signal entry rather than week-end close? Or is shifting signals enough?
4. **Joint patch review**: once patches are written but before re-running IC, do we want a third pass (Codex re-reads the diff)?

---

## E. Verdict on A1 (current)

A1 `verdict_2026-05-23.md` reports IC=-0.0164 / t=-4.97 / +13.91% excess.

**Four CRITICAL bugs invalidate the verdict** (joint Claude+Codex):
1. **B1** — smart cube list selected on 2026 outcome ann_gain (Codex CRITICAL, Claude accepts).
2. **B2** — event backdating: 80.34% events Tuesday-or-later stamped to same-week Monday + Friday-W post-close subset has real entry-price leak (Codex CRITICAL, Claude accepts).
3. **B3-i** — `build_signal.py:156` rank-pct mask = all-non-NaN, IC tests selection effect not rank skill (Claude CRITICAL, Codex did not surface).
4. **B5-i** — `rerun_with_full_data.py:77` 0-fills delisted fwd_ret instead of NaN, 430/5,429 cols (7.9%) silently 0 (Claude CRITICAL, Codex did not surface).

**Three MEDIUM defects compound the bias**:
5. B3-ii universe CB/STAR contamination (both auditors).
6. B3-iii `no_smart_random` not size/liq matched (Codex).
7. B4 random control N=30 t-inflation + permutation weakness (both, complementary framings).
8. B5-ii survivorship lower-bound — needs 1-3%/yr discount per foundation convention (both).

**Required to revisit A1 verdict**:
1. Phase 0 PASS (rebuild data, self_test 7/7).
2. Fix B5-i in `rerun_with_full_data.py`, rebuild `forward_returns_v2.csv`.
3. Fix B3-i + B3-ii in `build_signal.py`, rebuild signal panel.
4. Implement B1 ex-ante smart-cube selection.
5. Wrap A1 as `CrossSectionalStrategy` in foundation, run `Backtest(random_control=True, n_random_repeats=1, train_test_split=("2014-01-01","2021-12-31"))`.
6. Yearly sub-period IC across 2014-2025 (12 years).
7. Apply 1-3%/yr survivorship discount.
8. New verdict at `research/smart_consensus/verdict_2026-05-23_foundation.md`.

**Honest expected outcome after fixes**:
- Selection effect (held vs not-held after size/liq controls) probably survives, magnitude ~3-7%/yr (vs reported 14%).
- Cross-sectional rank skill (within in-pool 30 stocks) probably weak (|IC| < 0.02, |t| < 2) → A1 is a binary filter, not a ranking factor.
- Post-cost (~1.1%/rebalance × monthly = 13%/yr) post-discount (1-3%/yr) net alpha could be 0-3%/yr.

This is the expected pattern from the project's 8-round history (per `foundation/README.md` line 7): backtest looks great → audit deflates 70%.

---

**Last update**: Claude session, 2026-05-23. Codex finding integration pending.
