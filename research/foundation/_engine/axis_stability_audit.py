"""
Axis Stability Audit (attack B8) — Alpha Discovery Engine

When a hypothesis family shares a SELECTION AXIS (e.g., "smart cubes" defined
by rolling 12M ann_gain > 25%), the axis itself must be temporally stable for
any signal derived from the cohort to generalize OOS.

Cycle 001 (2026-05-24) showed every skill-axis hypothesis (A1/H2/H3/H4)
suffering Train/Test alpha sign divergence. Diagnosis from lessons_learned
L9 + L10: the rolling-skill cohort rotates so fast that any per-cohort signal
is contaminated by reconstitution, not by genuine alpha decay.

This module BLOCKS such hypothesis families from entering RUNNING status
during cycle selection. It computes the quarter-over-quarter cohort overlap
of any axis defined as a (weeks × cubes) selection matrix.

Usage:
    from research.foundation._engine.axis_stability_audit import (
        audit_axis_stability, AxisStabilityReport
    )
    report = audit_axis_stability(
        axis_path="research/smart_consensus/output/rolling_ann_gain.csv",
        skill_min=25.0, skill_max=200.0,
    )
    if not report.passes:
        raise AxisInstabilityBlock(f"Axis {report.name} cohort rotation "
                                    f"{report.median_rotation_pct:.1f}%/Q "
                                    f"exceeds 20%/Q threshold")

Pass criterion: **median quarter-over-quarter member rotation rate < 20%**.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd


# Threshold: cycle 001 lessons_learned L9 — anything > 20%/Q rotation is the
# pattern that killed A1/H2/H3/H4. Conservative; can be loosened if a future
# hypothesis demonstrates stability of a wider window.
ROTATION_THRESHOLD_PCT = 20.0


class AxisInstabilityBlock(Exception):
    """Raised when an axis fails B8 audit and a hypothesis tries to RUN on it."""


@dataclass(frozen=True)
class AxisStabilityReport:
    name: str
    axis_path: str
    skill_min: float
    skill_max: float
    n_quarters_checked: int
    quarter_overlaps: List[float]      # fraction of cohort retained from prev quarter
    quarter_rotation_pcts: List[float]  # 100 * (1 - overlap)
    median_rotation_pct: float
    p75_rotation_pct: float
    max_rotation_pct: float
    median_cohort_size: int
    passes: bool

    def render_md(self) -> str:
        lines = [
            f"# Axis Stability Audit — {self.name}",
            "",
            f"**Source**: `{self.axis_path}`",
            f"**Skill range**: ({self.skill_min}, {self.skill_max}]",
            f"**Threshold**: < {ROTATION_THRESHOLD_PCT:.0f}%/Q median rotation",
            "",
            f"**Verdict**: {'✅ PASS' if self.passes else '❌ BLOCK'}",
            "",
            "## Summary",
            f"- Quarters checked: {self.n_quarters_checked}",
            f"- Median cohort size: {self.median_cohort_size}",
            f"- Median rotation: **{self.median_rotation_pct:.1f}%/Q**",
            f"- P75 rotation: {self.p75_rotation_pct:.1f}%/Q",
            f"- Max rotation: {self.max_rotation_pct:.1f}%/Q",
            "",
        ]
        if not self.passes:
            lines += [
                f"## Why this blocks hypotheses",
                f"",
                f"Cycle 001 showed (lessons_learned L9 + L10) that selection axes",
                f"rotating > {ROTATION_THRESHOLD_PCT:.0f}%/quarter generate signals with",
                f"Train/Test sign divergence regardless of hypothesis specifics.",
                f"This axis's {self.median_rotation_pct:.1f}%/Q median rotation matches",
                f"that failure pattern.",
                "",
                "Any hypothesis using this exact axis must:",
                "1. Switch to a different axis (behavioral observable, not rolling skill), or",
                "2. Restrict universe to the stable sub-cohort (cubes in cohort > N consecutive quarters), or",
                "3. Explicitly document the instability in cycle file and accept REJECT outcome.",
            ]
        return "\n".join(lines) + "\n"


def audit_axis_stability(
    *,
    axis_path: str,
    skill_min: float,
    skill_max: float,
    name: str | None = None,
) -> AxisStabilityReport:
    """Compute cohort rotation rate per quarter for a (weeks × members) axis CSV.

    Args:
        axis_path: CSV with date index (one row per week or any cadence) and
            member columns. Values represent the membership criterion (e.g.
            rolling ann_gain percentage).
        skill_min, skill_max: inclusive-lower / inclusive-upper bounds. A
            member is in the cohort at row T iff skill_min < value <= skill_max.
        name: optional report label. Defaults to the basename of axis_path.

    Returns:
        AxisStabilityReport with quarter-over-quarter overlap stats.
    """
    if name is None:
        name = os.path.basename(axis_path)

    df = pd.read_csv(axis_path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()].sort_index()

    # Resample to quarterly: for each quarter, the cohort = members satisfying
    # the criterion on the LAST observation of that quarter. Most operational
    # signal-date selectors take the last-known value, so this matches usage.
    quarter_end = df.resample("QE").last()

    cohort_history: list[set] = []
    for ts in quarter_end.index:
        row = quarter_end.loc[ts]
        cohort = set(
            row.index[(row > skill_min) & (row <= skill_max) & row.notna()].tolist()
        )
        cohort_history.append(cohort)

    overlaps: list[float] = []
    rotations: list[float] = []
    cohort_sizes: list[int] = []
    for i in range(1, len(cohort_history)):
        prev, curr = cohort_history[i - 1], cohort_history[i]
        if not prev:
            continue
        retained = len(prev & curr) / len(prev)
        overlaps.append(retained)
        rotations.append(100.0 * (1 - retained))
        cohort_sizes.append(len(curr))

    if not rotations:
        # Pathological: less than 2 quarters of data
        return AxisStabilityReport(
            name=name,
            axis_path=axis_path,
            skill_min=skill_min,
            skill_max=skill_max,
            n_quarters_checked=0,
            quarter_overlaps=[],
            quarter_rotation_pcts=[],
            median_rotation_pct=float("nan"),
            p75_rotation_pct=float("nan"),
            max_rotation_pct=float("nan"),
            median_cohort_size=0,
            passes=False,
        )

    median_rot = float(np.median(rotations))
    p75_rot = float(np.percentile(rotations, 75))
    max_rot = float(np.max(rotations))
    median_size = int(np.median(cohort_sizes)) if cohort_sizes else 0

    return AxisStabilityReport(
        name=name,
        axis_path=axis_path,
        skill_min=skill_min,
        skill_max=skill_max,
        n_quarters_checked=len(rotations),
        quarter_overlaps=overlaps,
        quarter_rotation_pcts=rotations,
        median_rotation_pct=median_rot,
        p75_rotation_pct=p75_rot,
        max_rotation_pct=max_rot,
        median_cohort_size=median_size,
        passes=median_rot < ROTATION_THRESHOLD_PCT,
    )


def gate_for_hypothesis(
    *,
    axis_path: str,
    skill_min: float,
    skill_max: float,
    hypothesis_id: str,
    name: str | None = None,
    write_report_to: str | None = None,
) -> AxisStabilityReport:
    """Hard gate function for hypothesis_registry promotion.

    Raises AxisInstabilityBlock if the axis fails B8. Writes the report to
    write_report_to if provided.
    """
    report = audit_axis_stability(
        axis_path=axis_path,
        skill_min=skill_min,
        skill_max=skill_max,
        name=name or f"axis_for_{hypothesis_id}",
    )

    if write_report_to:
        os.makedirs(os.path.dirname(write_report_to), exist_ok=True)
        with open(write_report_to, "w", encoding="utf-8") as f:
            f.write(report.render_md())

    if not report.passes:
        raise AxisInstabilityBlock(
            f"Hypothesis {hypothesis_id} fails B8 axis stability gate: "
            f"median rotation {report.median_rotation_pct:.1f}%/Q "
            f">= {ROTATION_THRESHOLD_PCT:.0f}%/Q threshold. "
            f"See cycle_001 lessons_learned L9/L10."
        )

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("axis_path", help="CSV path with weeks × members axis values")
    parser.add_argument("--skill-min", type=float, required=True)
    parser.add_argument("--skill-max", type=float, required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--write-report", default=None)
    args = parser.parse_args(argv)

    report = audit_axis_stability(
        axis_path=args.axis_path,
        skill_min=args.skill_min,
        skill_max=args.skill_max,
        name=args.name,
    )
    print(report.render_md())
    if args.write_report:
        os.makedirs(os.path.dirname(args.write_report) or ".", exist_ok=True)
        with open(args.write_report, "w", encoding="utf-8") as f:
            f.write(report.render_md())
        print(f"\n[+] Report written to {args.write_report}")

    return 0 if report.passes else 1


if __name__ == "__main__":
    sys.exit(main())
