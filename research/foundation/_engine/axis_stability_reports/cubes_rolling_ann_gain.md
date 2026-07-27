# Axis Stability Audit — cubes_rolling_ann_gain

**Source**: `research/smart_consensus/output/rolling_ann_gain.csv`
**Skill range**: (25.0, 200.0]
**Threshold**: < 20%/Q median rotation

**Verdict**: ❌ BLOCK

## Summary
- Quarters checked: 44
- Median cohort size: 59
- Median rotation: **33.7%/Q**
- P75 rotation: 51.1%/Q
- Max rotation: 100.0%/Q

## Why this blocks hypotheses

Cycle 001 showed (lessons_learned L9 + L10) that selection axes
rotating > 20%/quarter generate signals with
Train/Test sign divergence regardless of hypothesis specifics.
This axis's 33.7%/Q median rotation matches
that failure pattern.

Any hypothesis using this exact axis must:
1. Switch to a different axis (behavioral observable, not rolling skill), or
2. Restrict universe to the stable sub-cohort (cubes in cohort > N consecutive quarters), or
3. Explicitly document the instability in cycle file and accept REJECT outcome.
