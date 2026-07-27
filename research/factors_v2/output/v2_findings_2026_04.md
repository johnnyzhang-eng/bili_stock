# v2 Factor Library — First Findings (2026-04)

## TL;DR

On the **correct universe** (3700 liquid A-share equities, not the 561
Xueqiu-active subset), the classic low-volatility factor is a clearly
stronger signal than the Xueqiu consensus factor.

| factor              | IC      | ICIR  | hit% | turnover/p | ann_cost | spread_ann | net_top_ann |
|---------------------|---------|-------|------|-----------:|---------:|-----------:|------------:|
| xueqiu (baseline)   | 0.0124  | 0.137 | 55.3 |      14.9% |    1.76% |      0.04% |      14.34% |
| low_volatility      | 0.0335  | 0.171 | 56.4 |      35.8% |    4.20% |     15.53% |       5.37% |

Period: 2015-01-01 → 2025-12-31. Panel: 2,910,469 rows, 3,700 stocks, 2,674 dates.

> **2026-04 update — survivorship-adjusted numbers.** After backfilling 232
> delisted names via baostock (see "Post-Backfill Numbers" below), the
> 19.9% paper net_top drops to **13.17%** and the best-overlay Calmar
> config drops to **14.90% CAGR / −57.2% MDD**. The 3-8pp haircut
> estimate landed at **~6pp on the core net number, plus ~15-19pp of
> worse MDD**. This is the realistic survivorship-adjusted baseline for
> everything below.

## Universe matters

Running low_vol on the Xueqiu-filtered panel (561 stocks) gave
`spread_ann = -8.38%` — an apparent negative factor. Moving to the
broad liquid A-share universe flipped it to `+15.53%`. Same factor,
same code, 24-point swing from universe alone.

Xueqiu subset is skewed toward momentum/attention-driven names
(Barber & Odean 2008). Low-vol anomaly cannot exist in a universe
pre-selected for retail attention.

## Xueqiu top-quintile looks great, isn't really alpha

Xueqiu factor shows `net_top_ann = 14.34%` — tempting. But:
- spread between top-quintile and bottom-quintile = 0.04% (zero).
- Bottom quintile of Xueqiu factor returns ~14% too.
- The 14% isn't *ranking* alpha; it's *universe* alpha — the set of
  Xueqiu-active stocks itself outperforms broad market.

Implication: if there's a monetizable signal in the cubes.db data,
it's "which stocks cubes follow at all", not "which stocks cubes
rank higher". This matches the structural reflection in
`docs/quant_strategy_lessons.md`.

## Low-vol turnover is suspiciously high

35.8% per 12-bday rebalance is much higher than the low-vol
literature would predict. Likely causes:
- 60-bday vol window is short enough that many stocks cluster near
  the top-quintile cutoff; tiny vol shifts flip ranks.
- Rebalancing every 12 bdays amplifies this cluster churn.

Cost-reduction levers for next iteration:
- Window: 60 → 120 bdays  (halves factor volatility)
- Hold step: 12 → 60 bdays (cuts periods/year from 21 to 4)
- Minimum-change threshold: only rebalance a stock if its rank
  percentile moves >10 points

Even a 50% turnover cut drops ann_cost from 4.20% → ~2.1%, pushing
net_top_ann toward 7.5% before factor improvements.

## Turnover Optimization Grid (2026-04)

Ran two experiments on low_vol to test whether the 35.8% per-period
turnover was fixable.

### 1. `(vol_window, hold_step)` grid

Nine combinations of window ∈ {60, 120, 250} × hold_step ∈ {12, 30, 60}.
Returns computed as true CAGR (product of per-period returns), which
drops the naively-compounded `(1+mean)^n` numbers by ~5pp for
high-volatility factors.

Best config: **window=60, hold_step=12** (the baseline).

Key finding: longer hold_step reduces annualized cost (4.21% → 1.39%
at hs=60), but kills top_ann faster than cost savings:

| config         | top_ann | ann_cost | **net_top** |
|---------------|--------:|--------:|----------:|
| w=60, hs=12   |  22.79% |  4.21%  | **18.59%** |
| w=60, hs=30   |  12.83% |  2.36%  |  10.47%    |
| w=60, hs=60   |  10.48% |  1.39%  |   9.09%    |
| w=120, hs=12  |  18.54% |  3.69%  |  14.86%    |
| w=250, hs=12  |  19.50% |  3.15%  |  16.35%    |

Low-vol alpha lives in short-horizon vol mean-reversion. Longer hold
trades it away. Window sweep similarly: longer windows smooth the
signal too much and lose contemporaneity.

### 2. Buffered rebalancing

Hysteresis: a stock enters at rank >= 0.80, leaves only below
`keep_q`. Same top-20% target, stickier holdings.

| keep_q         | turn/p | ann_cost | top_ann | **net_top** | Δ vs baseline |
|---------------|-------:|--------:|-------:|----------:|---------:|
| 0.80 (none)   |  35.8% |  4.22%  | 23.01% |  18.79%   | baseline |
| **0.70**      |  **27.2%** |  **3.20%**  | **23.05%** |  **19.86%** |  **+1.06pp** |
| 0.60          |  22.8% |  2.68%  | 21.55% |  18.87%   | +0.08pp  |
| 0.50          |  20.4% |  2.40%  | 21.38% |  18.98%   | +0.18pp  |

**Sweet spot: `keep_q=0.70`**. Turnover −24%, cost −1pp, top_ann
unchanged, +1.06pp net. Beyond 0.70 we keep stocks that have drifted
out of the quality zone — top_ann falls by roughly what cost saves.

### Production-candidate config (low_vol v1)

```
vol_window  = 60 bdays
hold_step   = 12 bdays
enter_q     = 0.80
keep_q      = 0.70  (buffered)
round_trip  = 56 bp (production cost model)
universe    = broad A-share equities, top 60% liquidity (20% in bull)
→  net_top_ann ≈ 19.9% (paper long-only, pre-realistic-execution)
```

### Caveats on the 19.9% number

This is a paper long-only top-quintile number. It does NOT yet include:
- Regime filter (bear-market drawdown control)
- T+1 lock impact beyond 56bp round-trip
- **Survivorship bias — confirmed severe (see below)**
- VWAP / open-execution slippage
- Dividend reinvestment consistency check

Production realistic haircut: expect 30-50% of paper alpha to survive,
landing at 10-14% net annualized — still far better than the Xueqiu
strategy's audited ~2%.

## Survivorship Bias Audit (2026-04)

`research/factors_v2/check_survivorship.py` last-date scan of all 3,721
A-share equity CSVs in `data/stock_data/`:

| last_date year | stocks |
|----------------|-------:|
| 2020           |      1 |
| 2021           |      1 |
| 2022           |      3 |
| 2023           |      1 |
| 2024           |      4 |
| 2025           |      4 |
| 2026           |  3,707 |

**99.6% of the universe is "still alive today".** Only 14 stocks have
a last-date before 2026. 2015-2025 saw hundreds of A-share delistings
(especially post-2020 with the stricter delisting rules) — essentially
none are represented.

Spot-check of 8 well-known delistings: **7 missing outright** (乐视网,
华锐风电, 退市海润, *ST富控, 退市长油, *ST长生, 信威集团). Only 康得新
is present, ending 2021-05-31 right before its 2021-07 delisting.

### Impact on the 19.9% (differential by quintile)

- **Top quintile (low-vol longs)**: small impact. Delisting names were
  almost all high-vol crashing stocks, which would have sat in the
  bottom quintile anyway.
- **Bottom quintile (high-vol)**: materially understated. The worst
  outcomes (→0) are excluded.
- **Spread (long-short)**: significantly inflated — would overstate
  a long-short backtest by a lot.
- **Long-only top (our 19.9%)**: directionally correct, but there is
  a **shadow bias**: some stocks looked low-vol *before* crashing and
  would have been picked up by the top quintile. Their post-inclusion
  crash returns are missing.

Rough estimate for long-only: **3-8pp of the 19.9% is survivorship
air**. Not fatal for a long-only strategy, but the residual net alpha
is ≈ **12-17%** before other haircuts, not 19.9%.

Next step to close this: pull a delisted-ticker list from
AKShare (`stock_info_sh_delist` / `stock_info_sz_delist`) or Tushare,
backfill missing CSVs, and re-run. Deferred — requires external data.

## Regime-Stratified Analysis (2026-04)

Question: where in the 222-period sample does the 19.9% net alpha
actually live? Buffered config (w=60, hs=12, enter=0.80, keep=0.70),
gross returns, regime = HS300 20-day return bucket at rebalance date.

### By HS300 regime (at rebalance date)

| Regime | Periods | Mean/period | CAGR-if-always | log-return share |
|--------|--------:|------------:|---------------:|-----------------:|
| 上涨   |      72 |       0.83% |         14.57% |           21.3%  |
| 震荡   |      99 |       1.23% |         24.84% |           47.7%  |
| 下跌   |      51 |       1.52% |         32.34% |           31.0%  |

**Counterintuitive finding**: only 21.3% of cumulative log-return is
earned in 上涨 regimes. **Low-vol makes most of its money in sideways
and declining markets** — the classic defensive-premium anomaly (Ang
2006): when HS300 is already down 3%+ over 20 days, quality/low-vol
names get flight-to-quality bid, then ride the rebound.

Implication for production: **no need to scale down in 下跌 regimes**
— the factor works best there. The regime to worry about is 上涨.

### By calendar year (gross annual return)

| Year | Dominant regime | Annual ret | log_share |
|-----:|:---------------:|-----------:|----------:|
| 2015 | 上涨            |   **+51.3%** |    18.9% |
| 2016 | 上涨            |     +33.9% |    13.3% |
| 2017 | 震荡            |     +11.7% |     5.1% |
| **2018** | **下跌**    | **-26.9%** |  **-14.3%** |
| 2019 | 震荡            |   **+60.5%** |    21.6% |
| 2020 | 上涨            |     +29.3% |    11.7% |
| 2021 | 震荡            |   **+46.1%** |    17.3% |
| 2022 | 下跌            |      +4.7% |     2.1% |
| 2023 | 震荡            |      -4.9% |    -2.3% |
| 2024 | 震荡            |     +29.7% |    11.8% |
| 2025 | 上涨            |     +38.4% |    14.8% |

9 positive years, 2 negative. Four big winners (2015, 2019, 2021, 2025)
account for 72.6% of cumulative log-return — **but they are 2 上涨 +
2 震荡 years, not a pure bull-market concentration**.

### 2018 is the elephant

**-26.9% in a single year.** Low-vol is a factor, not a hedge:
broad bear market selloffs drag quality names down too (just less
than the junk names, which is what shows up as the factor premium).

Per-period CAGR-if-always numbers (32% in 下跌) hide this: within
any given 12-day bear-regime window the factor rebounds, but stringing
21 bear periods together in 2018 compounded to -27%.

### Implications for production sizing

| Layer                                | Paper   | Realistic   |
|--------------------------------------|--------:|------------:|
| Top-quintile gross (CAGR)            | 23.05%  |             |
| − trading cost (buffered, 56bp)      |  3.20%  |             |
| = paper long-only net                | 19.85%  |             |
| − survivorship haircut (3-8pp)       |         |   11.9-16.9% |
| − max-drawdown overlay needed for 2018-type years? |         |     ?       |

The 19.9% number is correct given the data, but the data has two
known holes: survivorship (fixable via delisting list) and factor
timing (not fixable — needs a market-regime overlay on top of the
factor to protect the -27% tail).

**Recommended production wrap** (superseded by 2026-04 overlay test — see below):
1. Low-vol (buffered) as core stock selector
2. ~~HS300 20-day momentum overlay~~ — see overlay test: only extreme
   tail (<-10% 20d) helps; mid-range thresholds COST alpha
3. Survivorship backfill via AKShare delisting list as prerequisite
   for any real deployment

## Overlay Test (2026-04): Can a Market Filter Save 2018?

Tested two overlay families on the buffered config:

**Short-horizon (HS300 20-day return)** — grid of threshold × scale_off:

| Overlay                 | CAGR_n | MDD     | Calmar | 2018    | 2022   |
|-------------------------|-------:|--------:|-------:|--------:|-------:|
| Baseline (no overlay)   | 19.16% | -43.88% |  0.44  | -28.97% | +2.23% |
| 20d < -3%  → 0.00       | 10.62% | -39.50% |  0.27  | -36.34% | -15.25% |
| 20d < -5%  → 0.50       | 17.60% | -37.75% |  0.47  | -29.56% |  -1.51% |
| **20d < -10% → 0.00**   |**20.35%**|**-38.03%**|**0.54**| -28.84% |  +2.23% |

**Long-horizon (trend filters)** — tested to attack the 2018 grinding bear:

| Overlay                   | CAGR_n | MDD     | Calmar | 2018    | t_off |
|---------------------------|-------:|--------:|-------:|--------:|------:|
| 60d < -10% → 0.00         | 13.73% | -59.78% |  0.23  | -34.29% | 11.7% |
| close < SMA120 → 0.00     |  8.08% | -39.13% |  0.21  | -10.88% | 45.0% |
| close < SMA120 → 0.50     | 13.93% | -38.99% |  0.36  | -20.12% | 45.0% |
| close < SMA200 → 0.50     | 13.94% | -40.65% |  0.34  | -20.59% | 44.1% |

### Why trend filters fail

The factor's own regime analysis (above) showed **31% of cumulative
log-return is earned during 下跌 regimes**. Trend filters that shut
off the book during trend-down market periods cut the factor from
its main source of alpha.

- SMA-200 breach is ON 44% of the sample — killing half the alpha
- 60-day return < -10% misses the V-shape rebounds that the factor
  specifically captures

**Only the extreme tail works**: HS300 20-day return < -10% (triggers
only 3.6% of the sample — ~2008/2015-crash/2020-covid style events).
Those periods are when the factor's defensive premium fails (liquidity
crisis → indiscriminate selling).

### Best achievable overlay

**Production overlay: `HS300_ret20 < -10% → scale_to_0.00`**

- CAGR_net: 19.16% → 20.35% (+1.19pp)
- MDD:      -43.88% → -38.03% (+5.85pp)
- Calmar:    0.44 → 0.54 (+23%)
- 2018:     -28.97% → -28.84% (unchanged — overlay doesn't fire)

The 2018 problem is **not overlay-solvable with market-trend signals**.
Fixing it requires a structural change (position-sizing by portfolio
vol, multi-factor hedging, or long-short pair construction — the last
is closed off for retail A-share). Deferred until after fundamentals
stack is built.

## Post-Backfill Numbers (2026-04, survivorship-adjusted)

Delisting backfill completed via baostock (AKShare/Eastmoney rate-
limited on first attempt). 51 new CSVs written from a target set of
243 A-share delistings in 2014-2026; 192 were already on disk. The
panel builder was patched with a `成交额`-from-CSV fallback because
the external `liquidity_daily_v1.csv` doesn't cover the backfilled
delisted names — without this patch the new CSVs would be silently
dropped by the liquidity filter (and the post-backfill panel would be
bit-identical to the pre-backfill one, which is how the first run
looked).

Panel: **3,118,699 rows, 3,932 stocks** (was 2,910,469 / 3,700).
`build_broad_panel.py` last-date scan: **248 stocks with last_date
before 2026** (was 14).

### Headline haircut

Buffered production config (w=60, hs=12, enter=0.80, keep=0.70, 56bp
round-trip), no overlay:

| metric       | pre-backfill | post-backfill | Δ      |
|--------------|-------------:|--------------:|-------:|
| CAGR_gross   | 23.05%       | 16.92%        | −6.13pp |
| CAGR_net     | **19.16%**   | **13.17%**    | **−5.99pp** |
| MDD          | −43.88%      | **−64.73%**   | **−20.85pp** |
| Calmar       | 0.44         | 0.20          | −0.24  |
| ann turnover cost | 3.20%   | 3.28%         | +0.08pp |

**The survivorship haircut landed at ~6pp on CAGR_net**, right at the
upper end of the 3-8pp pre-backfill estimate. More dramatic is the
**MDD blowing out by ~21pp** — the delisted names (many failed in
2018, 2022-2024) dragged the tail significantly.

### 2018 revealed

Annual gross returns changed substantially in broad-bear years:

| Year | pre-backfill | post-backfill | Δ      |
|-----:|-------------:|--------------:|-------:|
| 2015 | +51.3%       | +46.2%        | −5.1pp |
| 2016 | +33.9%       | +24.4%        | −9.5pp |
| 2017 | +11.7%       |  −4.3%        | −16.0pp |
| **2018** | **−26.9%** | **−38.8%** | **−11.9pp** |
| 2019 | +60.5%       | +56.9%        | −3.6pp |
| 2020 | +29.3%       | +25.1%        | −4.2pp |
| 2021 | +46.1%       | +42.6%        | −3.5pp |
| 2022 |  +4.7%       |  +3.8%        | −0.9pp |
| 2023 |  −4.9%       |  −5.9%        | −1.0pp |
| 2024 | +29.7%       | +29.5%        | −0.2pp |
| 2025 | +38.4%       | +38.2%        | −0.2pp |

2017 and 2018 took the biggest hits (−16pp, −12pp). Recent years are
nearly unchanged, which makes sense: the realistic delisting risk
mostly lives in the 2014-2022 window, after which the stricter
delisting rules had fully swept through.

### Best-achievable overlay (re-run)

| Config                        | CAGR_n | MDD     | Calmar | 2018    |
|-------------------------------|-------:|--------:|-------:|--------:|
| Baseline (no overlay)         | 13.17% | −64.73% |  0.20  | −40.69% |
| **HS300 20d < −7% → 0.00**    |**14.65%**|**−56.22%**|**0.26**|−38.51%|
| HS300 20d < −10% → 0.00       | 14.90% | −57.23% |  0.26  | −39.93% |

The winning overlay threshold shifted from `−10% → 0.00` (pre-backfill,
20.35%/−38.03%) to `−7% → 0.00` post-backfill. The tighter threshold
triggers more often (6.3% vs 3.6% of sample), which is now needed
because the actual drawdowns are deeper. Even so, 2018 only improves
from −40.69% to −38.51% — **2018 remains structurally unfixable by
market-trend overlay**, confirming the pre-backfill conclusion.

### Regime breakdown (post-backfill)

| Regime | Periods | Mean/period | CAGR-if-always | log-share |
|--------|--------:|------------:|---------------:|----------:|
| 上涨   |      72 |       0.66% |          9.4%  |    18.6% |
| 震荡   |      99 |       1.00% |         18.3%  |    47.9% |
| 下跌   |      51 |       1.26% |         25.6%  |    33.5% |

Defensive-premium story holds: 下跌 is still the highest-mean regime
and 下跌 + 震荡 still earns 81% of cumulative log-return. But all
three means compressed — the pre-backfill regime table was itself
biased upward, not just the CAGR.

### What the realistic number is now

| Layer                                | Paper   | Realistic     |
|--------------------------------------|--------:|--------------:|
| Top-quintile gross (CAGR)            | 16.92%  |               |
| − buffered trading cost              |  3.28%  |               |
| = long-only net, survivorship-adj    | 13.17%  |               |
| + best overlay (HS300 20d < −7%)     |         |    **14.65%** |
| − T+1/VWAP/open execution slippage   |         |   ~−1 to −2pp |
| = **realistic post-execution**       |         |   **12-14%**  |

The 12-14% realistic range is about where the pre-backfill "3-8pp
haircut" estimate projected (11.9-16.9%). Close to 2x the audited
Xueqiu strategy's ~2% net, but with a −57% MDD the risk-adjusted
story needs the overlay and eventually a multi-factor stack to be
deployable.

## Multi-Factor Stack Research (2026-04-20)

Tested three price-only factors as low_vol complements. Goal: reduce −57% MDD
by stacking orthogonal signals. All tests on survivorship-adjusted broad panel.

### Factors tested

| Factor | IC | ICIR | Corr(lv) | Standalone net | Stack result |
|--------|---:|-----:|--------:|---------------:|-------------:|
| MAX (−max_20d) | +0.038 | 0.281 | +0.592 | 7.19% / −69.8% | 12.40% / −64.1% |
| BAB (−beta_252d) | −0.015 | −0.109 | +0.194 | −0.70% / −89.2% | 7.98% / −79.8% |
| Reversal (−ret_5d) | +0.015 | 0.133 | **−0.012** | +0.77% / −85.6% | 11.83% / −69.2% |

### Conclusions

**No price-only factor stack improved on low_vol alone.**

- **MAX**: Strong IC/ICIR (0.038/0.281) but high correlation (+0.59) — stack is redundant.
- **BAB**: IC is NEGATIVE in A-shares. High-beta stocks outperform in the
  retail-dominated, bull-heavy 2015-2025 sample. BAB is a risk-adjusted
  (Sharpe) story in US markets; raw long-only BAB fails in A-shares.
- **Reversal**: Near-zero correlation (−0.012) is theoretically ideal, but
  74% per-period turnover makes it unprofitable. 56bp costs eat the +0.015 IC.

**Key structural insight**: The −64% MDD is systemic market risk (beta to broad
A-share market), not a stock-selection problem. Adding more long-only equity
factors cannot reduce it — they all crash together in 2018-type bear markets.

### Best production candidate (confirmed)

```
low_vol  vol_window=60, hold_step=12, enter_q=0.80, keep_q=0.70
+ overlay: HS300 20d < −7% → scale_to_0
→ CAGR_net 14.65% | MDD −56.22% | Calmar 0.26
```

This beats all stacks on every metric. The overlay (not factor stacking) is
the right tool for market-risk management in a long-only framework.

## Next groundwork

1. ~~**Survivorship check**~~ — done. Knocked ~6pp off 19.9%.
2. ~~**Regime-stratified analysis**~~ — done. Low-vol is NOT bull-
   year dependent; 2018-type broad bear is the production risk.
3. ~~**Bear-year overlay test**~~ — done. Only extreme 20d <-7%
   helps (updated from -10% post-backfill). Trend filters destroy alpha.
4. ~~**Delisting backfill**~~ — done via baostock. 232 additional
   stocks, 51 newly-fetched delistings. Haircut quantified above.
5. ~~**Multi-factor stack (price-only)**~~ — done. No improvement found.
   MDD is systemic, not selectable. Best config is low_vol + overlay.
6. ~~**Full QC**~~ — done. All three tests passed. See below.
7. **Fundamentals ingestion** (deferred) — earnings_yield, roe_stability,
   gross_profitability. Only worth pursuing after live paper-trade confirms
   signal. Requires AKShare or Tushare token.

## Production QC (2026-04-20) — ✓ PASSED

Production config: `low_vol (vol_window=60, hold_step=12, enter_q=0.80, keep_q=0.70) + HS300 20d < −7% → scale_to_0`

**Baseline**: CAGR_net +14.83%, MDD −55.41%, Calmar 0.268, overlay fires 6.3% of periods.

### Test 1 — Randomized start-date (offset 0..11): ✓ PASS
- 100% of 12 offsets have positive CAGR_net
- Calmar range [0.105, 0.274], CV=0.37 (stable threshold <0.40)
- Gradient: offset 0-3 Calmar ~0.24-0.27, offset 5-9 ~0.10-0.13. All positive.

### Test 2 — hold_step sensitivity (8, 10, 12, 14, 16, 18, 20): ✓ PASS
- Calmar range [0.196, 0.330], CV=0.15 (very stable)
- No cliff edges. Compare: Xueqiu strategy had CV>1.0 on same test.
- Note: hold_step=20 gives Calmar 0.330 / MDD −47.74% — not adopted because
  faster rebalancing (hs=12) gives better factor responsiveness in live use.

### Test 3 — Parameter grid (enter_q × keep_q, 3×3): ✓ PASS
- 9/9 cells have Calmar > 0.15
- Range 0.243–0.324. Production cell (★): 0.268.
- Observation: enter_q=0.85 consistently outperforms 0.80 (range 0.286–0.324).
  **Not adopting yet** — changing params after seeing QC results would be
  p-hacking. Flag for v2 pre-registered test.

### QC verdict: strategy is robust, ready for live paper-trade monitoring.

## Files

- `research/factors/factor_low_volatility.py` — factor builder
- `research/factors_v2/build_broad_panel.py` — broad-universe panel
- `research/factors_v2/run_v2_factor_ic.py` — initial IC comparison
- `research/factors_v2/run_low_vol_turnover_grid.py` — window × hold grid
- `research/factors_v2/run_low_vol_buffered.py` — buffered rebalance test
- `research/factors_v2/check_survivorship.py` — last-date distribution audit
- `research/factors_v2/run_low_vol_regime.py` — regime/year stratified analysis
- `research/factors_v2/run_low_vol_overlay.py` — short-horizon 20d overlay grid
- `research/factors_v2/run_low_vol_overlay_trend.py` — long-horizon trend-filter test
- `research/factors_v2/build_low_vol_cache.py` — one-off factor cache builder
- `research/factors_v2/cache/broad_panel_2015_2025_fwd10.pkl` — panel cache
- `research/factors_v2/cache/low_vol_w60.pkl` — low_vol factor cache
- `research/factors_v2/output/v2_factor_ic_comparison.csv`
- `research/factors_v2/output/low_vol_turnover_grid.csv`
- `research/factors_v2/output/low_vol_buffered.csv`
- `research/factors_v2/output/survivorship_meta.csv`
- `research/factors_v2/output/low_vol_regime_periods.csv`
- `research/factors_v2/output/low_vol_by_regime.csv`
- `research/factors_v2/output/low_vol_by_year.csv`
- `research/factors_v2/output/low_vol_overlay_grid.csv`
- `research/factors_v2/output/low_vol_overlay_trend.csv`
- `research/factors/factor_max.py` — MAX (lottery reversal) factor
- `research/factors/factor_bab.py` — BAB (betting against beta) factor
- `research/factors/factor_reversal.py` — short-term reversal factor
- `research/factors_v2/run_max_factor_ic.py` — MAX vs low_vol IC comparison
- `research/factors_v2/run_max_buffered.py` — MAX buffered rebalance test
- `research/factors_v2/run_lv_max_stack.py` — low_vol + MAX stack backtest
- `research/factors_v2/run_bab_factor_ic.py` — BAB IC + stack backtest
- `research/factors_v2/run_reversal_ic.py` — reversal IC + stack backtest
- `research/factors_v2/run_production_qc.py` — full production QC (3 tests)
- `research/factors_v2/output/max_factor_ic.csv`
- `research/factors_v2/output/max_buffered.csv`
- `research/factors_v2/output/lv_max_stack.csv`
- `research/factors_v2/output/bab_factor_ic.csv`
- `research/factors_v2/output/reversal_ic.csv`
- `research/factors_v2/output/production_qc.csv`

---

## 2026-04-21 Update — 三层栈 & 小盘宇宙 & 核心教训

### 实验 1: Layer 3 权重扫描 (基本面 + 情绪反向 + 低波)

全宇宙 A 股, HOLD=20, K=20, 2017-2026 (9.1 年):

| W_FUND/W_SENT/W_VOL | CAGR_net | MDD | Sharpe | Calmar | 换手 |
|---|---:|---:|---:|---:|---:|
| 1.0/0.0/0.0 (纯基本面) | +6.07% | -50.29% | 0.14 | 0.12 | 29% |
| 0.4/0.3/0.3 (默认) | +6.81% | -43.52% | 0.18 | 0.16 | 35% |
| **0.4/0.1/0.5** | **+8.39%** | **-37.82%** | **0.24** | **0.22** | 35% |
| 0.3/0.2/0.5 | +8.32% | -39.67% | 0.24 | 0.21 | 35% |
| 0.0/0.0/1.0 (纯低波) | +7.83% | -41.06% | 0.22 | 0.19 | 35% |
| 0.0/1.0/0.0 (纯情绪反向) | +6.70% | -50.62% | 0.16 | 0.13 | 46% |

**结论**: 低波权重 0.5 是最优区间，情绪反向贡献最小（0.1 够了），
基本面 0.4 作为硬门槛而非打分主力。最佳组合 CAGR_net = 8.4%，
仍**显著跑输** 红利低波 ETF 买入持有 (12.82%)。

### 实验 2: 小盘宇宙 (60x/00x/300x/688 剔除大盘前15%) 三层栈

相同权重 0.4/0.1/0.5, HOLD=20, K=20：

| 标的 | CAGR_net | MDD | Calmar |
|---|---:|---:|---:|
| **小盘 3 层** | **+1.69%** | -30.67% | 0.05 |
| 沪深 300 | +3.21% | -41.90% | 0.08 |
| 中证 1000 ETF | +2.53% | -46.28% | 0.05 |
| 创业板 ETF | +6.68% | -52.88% | 0.13 |
| **红利低波 ETF 512890** | **+12.82%** | -14.14% | **0.91** |

**结构性结论**: 小盘宇宙过滤让结果**恶化**（CAGR 从 8.4% → 1.7%）。
小盘股票流动性差 + 波动大 + 基本面门槛卡掉太多标的 → 可选池子变窄，
交易成本占比上升，年化成本 3.75% 吃掉大半粗收益 (4.81% → 1.69%)。
换手 53% 明显高于全宇宙 35%。

### 核心教训 (与 quant_structural_lessons 一致)

1. **多因子不如一只红利低波 ETF**。9 年跑下来，任何多因子组合（包括最优低波权重）
   的 CAGR_net 都跑不赢 512890 买入持有 (12.82%, -14.14% MDD, Calmar 0.91)。
2. **Alpha 的真正来源是"避免追热点"**。红利低波的 14% MDD 和 0.91 Calmar 不是
   因为因子多先进，而是因为行业分散 + 低估值 + 稳定分红 = 天然防守。
3. **交易成本是最大敌人**。56bp 往返 × 35% 换手 × 12.6 期/年 ≈ 年化 2.5%-3.75%，
   直接把 5% 原始 alpha 砍到 2%。
4. **研究方向应转向**: (a) 红利低波 + 择时 overlay 降 MDD; (b) 质量+低波选股（若非要选股）;
   (c) 红利低波/创业板 regime 轮动。**不要再堆因子数量**。

### 新文件

- `research/factors_v2/layer3_full_stack.py` — 基本面+情绪+低波三层栈
- `research/factors_v2/layer3_weight_sweep.py` — 权重扫描
- `research/factors_v2/smallcap_full_stack.py` — 小盘宇宙版本（已证伪）
- `research/factors_v2/fetch_small_cap_etfs.py` — CSI500/CSI1000/创业板 ETF 抓取
- `research/factors_v2/output/layer3_weight_sweep.csv`
- `research/factors_v2/output/layer3_periods.csv`
- `research/factors_v2/output/layer1_periods.csv`

---

## 2026-04-21 续篇 — ETF 组合 vs 选股: 结构性胜负已分

### 实验 3: 红利低波 择时 overlay (全部证伪)

基于 512890, 2019-01 → 2026-04 (7.3 年):

| Overlay | CAGR | MDD | Calmar |
|---|---:|---:|---:|
| Baseline 买入持有 | +12.74% | -16.53% | 0.77 |
| A: SMA60 趋势 | -6.65% | -50.84% | -0.13 |
| B: SMA60 滞回(-3%) | -1.02% | -33.63% | -0.03 |
| C: HS300 ret60>-5% | +0.98% | -26.60% | 0.04 |
| D: DD 熔断-8%/回 95% | -2.58% | -37.77% | -0.07 |
| E: SMA60 & HS300 趋势 | -7.95% | -55.60% | -0.14 |
| F: SMA120 趋势 | -3.68% | -38.32% | -0.10 |

**结论**: 红利低波本身是均值回归品种，趋势 overlay 被 whipsaw
砸得一塌糊涂。**单一资产择时 = 证伪**。

### 实验 4: DIV ↔ GEM regime 轮动 vs 固定混合

(2019-01 → 2026-04)

| 策略 | CAGR | MDD | Calmar | Sharpe |
|---|---:|---:|---:|---:|
| DIV 买入持有 | +12.74% | -16.53% | 0.77 | 0.63 |
| GEM 买入持有 | +16.29% | -56.58% | 0.29 | 0.47 |
| R1 HS300_ret60>5%→GEM | +9.75% | -29.34% | 0.33 | 0.31 |
| R2 HS300_ret60>0→GEM | +6.07% | -39.85% | 0.15 | 0.15 |
| R5 60d 动量赢家 | +8.67% | -41.15% | 0.21 | 0.25 |
| R6 120d 动量赢家 | +11.99% | -39.72% | 0.30 | 0.40 |
| **R9 固定 DIV70/GEM30** | **+14.67%** | **-17.18%** | **0.85** | **0.72** |
| R8 固定 DIV60/GEM40 | +15.17% | -20.71% | 0.73 | 0.71 |

**结论**: **固定 DIV70/GEM30 完爆所有动态轮动规则**。regime/动量
轮动每次切换吃 56bp，错过 rebound —— 损失远大于择时收益。

### 实验 5: 多 ETF 静态组合 grid search

扫描 DIV/HS300/GEM/CSI1K 58 个组合:

| 组合 | CAGR | MDD | Calmar | Sharpe |
|---|---:|---:|---:|---:|
| **DIV70/GEM30 月再平衡** | **+14.78%** | **-17.29%** | **0.85** | **0.73** |
| DIV80/GEM20 | +14.19% | -16.75% | 0.85 | 0.72 |
| DIV60/GEM40 | +15.28% | -20.75% | 0.74 | 0.71 |
| DIV50/GEM50 | +16.03% | -26.08% | 0.61 | 0.70 |

**加 HS300 或 CSI1K 无增益** — 二元 DIV/GEM 吃掉所有可捕捉的 alpha。

### 实验 6: Quality + LowVol Hybrid (证伪基本面门槛)

基本面硬门槛 → 主板内 60 日低波 Top K, 2019-2026:

| 配置 | CAGR_net | MDD | Calmar | 换手 |
|---|---:|---:|---:|---:|
| 无门槛 LV30 | +10.50% | -19.60% | 0.54 | 32% |
| 宽松 LV20 | +9.22% | -28.71% | 0.32 | 34% |
| 中等 LV30 | +11.97% | -43.54% | 0.27 | 30% |
| 严格 LV20 | +4.17% | -40.72% | 0.10 | 25% |

**反直觉结论**: 基本面门槛越严越差。低波因子本身已经隐含质量信号
（低波股现金流稳定），再加硬门槛只是把池子变窄 → concentration 上升
→ MDD 恶化。所有选股组合 **全部跑输** DIV70/GEM30。

### 实验 7: DIV70/GEM30 再平衡频率 / Target vol / DD brake

**再平衡频率** (DIV70/GEM30):

| 频率 | CAGR | MDD | Calmar |
|---|---:|---:|---:|
| 永不 | +13.88% | -19.00% | 0.73 |
| 年度 | +14.90% | -17.69% | 0.84 |
| **季度** | **+15.15%** | **-17.61%** | **0.86** |
| **月度** | **+15.09%** | **-17.35%** | **0.87** |
| 周度 | +14.76% | -17.18% | 0.86 |
| 日度 | +14.30% | -17.57% | 0.81 |

季度/月度并列最优, 日度因成本略差。**季度再平衡 = 最佳实操**
（少 75% 交易次数但性能等同月度）。

**Target vol (年化 6-12% 目标)**: 全部恶化 CAGR 到 5-10%。高波动期
往往是恐慌后的 rebound 期，缩仓错过反弹。**证伪**。

**DD brake (组合回撤 -5% ~ -15% 减半仓)**: 几乎全部恶化（CAGR 2-8%）。
减半仓后错过底部反弹。**证伪**。

### 最终生产配置建议

```
持仓: 70% 红利低波 ETF (512890) + 30% 创业板 ETF (159915)
再平衡: 季度末恢复至 70/30
交易成本: 约 56bp × 每季度 0-5% 换手 ≈ 年化 0.4%
期望表现 (9 年回测 basis):
  CAGR_net: +15.15%
  MDD: -17.61%
  Calmar: 0.86
  Sharpe: 0.74
```

**总结 (4 条硬规则)**:
1. **不选股, 选 ETF 组合**。所有 factor 选股组合跑不赢简单 DIV/GEM 二元。
2. **不择时, 不轮动**。动态规则都被 whipsaw 毁掉。
3. **不 target vol, 不 DD brake**。主动降仓 = 错过 rebound。
4. **季度再平衡已足够**。日/周再平衡浪费交易成本, 月/年也可接受。

### 新文件

- `research/factors_v2/overlay_div_lowvol.py` — 实验 3 (证伪)
- `research/factors_v2/rotate_div_gem.py` — 实验 4 (固定胜轮动)
- `research/factors_v2/etf_portfolio_sweep.py` — 实验 5 (二元胜多元)
- `research/factors_v2/quality_lowvol_hybrid.py` — 实验 6 (门槛证伪)
- `research/factors_v2/portfolio_advanced.py` — 实验 7 (频率/TV/DD brake)
- `research/factors_v2/output/overlay_div_lowvol.csv`
- `research/factors_v2/output/rotate_div_gem.csv`
- `research/factors_v2/output/etf_portfolio_sweep.csv`
- `research/factors_v2/output/quality_lowvol_hybrid.csv`
- `research/factors_v2/output/portfolio_advanced.csv`

---

## 2026-04-21 下半场 — DCA 机制 & CB 双低起步

### 实验 8: DCA (定投) 机制对比

每月投入 ¥5000, 区间 2019-01 → 2026-04 (7.3 年):

| 策略 | IRR | MDD (相对平均成本) | 总回报 |
|---|---:|---:|---:|
| 月定投 DIV100 | +11.1% | -19.2% | +50.7% |
| 月定投 GEM100 | +14.1% | -61.0% | +68.4% |
| 月定投 DIV70/GEM30 | +12.0% | -24.5% | +56.0% |
| 月定投 DIV50/GEM50 | +12.6% | -33.1% | +59.6% |
| **月定投 DIV70/GEM30 + 季度再平衡** | **+13.4%** | -26.5% | +64.2% |
| 2周/周 定投 DIV70/GEM30 | +12.0% | -24.2% | ≈ |
| 月定投 + HS300 分位估值加权 | +12.9% | -31.3% | +55.8% |
| **月定投 + 估值加权 + 季度再平衡** | **+14.2%** | -33.0% | +63.5% |

**关键结论**:
1. **频率无影响** — 月/2周/周 定投 IRR 差别 ≤0.1pp (每月 5000 切成更细档没意义)
2. **季度再平衡贡献 +1.4pp IRR** (从 12.0% → 13.4%), 值得加
3. **估值加权 (HS300 3年分位: <30% 加倍, >70% 减半) 再 +0.8pp** (14.2%), 成本: MDD 略大因为低点加仓
4. **GEM 单独定投 IRR 最高 (14.1%) 但 MDD -61%** — 心理上极难坚持
5. **用户真实案例** (2018 起 bank+GEM, 7 年 +50%) 按 DCA 模型估算 IRR ~10-12%, 与 "月定投 DIV/GEM 混合" 吻合

### 实验 9: 可转债市场 2025-2026 状态 & 双低信号

**CB 等权指数近 1 年 (2025-04 → 2026-04)**:
- 累计 **+31.1%** / 年化 **+30.1%** (近年最强)
- 年化波动 14.1% / MDD -10.7%
- **当前温度: 92 (历史极热, 70 已算热, 85+ 严重过热)**
- 均价 163.6 元 (正常 110-130), 均双低 214.2 (正常 130-150)

**双低策略状态**: 当前市场 **严重过热, 双低标的几乎被买光**:
- 标准筛选 (价 95-130 + 溢价<30%) → **筛出 0 只** (已没有安全价位)
- 放宽到 (价 95-140 + 溢价<40%) → 勉强筛出 20 只, 但 Top 双低值已 124-148 (正常 90-110)

**操作建议**:
- **不在当前温度 (92) 大规模入场**
- 等 CB 指数温度回到 50-60 (历史冷区间) 再启动双低策略
- 现在只做小仓位跟踪 / 关注降温信号

### 新文件

- `research/factors_v2/dca_compare.py` — DCA 9 个组合对比 + IRR 计算
- `research/factors_v2/cb_dblow_signal.py` — CB 双低实盘信号 + 钉钉推送
- `research/factors_v2/output/dca_compare.csv`
- `research/factors_v2/output/live/cb_market_baseline.csv`
- `research/factors_v2/output/live/cb_dblow_picks_latest.csv`


---

## 2026-04-21 补充 — 长周期鲁棒性 (16 年回测)

**动机**: 之前 DIV70/GEM30 15.15% CAGR / 0.86 Calmar 的结论基于 2019-2026 窗口 (7.3 年), 起点正好在 2018 年熊市底部, 疑有选择偏差. 用新浪中证红利 (sh000922) + 创业板指 (sz399006) 拼接 ETF, 扩展到 2010-06 → 2026-04 (16 年).

**拼接方法** (`research/factors_v2/fetch_long_history.py`):
- 红利低波: `sh000922 中证红利` 2005-2019 + ETF 512890 (hfq) 2019+
  - ⚠️ 2010-2019 段为 **中证红利** (不含低波因子), 是逼近而非精确. 红利低波指数无公开长历史
- 创业板: `sz399006 创业板指` 2010-2011 + ETF 159915 2011+
- HS300: `sh000300` 全段

### 结果 — 长周期回测 (2010-06 → 2026-04, 16 年)

| 策略 | CAGR | MDD | Calmar | Sharpe | 换手 |
|---|---|---|---|---|---|
| HS300 (基准) | +3.52% | -46.7% | 0.08 | 0.18 | - |
| DIV100 不再平衡 | +8.08% | -46.5% | 0.17 | 0.40 | - |
| GEM100 不再平衡 | +8.82% | -69.6% | 0.13 | 0.37 | - |
| DIV70/GEM30 不再平衡 | +8.31% | -52.9% | 0.16 | 0.40 | 0 |
| DIV70/GEM30 月度再平衡 | +9.28% | -50.8% | 0.18 | 0.44 | 5.3 |
| **DIV70/GEM30 季度再平衡** | **+9.31%** | **-51.1%** | **0.18** | **0.44** | **3.0** |
| DIV70/GEM30 年度再平衡 | +9.48% | -51.1% | 0.19 | 0.45 | 1.8 |
| DIV60/GEM40 季度再平衡 | +9.52% | -54.1% | 0.18 | 0.44 | 3.4 |
| DIV50/GEM50 季度再平衡 | +9.63% | -56.9% | 0.17 | 0.43 | 3.6 |
| DIV80/GEM20 季度再平衡 | +9.00% | -48.0% | 0.19 | 0.43 | 2.3 |

### 🚨 对比真相 — 短窗口 vs 长窗口

| 指标 | 2019-2026 (7.3 年) | **2010-2026 (16 年)** |
|---|---|---|
| CAGR | 15.15% | **9.31%** (-5.8pp) |
| MDD | -17.3% | **-51.1%** (-34pp!) |
| Calmar | 0.86 | **0.18** |

**短窗口 15% CAGR 是牛市偏差** — 起点 2019 恰好在 2018 熊市底, 幸存者偏差严重. 16 年真实表现: **9.3% CAGR, -51% MDD, Calmar 0.18** 才是诚实答案.

### 分段 CAGR vs HS300 (2 年段)

| 区间 | DIV70/GEM30 | HS300 | 超额 |
|---|---|---|---|
| 2010-2011 | -10.55% | -9.45% | -1.10% |
| 2012-2013 | +9.68% | +0.68% | +9.00% |
| 2014-2015 | +40.84% (MDD -48%) | +26.86% | +13.98% |
| 2016-2017 | +0.62% | +7.85% | -7.23% |
| 2018-2019 | +0.44% | +0.11% | +0.33% |
| 2020-2021 | +20.69% | +9.10% | +11.60% |
| **2022-2023** (熊市) | **-3.03%** | **-16.61%** | **+13.57%** |
| 2024-2025 | +21.63% | +16.97% | +4.66% |
| 2026 YTD | +17.29% | +2.96% | +14.33% |

**2015 股灾 DIV70/GEM30 和 HS300 一起跳崖** — 两个都是权益资产, 无债券缓冲. 但 **2022-2023 熊市大胜 +13.57%**, 体现红利低波的防御价值.

### 3 年滚动鲁棒性 (3098 个窗口)

指标 | DIV70/GEM30 | HS300
---|---|---
平均 3Y CAGR | +10.17% | +3.38%
中位 3Y CAGR | +9.15% | +4.74%
最坏 3Y CAGR | -16.36% | -14.65%
最好 3Y CAGR | +44.10% | +25.60%
平均 MDD | -29.9% | -35.7%
最坏 MDD | -48.4% | -46.7%
**3Y CAGR > 0 窗口占比** | **84.7%** | 63.8%
**3Y CAGR > HS300 胜率** | **79.0%** | -

**稳健但非全天候**:
- 79% 窗口跑赢 HS300
- 85% 窗口 3 年不亏钱
- 平均 MDD 比 HS300 低 6pp
- 但最坏 MDD -48% 与 HS300 -47% 基本相等 (2015 股灾期间两个一起挂)
- 要做到真正 all-weather, 必须加入债券/现金/黄金等负相关资产

### 新文件

- `research/factors_v2/fetch_long_history.py` — 拼接长历史序列
- `research/factors_v2/long_backtest.py` — 16 年长周期回测
- `research/factors_v2/rolling_robustness.py` — 3 年滚动鲁棒性
- `research/factors_v2/output/long_history.csv` — 拼接后日序列
- `research/factors_v2/output/long_backtest.csv` — 策略汇总
- `research/factors_v2/output/long_backtest_segments.csv` — 两年分段
- `research/factors_v2/output/rolling_3y.csv` + `rolling_3y.png` — 滚动窗口

### 🔑 修订后的结论

之前: "DIV70/GEM30 季度再平衡 CAGR 15%, Calmar 0.86, 跑赢所有选股"
现在: "DIV70/GEM30 季度再平衡 **16 年 CAGR 9.3%**, **MDD -51%**, Calmar 0.18, 胜率 79% 但 2015 股灾一起跳崖. **跑赢 HS300 5.8pp/年**, **不能取代债券配置**"

下一步方向: (C) 加债券/现金仓位做 all-weather / 风险平价; (D) 研究 GEM 的动量/趋势过滤 (GEM 单边 MDD -70% 太吓人)

---

## 2026-04-21 补充 — 全天候组合 (加债 + 加金)

**动机**: DIV70/GEM30 16 年 MDD -51% (2015 股灾一起跳崖), 需要加负相关资产做 all-weather.

### 数据扩充

- 债: `sh000012` 上证国债指数 (Sina, 2003-2026, 23 年)
- 金: `AU0` 沪金主力连续 (Sina, 2008-2026, 18 年)
- 拼接: `research/factors_v2/fetch_bond_gold.py` → `long_history_4asset.csv`

### 各资产 16 年单独 B&H (2010-06 → 2026-04)

| 资产 | CAGR | 波动 | MDD |
|---|---|---|---|
| DIV (红利低波) | 8.08% | 20.8% | -46.5% |
| GEM (创业板) | 8.82% | 32.9% | -69.6% |
| HS300 | 3.52% | 21.5% | -46.7% |
| BOND (上证国债) | 3.81% | **0.7%** | **-1.0%** |
| **GOLD (沪金)** | **8.99%** | 16.1% | -44.8% |

🚨 **意外**: 黄金 CAGR 居然最高 8.99%, 和股票弱相关, 是关键防守资产.

### ABC 方案回测 (16 年, 季度再平衡)

| 方案 | CAGR | 波动 | MDD | Calmar | Sharpe | 2015 股灾 | 2022-23 熊 | 2020 疫情 |
|---|---|---|---|---|---|---|---|---|
| E 基准 DIV70/GEM30 | 9.31% | 21.9% | -51.1% | 0.18 | 0.44 | -48.4% | -13.6% | -14.4% |
| A 60/40 股债 | 7.54% | 13.1% | -32.4% | 0.23 | 0.49 | -32.4% | -7.6% | -8.4% |
| **B 40/40/20 股债金** | **7.62%** | **9.5%** | **-23.7%** | **0.32** | **0.64** | **-23.7%** | **-4.9%** | **-7.1%** |
| C 风险平价 (60日波动) | 4.64% | 2.0% | -7.5% | 0.62 | 1.35 | **+2.3%** | **+8.2%** | **+0.9%** |
| D 25/25/50 股金债 | 6.98% | 7.0% | -15.9% | 0.44 | 0.75 | -15.9% | -2.9% | -5.5% |

### 股/债/金 比例 sweep → 最优 30/30/40

| 股 | 债 | 金 | CAGR | MDD | Calmar | Sharpe |
|---|---|---|---|---|---|---|
| **30% | 30% | 40%** | **+8.13%** | **-19.4%** | **0.42** | 0.69 |
| 40% | 20% | 40% | +8.75% | -24.7% | 0.35 | 0.66 |
| 40% | 30% | 30% | +8.19% | -24.2% | 0.34 | 0.65 |
| 30% | 40% | 30% | +7.58% | -18.9% | 0.40 | 0.71 |
| 50% | 20% | 30% | +8.77% | -29.1% | 0.30 | 0.61 |

胜出: **30% 股 (DIV/GEM 7:3) / 30% 债 / 40% 金, 季度再平衡**
- CAGR 8.13% (仅比 DIV70/GEM30 低 1.2pp)
- **MDD -19.4%** (比 -51% 少 31pp)
- **Calmar 0.42** (vs 基准 0.18, 2.3 倍)
- Sharpe 0.69

黄金 SMA200 overlay 测试: 加了 overlay 后 CAGR 8.13→7.87%, Calmar 0.42→0.45 — **边际改善但不值复杂度, 不加**.

### 3 年滚动鲁棒性 (3098 个窗口)

| 指标 | AW 30/30/40 | DIV70/GEM30 | HS300 |
|---|---|---|---|
| 平均 CAGR | 7.01% | 10.17% | 3.38% |
| 最坏 CAGR | **-3.86%** | -16.36% | -14.65% |
| 最好 CAGR | 22.32% | 44.10% | 25.60% |
| 平均 MDD | **-11.7%** | -29.9% | -35.7% |
| 最坏 MDD | **-19.4%** | -48.4% | -46.7% |
| **3 年不亏率** | **90.6%** | 84.7% | 63.8% |
| 跑赢 HS300 | 61.9% | 79.0% | - |
| 跑赢 DIV70/GEM30 | 48.5% | - | - |

**核心价值**: AW 最坏 3 年只亏 3.86%, 几乎"永不大亏". 放弃部分 CAGR (换取 3 年不亏率 90.6%, 比 DIV70/GEM30 的 84.7% 更稳, 比 HS300 的 63.8% 高 27pp).

### 关键洞察 — "天气"不是择时而是配置

1. **4 种宏观天气 (成长×通胀)** 都有对应的赢家资产: 股票 / 长债 / 商品-金 / 短债-金
2. **不预测天气, 固定比例 + 再平衡** 就能让不同资产轮流顶上
3. **2015 股灾 / 2022-23 熊市 / 2020 疫情** 三次压力测试, AW 组合都把损失压到个位数
4. **黄金是 A 股投资者的"隐藏神器"** — 16 年 CAGR 最高 8.99%, 且和股票弱相关, 但很少人配
5. **再平衡 = 被动择时**: 股涨卖股买金, 股跌卖金买股, 自动低买高卖

### 新文件

- `research/factors_v2/fetch_bond_gold.py` — 拉债/金长历史 + 拼接
- `research/factors_v2/all_weather_abc.py` — ABC 方案回测 + 应激测试
- `research/factors_v2/all_weather_sweep.py` — 股债金比例 sweep
- `research/factors_v2/all_weather_rolling.py` — 3 年滚动鲁棒性
- `output/long_history_4asset.csv` — 5 资产日序列
- `output/all_weather_abc.csv`, `all_weather_sweep.csv`, `all_weather_rolling_3y.csv`
- `output/all_weather_rolling_3y.png`, `all_weather_nav_compare.png`

### 🔑 修订后的生产策略

之前: "DIV70/GEM30 季度, CAGR 15.15% / Calmar 0.86" (短窗口偏差)
16 年修正: "DIV70/GEM30 季度, CAGR 9.31% / MDD -51% / Calmar 0.18" (诚实但吓人 MDD)
**新版全天候**: "30% 股 + 30% 债 + 40% 金, 季度再平衡, CAGR 8.13% / MDD -19.4% / Calmar 0.42 / 3 年不亏率 90.6%"

**适合人群**:
- 不能承受 -51% 的普通投资者 → 选 AW 30/30/40
- 年轻 / 长期视角 / 能承受 -51% → 选 DIV70/GEM30 换更高 CAGR
- 极端保守 → 选 C 风险平价 (MDD -7.5%, Sharpe 1.35, 但 CAGR 只有 4.6%)

下一步: (F) 做成 AW 30/30/40 实盘触发信号脚本 (仿照 ETF rebalance signal); (G) 研究动量 tilt 是否能提升 CAGR 同时保持 Calmar
