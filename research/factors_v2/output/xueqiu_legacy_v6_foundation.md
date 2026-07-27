# Xueqiu Legacy v4-v6/SRF — Foundation-Compatible Rerun

Execution: `.venv/bin/python -B research/foundation/run_xueqiu_legacy_foundation.py --rebuild-panel`.

Rules:
- Reuses legacy point-in-time signal/feature construction only (`_prepare_panel_v5`, `_enrich_from_stock_data`).
- Applies B2-style timestamp discipline: panel rows are shifted to the first trading day strictly after the source event date.
- Does not call legacy `_build_rebalance`, `_apply_risk_controls`, `_run_one`, go-flat, take-profit, or long-short spread metrics.
- Selection does not read `fwd_ret_2w` or any forward-return column.
- Return is recomputed from `DataBundle.price_cache` after selection.
- Random control and size/turnover matched control are sampled from the same signal-covered investable universe.
- Round-trip cost: `0.56%`; hold horizons: `[10, 12, 15]` business days.
- Train/Test: train <= `2020-12-31`, test >= `2021-03-01`; gap in between dropped.
- Data window: `2015-01-01` -> `2025-12-31`; seeds: `[1, 42, 99]`.

## Summary vs Matched Control

| variant | hold | seed | train alpha | train t | test alpha | test t | full alpha | full t | ann net | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| legacy_follow_top30pct_cap30 | 10 | 1 | -0.03% | -0.09 | +0.37% | +1.39 | +0.25% | +1.19 | -4.1% | REJECT_SIGN_FLIP |
| legacy_follow_top30pct_cap30 | 10 | 42 | +0.08% | +0.35 | +0.27% | +0.83 | +0.21% | +0.90 | -4.1% | REJECT_OOS_WEAK |
| legacy_follow_top30pct_cap30 | 10 | 99 | -0.32% | -1.01 | +0.22% | +0.78 | +0.06% | +0.25 | -4.1% | REJECT_SIGN_FLIP |
| legacy_follow_top30pct_cap30 | 12 | 1 | +0.46% | +1.55 | -0.11% | -0.36 | +0.12% | +0.52 | +0.2% | REJECT_SIGN_FLIP |
| legacy_follow_top30pct_cap30 | 12 | 42 | +0.35% | +1.14 | -0.36% | -1.29 | -0.08% | -0.37 | +0.2% | REJECT_SIGN_FLIP |
| legacy_follow_top30pct_cap30 | 12 | 99 | +0.70% | +2.35 | -0.22% | -0.66 | +0.15% | +0.64 | +0.2% | REJECT_SIGN_FLIP |
| legacy_follow_top30pct_cap30 | 15 | 1 | -0.08% | -0.18 | +0.17% | +0.38 | +0.09% | +0.28 | +9.3% | REJECT_SIGN_FLIP |
| legacy_follow_top30pct_cap30 | 15 | 42 | -0.19% | -0.42 | +0.29% | +0.67 | +0.14% | +0.42 | +9.3% | REJECT_SIGN_FLIP |
| legacy_follow_top30pct_cap30 | 15 | 99 | +0.47% | +1.12 | +0.12% | +0.28 | +0.23% | +0.70 | +9.3% | REJECT_OOS_WEAK |
| legacy_contrarian_bottom30pct_cap30 | 10 | 1 | -0.26% | -0.83 | +0.18% | +0.73 | +0.04% | +0.21 | -4.1% | REJECT_SIGN_FLIP |
| legacy_contrarian_bottom30pct_cap30 | 10 | 42 | +0.03% | +0.09 | +0.45% | +1.79 | +0.32% | +1.61 | -4.1% | REJECT_OOS_WEAK |
| legacy_contrarian_bottom30pct_cap30 | 10 | 99 | -0.07% | -0.23 | +0.37% | +1.44 | +0.23% | +1.17 | -4.1% | REJECT_SIGN_FLIP |
| legacy_contrarian_bottom30pct_cap30 | 12 | 1 | +0.30% | +0.99 | -0.26% | -1.03 | -0.03% | -0.18 | -0.1% | REJECT_SIGN_FLIP |
| legacy_contrarian_bottom30pct_cap30 | 12 | 42 | +0.67% | +2.34 | -0.59% | -1.77 | -0.08% | -0.36 | -0.1% | REJECT_SIGN_FLIP |
| legacy_contrarian_bottom30pct_cap30 | 12 | 99 | +0.92% | +2.95 | -0.50% | -1.62 | +0.07% | +0.29 | -0.1% | REJECT_SIGN_FLIP |
| legacy_contrarian_bottom30pct_cap30 | 15 | 1 | +0.62% | +2.08 | -0.16% | -0.32 | +0.09% | +0.24 | +8.8% | REJECT_SIGN_FLIP |
| legacy_contrarian_bottom30pct_cap30 | 15 | 42 | +0.55% | +1.91 | +0.09% | +0.21 | +0.23% | +0.75 | +8.8% | REJECT_OOS_WEAK |
| legacy_contrarian_bottom30pct_cap30 | 15 | 99 | +0.45% | +1.08 | -0.39% | -0.79 | -0.13% | -0.35 | +8.8% | REJECT_SIGN_FLIP |
| srf_v2_gate_top15_no_goflat | 10 | 1 | +0.55% | +1.09 | -0.05% | -0.11 | +0.14% | +0.39 | +0.0% | REJECT_SIGN_FLIP |
| srf_v2_gate_top15_no_goflat | 10 | 42 | +0.79% | +1.77 | +0.53% | +1.30 | +0.61% | +1.96 | +0.0% | REJECT_OOS_WEAK |
| srf_v2_gate_top15_no_goflat | 10 | 99 | +0.54% | +1.14 | +0.14% | +0.33 | +0.26% | +0.82 | +0.0% | REJECT_OOS_WEAK |
| srf_v2_gate_top15_no_goflat | 12 | 1 | +0.18% | +0.39 | +1.02% | +1.92 | +0.69% | +1.86 | +5.1% | REJECT_OOS_WEAK |
| srf_v2_gate_top15_no_goflat | 12 | 42 | +0.48% | +0.94 | +1.08% | +2.05 | +0.84% | +2.23 | +5.1% | NEEDS_DEEP_AUDIT_NOT_PRODUCTION |
| srf_v2_gate_top15_no_goflat | 12 | 99 | +0.24% | +0.51 | +1.08% | +2.11 | +0.75% | +2.06 | +5.1% | NEEDS_DEEP_AUDIT_NOT_PRODUCTION |
| srf_v2_gate_top15_no_goflat | 15 | 1 | +1.73% | +3.27 | +0.27% | +0.34 | +0.73% | +1.25 | +16.6% | REJECT_OOS_WEAK |
| srf_v2_gate_top15_no_goflat | 15 | 42 | +1.12% | +2.60 | +0.75% | +1.01 | +0.86% | +1.65 | +16.6% | REJECT_OOS_WEAK |
| srf_v2_gate_top15_no_goflat | 15 | 99 | +1.86% | +3.32 | +0.19% | +0.25 | +0.71% | +1.28 | +16.6% | REJECT_OOS_WEAK |

## Overall Verdict

- `legacy_follow_top30pct_cap30`: rejected. It does not survive matched control across seeds and hold horizons; train/test sign flips are common.
- `legacy_contrarian_bottom30pct_cap30`: rejected as a production strategy. The old inversion lesson remains useful, but the clean matched-control implementation does not produce stable positive OOS alpha.
- `srf_v2_gate_top15_no_goflat`: warning only. The 12-business-day horizon shows a weak positive anomaly for seed 42/99, but 10-day and 15-day horizons fail OOS significance. This is the old `hold_step` sensitivity red flag, so it is not production and must not be connected to the dashboard as an alpha source.

## Interpretation

- `legacy_follow_top30pct_cap30`: closest clean read of the old Xueqiu follow/rank gate without legacy risk controls.
- `legacy_contrarian_bottom30pct_cap30`: tests the documented signal inversion directly against a matched control.
- `srf_v2_gate_top15_no_goflat`: keeps the Xueqiu top-30% gate and SRF v2 re-ranker, but removes asymmetric choppy go-flat and other old risk controls.
- Any positive row here is not production. It still needs B8/axis stability, seed/date robustness, and a stricter implementation review before it can be treated as a live candidate.

CSV: `research/factors_v2/output/xueqiu_legacy_v6_foundation.csv`
