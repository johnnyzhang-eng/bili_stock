# Methodology Audit — 2026-05-23 (Codex)

Scope: independent audit of the foundation gate and A1 methodology.

## Finding 1: Foundation self-test is blocked by a missing required panel file
**Severity**: CRITICAL  
**Evidence**:
- `python3 research/foundation/self_test.py` could not run because `numpy` was absent in the system interpreter.
- `uv run --with numpy --with pandas --with scipy python research/foundation/self_test.py` then failed at `DataBundle.load()` with:
  - `FileNotFoundError: /Users/johnnyzhang/jz_code/bili_stock/data/fundamentals/panel_quarterly.csv`
- `research/foundation/data.py:24-25` hardcodes `PANEL = .../data/fundamentals/panel_quarterly.csv`.
- The workspace `data/` tree contains `cubes.db`, `market_cache/`, `stock_data/`, and `strategy_data.db`, but no `data/fundamentals/` directory or `panel_quarterly.csv`.

**Impact on A1 verdict**: INVALIDATES / STOP  
**Suggested fix**: restore the required `data/fundamentals/panel_quarterly.csv` asset, or update the canonical data-loading contract so `DataBundle.load()` points at the real panel source before any strategy audit.  
**Confidence**: HIGH

## STOP
The foundation gate did not pass, so I did not evaluate items 2-7 or the A1 signal itself.

## Static findings B1-B5

## Finding 2 (B1): Smart-cube selection uses a 2026 snapshot to score a 2022+ backtest universe
**Severity**: CRITICAL  
**Evidence**:
- `research/trader_profile/build_profile.py:37-42, 67-73, 118-125, 147-175` builds `trader_profile.csv` from full `cubes.db` metadata plus the full rebalance history, then writes `annualized_gain_rate`, `followers_count`, `n_user_events`, `active_days`, `first_event`, `last_event`.
- `research/smart_consensus/build_signal.py:42-58` filters smart cubes from that snapshot using current `annualized_gain_rate`, `followers_count`, `n_user_events`, and `active_days`.
- `data/cubes.db` snapshot for the selected smart cubes is current as of `updated_at = 2026-02-25` for all 96 rows.
- Quantified look-ahead: among the 96 smart cubes, 25 were created after `2022-01-01`, 38 had first_event after `2022-01-01`, 7 were created after `2024-01-01`, and 1 after `2025-01-01`.

**Impact on A1 verdict**: INVALIDATES  
**Suggested fix**: freeze cube eligibility at each signal date, or rebuild the filter from a point-in-time snapshot that predates the backtest window.  
**Confidence**: HIGH

## Finding 3 (B2): Weekly signal timestamps are backdated relative to the events that create them
**Severity**: CRITICAL  
**Evidence**:
- `research/smart_consensus/build_signal.py:85-108` maps each `created_at` to `strftime('%Y-W%W')` and then converts that to the Monday of the same week.
- The event lag is material: 26,855 smart-cube user events, mean offset from mapped Monday is 2.06 days, median 2 days, and 80.34% of events occur on Tuesday or later.
- `research/cube_attention_delta/rerun_with_full_data.py:55-90` builds `forward_returns_v2.csv` from Monday-anchored weeks using week-end closes and `shift(-1)`, so the same Monday label is used for a return that starts at the end of that week.

**Impact on A1 verdict**: INVALIDATES  
**Suggested fix**: shift each signal to the first tradable timestamp after the latest event inside the bucket, or rebuild the return horizon from the exact event time.  
**Confidence**: HIGH

## Finding 4 (B3): Signal and return universes are not filtered the same way, and the random controls are not size/liquidity matched
**Severity**: MEDIUM  
**Evidence**:
- `research/smart_consensus/build_signal.py:103-108` removes ETF-like prefixes `510/511/512/513/515/516/518/588/159/160`, but it does not remove CB prefixes `110/113/118/123/127/128`.
- Actual column counts: `smart_consensus_ffill.csv` has 4,063 columns, `forward_returns_v2.csv` has 5,429, intersection is 3,370, with 693 signal-only and 2,059 forward-only columns.
- Prefix counts show the mismatch clearly: signal has 587 CB-like codes and 374 STAR codes; forward returns have 0 CB-like codes and 538 STAR codes; intersection keeps 374 STAR codes and 0 CB-like codes.
- `research/smart_consensus/test_contrarian.py:35-60, 108-129` defines `no_smart_random` as the complement of the in-pool set, with no explicit liquidity or size matching.

**Impact on A1 verdict**: WEAKENS  
**Suggested fix**: define one investable universe with explicit board / liquidity / size filters and apply it identically to both the signal matrix and the random control.  
**Confidence**: HIGH

## Finding 5 (B4): The permutation random control is weaker than the foundation random-control contract
**Severity**: MEDIUM  
**Evidence**:
- `research/cube_attention_delta/rerun_with_full_data.py:185-223` randomizes by shuffling each weekly row 30 times; that preserves the row marginal distribution but destroys stock identity and any cross-week persistence.
- `research/foundation/backtest.py:212-227` uses a stricter random control: same universe, signal picks removed from the pool, explicit `random_control=True`, and the same hold mechanics.

**Impact on A1 verdict**: WEAKENS  
**Suggested fix**: use the foundation random-control path for the final verdict, and treat row-shuffle IC as an auxiliary permutation sanity check only.  
**Confidence**: HIGH

## Finding 6 (B5): Survivorship evidence remains a lower-bound correction, not a complete fix
**Severity**: MEDIUM  
**Evidence**:
- Survivorship facts: `data/cubes.db` spans `created_at` 2014-10-20 to 2026-02-25; the pre-2022 cache has 4,250 files, the 2022+ cache has 5,001, and only 27 codes exist only in the pre-2022 cache.
- Of those 27 legacy-only codes, 24 end before `2021-12-31` and 3 end exactly on `2021-12-31`. This is a lower bound on missing delisted history, not a complete correction.

**Impact on A1 verdict**: WEAKENS  
**Suggested fix**: restore point-in-time delisted coverage before trusting any positive excess return; subtracting only the known 1-3%/yr survivorship estimate leaves A1 at roughly 11-13%/yr, but B1/B2 are larger invalidators.  
**Confidence**: HIGH

## Independent alpha hypothesis
Deferred until the foundation gate passes and the universe / alignment issues above are repaired.
