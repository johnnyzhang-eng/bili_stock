# Axis Stability Audit — H5_V2_turnover_only_axis

**Source**: `research/smart_consensus/output/H5_axis_turnover_only.csv`
**Skill range**: (0.5, 1.0]
**Threshold**: < 20%/Q median rotation

**Verdict**: ❌ BLOCK

## Summary
- Quarters checked: 46
- Median cohort size: 39
- Median rotation: **43.7%/Q**
- P75 rotation: 56.8%/Q
- Max rotation: 76.6%/Q

## Why this blocks hypotheses

Cycle 001 showed (lessons_learned L9 + L10) that selection axes
rotating > 20%/quarter generate signals with
Train/Test sign divergence regardless of hypothesis specifics.
This axis's 43.7%/Q median rotation matches
that failure pattern.

Any hypothesis using this exact axis must:
1. Switch to a different axis (behavioral observable, not rolling skill), or
2. Restrict universe to the stable sub-cohort (cubes in cohort > N consecutive quarters), or
3. Explicitly document the instability in cycle file and accept REJECT outcome.
