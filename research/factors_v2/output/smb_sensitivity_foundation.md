# SMB Sensitivity — Foundation Rerun (2026-05-25)

Execution: `.venv/bin/python -B research/foundation/run_smb_sensitivity_foundation.py`.

Purpose: validate whether the 12-factor battery's Test-only SMB weak positive survives seed and size-bucket changes.

| bucket | seed | n | train alpha | train t | test alpha | test t | full alpha | full t | test win% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| broad_30_500 | 1 | 32 | -5.29% | -2.26 | +2.80% | +0.99 | -0.99% | -0.50 | 65% |
| broad_30_500 | 42 | 32 | -6.25% | -2.95 | +6.44% | +2.31 | +0.49% | +0.24 | 82% |
| broad_30_500 | 99 | 32 | -5.75% | -3.21 | +2.07% | +0.60 | -1.60% | -0.76 | 53% |
| small_30_100 | 1 | 32 | -4.85% | -1.91 | +4.56% | +1.55 | +0.15% | +0.07 | 53% |
| small_30_100 | 42 | 32 | -3.93% | -1.75 | +3.83% | +1.29 | +0.20% | +0.10 | 53% |
| small_30_100 | 99 | 32 | -3.61% | -2.07 | +1.66% | +0.53 | -0.81% | -0.43 | 53% |
| mid_100_500 | 1 | 32 | +2.74% | +0.87 | +4.09% | +1.79 | +3.46% | +1.84 | 76% |
| mid_100_500 | 42 | 32 | +0.18% | +0.07 | +3.48% | +1.63 | +1.93% | +1.16 | 59% |
| mid_100_500 | 99 | 32 | -0.17% | -0.06 | +2.81% | +1.61 | +1.41% | +0.83 | 59% |

Interpretation: a production-grade SMB claim requires stable positive alpha across seeds and across adjacent size buckets, without train/test sign reversal.
