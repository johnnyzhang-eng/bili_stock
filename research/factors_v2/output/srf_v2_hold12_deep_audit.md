# SRF v2 Hold=12 Anomaly — Deep Audit (2026-05-26)

Execution source:

- Base rerun: `.venv/bin/python -B research/foundation/run_xueqiu_legacy_foundation.py --seeds 1,42,99 --hold-bdays 10,12,15 --rebuild-panel`
- Input CSV: `research/factors_v2/output/xueqiu_legacy_v6_foundation.csv`
- Follow-up audit: split by hold horizon, seed, year, regime, half-sample, and control type.

## What Was Being Audited

The only residual positive Xueqiu/SRF result after the foundation-compatible rerun was:

- variant: `srf_v2_gate_top15_no_goflat`
- hold: `12` business days
- seed 42/99 Test alpha vs matched control: about `+1.08%/period`, `t=2.05/2.11`

This was explicitly not production in the first report because hold=10 and hold=15 failed.

## Hold-Horizon Stability

Matched-control Test results:

| hold | seed | n | test alpha | t | verdict |
|---:|---:|---:|---:|---:|---|
| 10 | 1 | 73 | -0.049% | -0.11 | fail |
| 10 | 42 | 73 | +0.531% | +1.30 | fail |
| 10 | 99 | 73 | +0.137% | +0.33 | fail |
| 12 | 1 | 54 | +1.025% | +1.92 | borderline fail |
| 12 | 42 | 54 | +1.081% | +2.05 | weak pass before multiplicity |
| 12 | 99 | 54 | +1.084% | +2.11 | weak pass before multiplicity |
| 15 | 1 | 46 | +0.271% | +0.34 | fail |
| 15 | 42 | 46 | +0.747% | +1.01 | fail |
| 15 | 99 | 46 | +0.191% | +0.25 | fail |

Conclusion: the signal is not hold-horizon stable. It is concentrated at the legacy `hold_step=12` cadence.

## Multiplicity Check

The apparent positives are one pocket among `3 hold horizons x 3 seeds`.

Two-sided p-values for hold=12 matched-control Test:

| seed | t | p | Bonferroni over 9 tests |
|---:|---:|---:|---:|
| 1 | +1.92 | 0.0596 | 0.5367 |
| 42 | +2.05 | 0.0454 | 0.4082 |
| 99 | +2.11 | 0.0398 | 0.3581 |
| date-mean across seeds | +2.15 | 0.0359 | 0.3232 |

Conclusion: the edge does not survive even a crude multiple-testing correction.

## Date-Mean Control

Because the 3 seeds share the same signal picks and only vary the control sample, seed rows are not fully independent. Aggregating alpha by `signal_date` gives:

| control | n_dates | mean alpha | t | win rate |
|---|---:|---:|---:|---:|
| matched | 54 | +1.063% | +2.15 | 61.1% |
| random | 54 | +0.917% | +1.93 | 59.3% |

Interpretation: the anomaly is not purely an unlucky matched-control draw, but it remains weak and multiplicity-sensitive.

## Year Stability

Date-mean matched-control alpha by Test year:

| year | n | mean alpha | t |
|---:|---:|---:|---:|
| 2021 | 9 | +0.554% | +0.57 |
| 2022 | 12 | +1.813% | +1.49 |
| 2023 | 9 | +1.032% | +1.61 |
| 2024 | 7 | +0.296% | +0.43 |
| 2025 | 17 | +1.136% | +0.97 |

No single Test year is independently significant.

## Regime Stability

Matched-control hold=12 Test by regime:

| seed | regime | n | mean alpha | t |
|---:|---|---:|---:|---:|
| 1 | 上涨 | 15 | +3.226% | +2.75 |
| 1 | 下跌 | 14 | +1.019% | +1.04 |
| 1 | 震荡 | 25 | -0.292% | -0.47 |
| 42 | 上涨 | 15 | +2.190% | +1.73 |
| 42 | 下跌 | 14 | +1.142% | +0.98 |
| 42 | 震荡 | 25 | +0.380% | +0.69 |
| 99 | 上涨 | 15 | +2.249% | +1.72 |
| 99 | 下跌 | 14 | +0.909% | +0.97 |
| 99 | 震荡 | 25 | +0.482% | +0.82 |

The strongest contribution is in upward regimes. Choppy regimes, historically the original v6.1 thesis, do not show robust alpha.

## Half-Sample Stability

Matched-control hold=12 Test, split chronologically:

| seed | half | n | mean alpha | t |
|---:|---|---:|---:|---:|
| 1 | first half | 27 | +1.399% | +2.17 |
| 1 | second half | 27 | +0.651% | +0.76 |
| 42 | first half | 27 | +1.332% | +1.79 |
| 42 | second half | 27 | +0.829% | +1.09 |
| 99 | first half | 27 | +1.205% | +1.82 |
| 99 | second half | 27 | +0.963% | +1.21 |

The second half remains positive but loses significance.

## Verdict

`srf_v2_gate_top15_no_goflat` is not production.

It is a research-only anomaly:

- It is concentrated at the legacy hold=12 cadence.
- It fails hold=10 and hold=15.
- It does not survive simple multiple-testing correction.
- It is not independently significant by year.
- It is weaker in the second half of Test.
- It is strongest in upward regimes, not in the original choppy-regime thesis.

Dashboard integration: do not connect this as alpha. At most, list it as a research backlog item requiring B8 axis-stability, date bootstrap, stronger matched controls, and a fresh preregistered runner.
