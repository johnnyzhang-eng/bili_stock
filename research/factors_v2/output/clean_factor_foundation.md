# Clean Factor — Foundation Rerun (2026-05-25)

Execution: `.venv/bin/python -B research/foundation/run_clean_factor_foundation.py`.

Legacy source: `research/factors_v2/run_clean_factor_backtest.py`.

Rules: `DataBundle.load`, broad 30-500亿 universe, top 20% capped at 30, hold_days=17, `CostModel.a_share_retail_swing`, `random_control=True`, train/test split at 2021-01-01. Actual random-control seeds are shown in the table.

Important caveat: Foundation cross-sectional engine rebalances quarterly. The legacy script rebalanced every 12 trading days. This rerun tests whether the signal survives strict project rails, not whether the legacy high-frequency loop is executable.

| factor | seed | n | train alpha | train t | test alpha | test t | full alpha | full t | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| combo_z | 42 | 35 | -1.29% | -3.60 | -0.24% | -0.35 | -0.69% | -1.60 | REJECT_NEGATIVE |
| dist_a | 1 | 35 | -0.21% | -0.49 | -0.19% | -0.38 | -0.20% | -0.59 | REJECT_NEGATIVE |
| dist_a | 42 | 35 | -0.63% | -1.60 | +0.18% | +0.41 | -0.17% | -0.55 | REJECT_NOT_SIGNIFICANT |
| dist_a | 99 | 35 | +0.07% | +0.16 | -0.46% | -0.61 | -0.23% | -0.49 | REJECT_NEGATIVE |
| hvbal_b | 42 | 35 | -1.17% | -3.44 | -1.35% | -1.92 | -1.28% | -3.02 | REJECT_NEGATIVE |

## Verdict

This file is an audit artifact, not a production recommendation. A positive row only means the legacy clean factor deserves deeper review: B8-style axis stability, date bootstrap, matched controls, and an implementation that can model the original 12-trading-day cadence without reintroducing legacy backtest-loop bugs.
