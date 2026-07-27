# PR #6 Update Draft — Cycle 001 Retraction

Posted to PR #6: https://github.com/Soli22de/Bili_Stock/pull/6#issuecomment-4527438379

Cycle 001 foundation rerun is complete. The original A1 claim in this PR is retracted.

TL;DR:

| Hypothesis | Foundation result |
|---|---|
| A1 Smart Cube Avoidance | REJECT: alpha +0.15%/period, t=+0.12 |
| H2 Smart Cube Cluster-Buy | REJECT: alpha +0.90%/period, t=+0.71 |
| H3 Smart Cube Mass-Exit | REJECT: alpha +0.33%/period, t=+0.29 |
| H4 Skill-Weighted Buy Intensity | REJECT: alpha -1.17%/period, t=-0.99 |

Replacement artifacts:

- `research/smart_consensus/verdict_2026-05-24_foundation.md`
- `research/smart_consensus/verdict_2026-05-23.md` with top-of-file RETRACTED banner
- `research/foundation/METHODOLOGY_AUDIT_2026-05-23.md`
- `research/foundation/IC_DELTA_2026-05-23.md`
- `research/foundation/_engine/negative_log.md`
- `research/foundation/_engine/cycles/cycle_001_2026-05-24.md`

Codex re-ran `research/foundation/self_test.py` on 2026-05-24: 7/7 PASS, then re-ran `research/foundation/run_all_hypotheses.py` and reproduced all four REJECT verdicts.

Codex also ran `research/foundation/cycle001_matched_baseline.py`: A1 `+0.57%/period, t=+0.70`; H4 `-1.66%/period, t=-1.31`. Size/liquidity matching does not rescue either cross-sectional result. H2/H3 use same-stock non-event random controls.

Cycle 002 is spawned as proposals only: H5 Behavioral Adverse Selection and I-B1 可转债套利. It has not started execution from this Cycle 001 closure.
