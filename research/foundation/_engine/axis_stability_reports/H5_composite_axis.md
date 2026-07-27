# Axis Stability Audit — H5 Composite Axis

**Source**: `research/smart_consensus/output/H5_composite_axis.csv`
**Reviewed commit**: `db3df2f`
**Reviewer**: Codex ATK

## Metric Result

The submitted composite axis narrowly passes the median-rotation B8 metric:

| Axis sample | Quarters | Median cohort size | Median rotation | P75 rotation | Max rotation | Metric |
|---|---:|---:|---:|---:|---:|---|
| submitted composite, all history | 38 | 35 | 18.90%/Q | 23.81%/Q | 100.00%/Q | PASS |
| submitted composite, post-2018 | 33 | 41 | ~20.00%/Q | 26.19%/Q | 100.00%/Q | borderline |
| turnover-only, all history | 49 | 42 | 11.90%/Q | 19.05%/Q | 98.81%/Q | PASS |
| turnover-only, post-2018 | 33 | 41 | 16.28%/Q | 20.93%/Q | 98.81%/Q | PASS |

## Attacker Verdict

**BLOCK despite metric PASS.**

The submitted axis is computed over `research/smart_consensus/output/smart_cubes_v1.csv`, a 96-cube snapshot/performance-selected pool with `annualized_gain_rate > 25` for every row. The workspace contains 926 cube rebalancing JSON files. Therefore the B8 metric measures stability inside a forward-selected subset, not stability of the H5 behavioral axis over the actual candidate universe.

H5 cannot enter strategy implementation until the axis is recomputed over all cubes, or over an ex-ante behavior-only eligibility universe that does not use current `annualized_gain_rate`, followers, or any other current snapshot profile field.

