# `research/foundation/` — Audit-enforced backtest framework

The only path for new A-share strategies in this repo. Refuses to run without random control, OOS split, benchmark match, and cost model.

## Why this exists

The Bili_Stock project went through 8 rounds of "backtest looked great → audit found it was 0–2% net". Each round produced a new bug or a new structural bias. This package codifies the rules that survived, so future strategies cannot accidentally re-introduce them.

See [`AUDIT_FINDINGS_2026_04_27.md`](AUDIT_FINDINGS_2026_04_27.md) for the complete bug history (B1–B4 + defensive guards).

## Hard rails enforced

1. **`DataBundle.load()`** runs a data audit and raises `DataAuditFailure` if OHLCV coverage < 30% or pct-change consistency < 85%.
2. **`Backtest()`** requires explicit `random_control: bool` — raises `MissingRandomControl` if omitted.
3. **`Benchmark.auto_for(universe)`** matches benchmark to universe size tier — raises `BenchmarkMismatch` on size/index mismatch (no more HS300 vs small-cap).
4. **`train_test_split`** is required for OOS verification.
5. **`CostModel`** is required (no zero-cost defaults).

## Quick start

```python
from research.foundation import (
    DataBundle, Universe, CostModel,
    CrossSectionalStrategy, EventDrivenStrategy,
    Backtest, StandardReport,
)

# 1. Cross-sectional factor (long top quintile, hold 6 months)
data = DataBundle.load()
uni  = Universe.broad(data, mcap_range=(30, 500))
strat = CrossSectionalStrategy(
    name="my_factor",
    factor_fn=my_fn,                    # (panel_df, signal_date) -> dict[code, score]
    top_pct=0.20, hold_days=180,
)
bt = Backtest(strategy=strat, universe=uni,
              cost_model=CostModel.a_share_retail_quarterly(),
              random_control=True,
              train_test_split=("2018-12-31", "2019-01-01"),
              n_random_repeats=1)
result = bt.run()
StandardReport.from_result(result).print()

# 2. Event-driven (limit-up / earnings / news)
strat = EventDrivenStrategy(
    name="first_board",
    detect_fn=my_detect,                # (price_cache) -> dict[code, list[idx]]
    entry_at="next_open", exit_at="next_close", hold_days=1,
)
# ...same Backtest call, framework auto-builds same-stock random-day baseline
```

## Self-test

After any framework change, run:

```bash
python research/foundation/self_test.py
```

7 segments must pass:

| # | Test | Pass criterion |
|---|---|---|
| A1 | NULL factor (constant 0) cross-sectional | \|alpha\| < 1%, \|t\| < 2 |
| A2 | RANDOM factor cross-sectional | \|alpha\| < 1%, \|t\| < 2 |
| A3 | High-turnover factor (negative direction) | `t < −2` (known A-share inverse) |
| A4 | Look-ahead "factor" (cheats with future returns) | `α > 10%`, `t > 4` (sanity that engine *can* find real signal) |
| B1 | EventDriven NULL (random-day events, 18,972 events) | \|alpha\| < 0.1%, \|t\| < 2 |
| C1 | Cost consistency (gross − cost = net) | exact equality across all rows |
| C2 | Train/test split strictness | no train date ≥ split, no test date < split |

## Modules

| File | Responsibility |
|---|---|
| `data.py` | `DataBundle.load()` — auto-audit, panel + price_cache + AuditResult |
| `universe.py` | `Universe.broad/large_cap/small_cap` with explicit `mcap_range`, `min_turnover_20d` |
| `benchmark.py` | `Benchmark.auto_for(universe)` — size-matched index, raises on mismatch |
| `costs.py` | `CostModel.a_share_retail_quarterly/intraday/swing/etf` — 4 realistic presets |
| `strategies.py` | `CrossSectionalStrategy`, `EventDrivenStrategy` base classes |
| `backtest.py` | `Backtest()` engine — enforces hard rails, runs random control, splits Train/Test |
| `report.py` | `StandardReport` — Markdown-renderable backtest summary |
| `self_test.py` | 7-segment health check |

## Strategies validated (or falsified) with this framework

All in `research/foundation/strategies_*.py`:

| Strategy | Verdict | Report |
|---|---|---|
| `strategies_lowvol.py` | ⛔ OOS reversal: Train Calmar +1.79 → Test −0.71 | `factors_v2/output/low_vol_foundation_validation.md` |
| `strategies_first_to_second_board.py` (H1, H1b, H3) | ⚠️ +1.87% alpha is overnight gap (limits to arbitrage) | `factors_v2/output/first_board_research_summary.md` |
| `strategies_first_board_executable.py` (H8 V1/V2/V3) | ⛔ All 3 retail-executable variants negative alpha | `factors_v2/output/first_board_executable.md` |
| `strategies_h9_textbook_rules.py` (H9 A/B/C/D/ALL) | ⛔ All 5 textbook rules reverse-direction at daily frequency | `factors_v2/output/h9_textbook_rules.md` |

## Known limitations

- **Survivorship bias**: panel `last_rpt < 2024-06` includes only 6 stocks (data source queries by current active universe). Real A-share 2015-2024 delistings ≈ 150. **Alpha is systematically overstated by 1-3%/year.**
- **ST history erased**: `name` field is current snapshot, so 349 stocks marked "ST" today were filtered as ST throughout history (some weren't ST at the time).
- **No minute-level data**: event strategies relying on intra-day execution (10:30 board / sealed-bid / partial-fill) cannot be tested at daily frequency. H8/H9 falsification specifically demonstrates this boundary.

See [`AUDIT_FINDINGS_2026_04_27.md`](AUDIT_FINDINGS_2026_04_27.md) for the full list.

## Adding a new strategy

1. Write a `detect_fn` (event) or `factor_fn` (cross-sectional) that returns the signal.
2. Pass it through `Backtest()` with all 5 hard-rail params filled in.
3. Inspect `result.full_summary["alpha_mean"]` and `result.full_summary["t_stat"]`.
4. **If `|t| > 2`**: re-run with different `seed`, check Train/Test split is honored, run `self_test.py` to confirm framework didn't drift.
5. **If alpha looks too good**: it almost certainly is. The 8-round project history says the median backtest deflates 70% on rigorous audit.
