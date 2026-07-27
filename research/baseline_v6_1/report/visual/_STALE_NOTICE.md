# Stale Pre-Audit Reports — Notice

**The files listed below were generated before the independent audit of 2026-04-14 that revealed ~70% of the reported alpha was look-ahead bias.**

**Their numbers are not valid and should not be cited.** They are preserved only as evidence of the audit journey.

---

## Affected files in this directory

| File | Why it is stale |
|---|---|
| `_qc_deep.txt` | Shows ann_ret 32.4%, Calmar 1.426 — all inflated by the go-flat look-ahead bug (fix: commit `1a1fb68`). |
| `_qc_audit.txt` | Uses long-short (Top30 − Bottom30) metrics; A-shares cannot short, so the reported spread is non-executable (fix: commit `9a88817`). |
| `_sanity_check.txt` | Per-year returns (e.g. "2014: +67.9%") use the unfixed engine and/or incorrect annualisation; correct engine produces much lower realised returns. |
| `_cost_audit.txt` | Cost sensitivity was run against 10 bp single-side, not the realistic 56 bp round-trip (fix: commit `25c2684`). |
| `_long_only_metrics.txt` | Early long-only derivation, partially superseded; check specific numbers against current `run_baseline_v6_v61_suite.py` output before citing. |
| `_practical_analysis.txt` | Practical-trading implications derived from pre-audit equity curve — conclusions are optimistic by ~20 pp annualised. |

## What to read instead

- [`docs/quant_strategy_lessons.md`](../../../../docs/quant_strategy_lessons.md) — the full structural post-mortem
- [`CLAUDE.md`](../../../../CLAUDE.md) — honest post-audit numbers
- [`research/baseline_v6_1/output/holdstep_sweep.csv`](../../output/holdstep_sweep.csv) — the only current, fully-honest performance report in this repo

## Reproducing honest numbers

The engine in the current `master` branch produces honest numbers by default. Rerunning any of the legacy visual reports with the current engine will overwrite these files with correct data — do not assume the existing outputs are safe to cite.

---

*Added 2026-04-17 as part of the Track-1 repository-value rewrite. See `README.md`.*
