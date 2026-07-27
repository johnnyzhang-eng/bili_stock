# Cycle 001 Size/Liquidity-Matched Baseline Audit

Cross-sectional strategies A1 and H4 are re-scored against a stricter
per-period baseline: one random non-signal stock per pick from the same
market-cap decile and 20-day-turnover decile, with deterministic fallback
to one-axis matching when a cell is empty.

H2 and H3 are event-driven and already use same-stock random non-event
dates in the foundation engine; size, liquidity, board, and industry are
therefore fixed by stock identity.

| ID | Split | n | alpha/period | t | Verdict impact |
|---|---|---:|---:|---:|---|
| A1 | train | 19 | +0.10% | +0.09 |  |
| A1 | test | 16 | +1.13% | +0.93 |  |
| A1 | full | 35 | +0.57% | +0.70 | REJECT unchanged |
| H4 | train | 19 | +0.21% | +0.11 |  |
| H4 | test | 16 | -3.89% | -3.08 |  |
| H4 | full | 35 | -1.66% | -1.31 | REJECT unchanged |

Output CSV: `research/smart_consensus/output/cycle001_matched_baseline.csv`
