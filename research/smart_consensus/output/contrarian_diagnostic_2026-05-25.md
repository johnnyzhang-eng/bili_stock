# Smart Consensus Contrarian Diagnostic — 2026-05-25

Execution: `.venv/bin/python -B research/smart_consensus/test_contrarian.py`.

Scope: diagnostic only. This uses current corrected `smart_consensus_ffill.csv`
and `forward_returns_v2.csv`, but it is not a fully size/liquidity/industry
matched foundation verdict. Canonical cycle001 verdict remains
`research/smart_consensus/verdict_2026-05-24_foundation.md`.

## Result

| strategy | gross CAGR | net CAGR after 56bp/week | Sharpe | win% |
|---|---:|---:|---:|---:|
| top_decile_smart | +11.22% | -16.92% | +0.37 | 54.4% |
| bot_decile_smart | +11.18% | -16.95% | +0.35 | 57.6% |
| no_smart_random | +23.95% | -7.36% | +0.74 | 58.0% |
| all_random | +20.41% | -10.01% | +0.66 | 58.3% |

## Contrarian Tests

- `bot_decile_smart - top_decile_smart`: mean weekly `+0.0063%`, annualized `+0.33%`, `t=+0.09`.
- Avoid-top filter: random from universe minus top-smart had CAGR `+19.33%`; random from full universe `+20.10%`; excess weekly `-0.0153%`, annualized `-0.80%`, `t=-0.23`.

## Verdict

The old direction lesson ("do not blindly follow top smart-consensus stocks") is
still useful as a caution, but the old `Top30 - Bottom30 = -6.8pp` style number
is not current strict evidence. Current diagnostic shows no significant
top-vs-bottom contrarian edge and no significant avoid-top benefit.
