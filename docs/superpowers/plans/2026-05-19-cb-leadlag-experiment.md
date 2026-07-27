# Convertible Bond Lead-Lag Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether convertible-bond market signals lead next-week returns of the underlying A-share stocks.

**Architecture:** Build one locked, falsifiable MVP experiment around 20-trading-day conversion-premium compression. Keep data loading, panel construction, factor calculation, metrics, and reporting separate enough to test without network access.

**Tech Stack:** Python, pandas, numpy, pytest, optional akshare/tushare for data backfill and inventory (report missing data-source deps, do not fail hard), existing `research/factors_v2` output conventions.

---

Research rationale for the repository owner: `docs/cb_leadlag_alpha_research_report.md`.

## Context

The current checkout does not contain enough data to run the experiment. `.gitignore` excludes `data/`, `*.csv`, `*.db`, and `research/factors_v2/cache/`, so the missing data is likely local-only rather than intentionally absent from the research design.

Do not treat a current-survivor AkShare sample as a final alpha result. That version is only a smoke test. A strict result requires historical convertible-bond universe data, including redeemed and delisted bonds.

## Required Local Data

- [ ] `data/stock_data/*.csv`: underlying stock daily bars.
  Required columns or aliases: `date`/`日期`, `close_raw`/`收盘`, `close_adj`/`复权收盘`, preferably `amount`/`成交额`.
  Use raw close for conversion-premium calculation and adjusted close for stock returns.

- [ ] `data/cb/universe.csv`: historical convertible-bond universe.
  Required columns: `cb_code`, `cb_name`, `stock_code`, `stock_name`, `list_date`, `delist_date`, `maturity_date`.
  Recommended columns: `rating`, `issue_size`.

- [ ] `data/cb/daily/{cb_code}.csv`: convertible-bond daily bars.
  Required columns: `date`, `close`.
  Recommended columns: `amount`, `turnover`, `premium_rt`.

- [ ] `data/cb/conv_price/{cb_code}.csv`: point-in-time conversion-price history.
  Required columns: `effective_date`, `conversion_price`.
  Strict mode must fail if only the latest conversion price is available.

- [ ] `data/cb/events.csv`: forced-redemption and major clause events.
  Required columns: `cb_code`, `event_date`, `event_type`.
  Include at least `force_redeem`, `downward_revision`, `redeem_notice` when available.

- [ ] Optional but useful: `research/baseline_v1/data_delivery/industry_mapping_v2.csv` and `liquidity_daily_v1.csv` for diagnostics.

## Locked Experiment Spec

This is the pre-registered baseline. Do not grid search windows or horizons before this spec is reported.

- Signal date: weekly, last available trading day of each week.
- Universe at date `t`: CB listed on or before `t`, not delisted/redeemed by `t`, valid underlying stock price, valid CB close.
- Liquidity filter: CB average 20-day amount >= CNY 5 million when `amount` exists.
- Maturity filter: remaining maturity >= 0.5 years.
- Event filter for headline metric: exclude observations with forced-redemption notices in `[t-10, t]` only.
  A symmetric plus/minus 10 trading-day filter may be reported only as an event-clean diagnostic, not as the headline tradable result.
- Premium formula: `premium_rt = cb_close / ((100 / conversion_price_point_in_time) * stock_close_raw) - 1`.
  If vendor `premium_rt` exists, recompute it from raw fields and fail if the absolute difference is material.
- Primary factor: `factor = -(premium_rt[t] - premium_rt[t-20])`.
  Interpretation: conversion-premium compression receives a higher score.
- Forward return: adjusted underlying stock close from `t+1` to `t+6`.
  This avoids entering at the same close used to compute the signal.
- Weekly portfolio timing: signal at `t` close, enter at `t+1` close, exit at `t+6` close. The next weekly signal enters at the same close where the previous holding exits, so capital is not double-counted.
- Primary metric: weekly cross-sectional Spearman rank IC between `factor` and forward return.
- Portfolio metrics:
  - headline tradable metric: long-only top quintile versus equal-weight CB-linked stock universe, after stock round-trip cost;
  - diagnostic metric: top quintile minus bottom quintile, after cost, explicitly marked as paper-only because A-share single-stock shorting is constrained.
- Random control: each week, draw a same-universe random portfolio with the same size as the signal top quintile. Use a fixed seed and at least `n_random_repeats=1`. True alpha is `signal excess - random excess`.
- Quintile rule: drop weeks with universe size < 25; use equal-weight groups, deterministic rank tie-breaking, and `pd.qcut(..., labels=False, duplicates="drop")`.
- Cost assumption: start with 56 bp round-trip; report sensitivity at 20 bp and 100 bp.
- In-sample window: `2022-01-01` to `2025-06-30`.
- Holdout window: `2025-07-01` to latest available date. Run only once after code and spec are frozen.

## Pass / Fail Rules

- Strict pass requires all of:
  - In-sample mean rank IC >= 0.03.
  - In-sample IC t-stat >= 2.5.
  - In-sample after-cost long-only excess return > 0.
  - In-sample same-universe random-control mean IC < 0.005.
  - In-sample signal IC minus random-control IC > 2 x standard error.
  - In-sample after-cost signal excess > random-control excess.
  - Holdout IC keeps the same sign and is >= 0.015.
  - Holdout IC t-stat >= 1.5.
  - Holdout after-cost long-only excess return > 0.
  - Holdout after-cost signal excess > random-control excess.

- Strict fail if any of:
  - Current-survivor sample only.
  - Historical redeemed/delisted CBs are missing.
  - Forced-redemption events cannot be filtered.
  - Point-in-time conversion-price history is missing.
  - Raw and adjusted stock close are not distinguishable.
  - Same-universe random control is not run.
  - Random-control IC is comparable to the signal IC.
  - In-sample IC is below 0.02 or flips sign by year.
  - After-cost long-only excess return is negative.

- Smoke-test result can only say `continue` or `reject`.
  It cannot say `validated`.
  Suggested smoke threshold for `continue`: current-survivor mean IC >= 0.02 and t-stat >= 1.5.

## Implementation Tasks

### Task 1: Data Inventory

**Files:**
- Create: `research/factors_v2/output/cb_leadlag/data_inventory.md`

- [ ] Run dependency check with optional data-source reporting:

```powershell
python -c "import pandas, numpy; print('core deps ok')"
python -c "import importlib.util as u; print('akshare:', 'installed' if u.find_spec('akshare') else 'missing (optional)')"
python -c "import importlib.util as u; print('tushare:', 'installed' if u.find_spec('tushare') else 'missing (optional)')"
```

Treat missing `akshare` / `tushare` as inventory information, not a hard failure.

- [ ] Check local data files:

```powershell
Test-Path data/stock_data
Test-Path data/cb/universe.csv
Test-Path data/cb/events.csv
Get-ChildItem data/cb/daily -Filter *.csv | Measure-Object
```

- [ ] Write `data_inventory.md` with:
  - stock file count,
  - CB universe row count,
  - CB daily file count,
  - conversion-price history file count,
  - earliest/latest dates,
  - missing required columns,
  - `pip freeze` snapshot for data-vendor package versions,
  - whether the run is `strict` or `smoke_test`.

### Task 2: Core Module And Tests

**Files:**
- Create: `research/factors_v2/cb_leadlag_mvp.py`
- Create: `tests/research/test_cb_leadlag_mvp.py`

- [ ] Write tests first for:
  - premium compression factor uses only dates <= `t`,
  - forward stock return starts at `t+1`,
  - diagnostic event window exclusion can remove plus/minus 10 trading days,
  - headline event filter uses only events known by `t`,
  - premium formula uses raw stock close and point-in-time conversion price,
  - stock forward return uses adjusted close,
  - rank IC returns positive value on a tiny known sample,
  - long-only excess return and top-minus-bottom spread apply costs,
  - random control uses the same weekly universe and the same portfolio size,
  - weekly holding intervals do not double-count capital.

- [ ] Run and confirm tests fail before implementation:

```powershell
pytest tests/research/test_cb_leadlag_mvp.py -q
```

- [ ] Implement the smallest working module with pure pandas functions:
  - `load_cb_universe(path)`,
  - `load_events(path)`,
  - `load_conversion_price_history(path)`,
  - `build_panel(...)`,
  - `compute_factor(panel)`,
  - `compute_forward_returns(panel)`,
  - `rank_ic_by_date(panel)`,
  - `long_only_excess(panel, cost_bps)`,
  - `random_control(panel, cost_bps, seed)`,
  - `quintile_spread(panel, cost_bps)`.

- [ ] Re-run tests until they pass.

### Task 3: Strict Run

**Files:**
- Create output directory: `research/factors_v2/output/cb_leadlag/`
- Create output files:
  - `summary.csv`
  - `ic_by_week.csv`
  - `spread_by_week.csv`
  - `coverage_by_week.csv`
  - `report.md`

- [ ] Run in-sample only:

```powershell
python research/factors_v2/cb_leadlag_mvp.py `
  --mode strict `
  --start 2022-01-01 `
  --end 2025-06-30 `
  --cost-bps 56
```

- [ ] Confirm the script refuses strict mode if historical universe or event data is missing.

- [ ] Freeze code and config after the in-sample run. Do not tune the factor based on holdout.

- [ ] Write a freeze manifest:

```powershell
git rev-parse HEAD
python research/factors_v2/cb_leadlag_mvp.py --write-freeze-manifest
```

The manifest should include git commit, script hash, locked parameters, in-sample date range, and output timestamp.

- [ ] Run holdout once:

```powershell
python research/factors_v2/cb_leadlag_mvp.py `
  --mode strict `
  --start 2025-07-01 `
  --end latest `
  --cost-bps 56 `
  --frozen-spec
```

The script must refuse to overwrite an existing holdout result unless a reviewer explicitly deletes the prior output and documents why.

### Task 4: Report

**Files:**
- Create: `research/factors_v2/output/cb_leadlag/report.md`

- [ ] Include this exact decision table:

| Check | Threshold | Result | Pass |
| --- | ---: | ---: | --- |
| IS mean rank IC | >= 0.03 |  |  |
| IS IC t-stat | >= 2.5 |  |  |
| IS long-only excess after cost | > 0 |  |  |
| IS random-control mean IC | < 0.005 |  |  |
| IS signal IC minus random IC | > 2 x SE |  |  |
| IS signal excess minus random excess | > 0 |  |  |
| OOS mean rank IC | >= 0.015 |  |  |
| OOS IC t-stat | >= 1.5 |  |  |
| OOS long-only excess after cost | > 0 |  |  |
| OOS signal excess minus random excess | > 0 |  |  |

- [ ] Include per-year IC:

| Year | Mean IC | Weeks | Sign Flip | Long-Only Excess After Cost |
| ---: | ---: | ---: | --- | ---: |

- [ ] Include data-quality notes:
  - percent of observations excluded by forced-redemption filter,
  - average weekly universe size,
  - minimum weekly universe size,
  - number of CBs with missing stock mapping,
  - whether sample includes redeemed/delisted CBs.
  - number of rows dropped due to missing amount in strict mode.
  - top/bottom quintile industry exposure as a diagnostic.
  - random-control IC and random-control excess return.

- [ ] Include pre-registration notes:
  - state that 10/30/60-day windows, CB-return residuals, monthly horizon, reverse stock-to-CB lead-lag, and volatility divergence were not tested in this PR;
  - future variants must use only data after the current holdout end date or be opened as a separately pre-registered experiment.

- [ ] End with one of three labels only:
  - `VALIDATED_FOR_NEXT_STAGE`
  - `REJECTED`
  - `INSUFFICIENT_EVIDENCE`

## PR Checklist

- [ ] Do not commit raw local market data unless the repo owner explicitly wants it.
- [ ] Commit the experiment script, tests, and report outputs only.
- [ ] Include `data_inventory.md` so reviewers know whether this was strict or smoke-test.
- [ ] Include the exact command output for tests.
- [ ] Include a short PR summary with the final label and the reason.

## Out Of Scope / Next Iteration

- If CB -> stock lead-lag is `REJECTED`, the next pre-registered experiment should test reverse stock -> CB lead-lag using the same `t+1` to `t+6` horizon discipline.
- Do not run the reverse direction inside this PR. It is a separate hypothesis and needs its own freeze manifest.

## Do Not Do

- Do not try 10/20/30/60-day windows in the same PR.
- Do not switch from premium compression to CB-return residuals after seeing results.
- Do not evaluate holdout before the in-sample spec is frozen.
- Do not call a current-survivor AkShare sample “validated”.
- Do not compare only to HS300; report random/control or top-minus-bottom within the same CB-linked stock universe.
- Do not use latest conversion price to reconstruct historical premium.
- Do not filter out future forced-redemption notices in the headline tradable metric.
