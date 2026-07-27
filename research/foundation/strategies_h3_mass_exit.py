"""
H3 — Smart cube mass-exit event, foundation implementation.

Thesis: when at least 3 ex-ante smart cubes simultaneously exit the same stock
within 7 calendar days, the cluster represents insider-information diffusion
and the stock should UNDERPERFORM same-stock random non-event days.

Note: A-share is long-only. H3's positive alpha thesis is INVERTED:
- H2 (buy cluster): positive alpha means "buying when smart cubes buy = profitable"
- H3 (exit cluster): positive alpha means "buying when smart cubes exit = profitable"
  which would VIOLATE the thesis. Thesis-confirming H3 verdict has NEGATIVE alpha.

This file reuses Codex's cube_events.make_cluster_detect_fn with side='exit'.
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from research.foundation import (
    Backtest,
    CostModel,
    DataBundle,
    EventDrivenStrategy,
    StandardReport,
    Universe,
)
from research.smart_consensus.cube_events import make_cluster_detect_fn


def make_strategy(
    *,
    min_cubes: int = 3,
    window_days: int = 7,
    hold_days: int = 5,
) -> EventDrivenStrategy:
    return EventDrivenStrategy(
        name=(
            "H3 smart-cube mass exit "
            f"(min_cubes={min_cubes}, window={window_days}d, hold={hold_days}d)"
        ),
        detect_fn=make_cluster_detect_fn(
            side="exit",
            min_cubes=min_cubes,
            window_days=window_days,
            cooldown_days=window_days,
        ),
        entry_at="next_open",
        exit_at="next_close",
        hold_days=hold_days,
    )


def run(data: DataBundle | None = None, verbose: bool = True):
    if data is None:
        data = DataBundle.load(verbose=False)

    universe = Universe.broad(
        data,
        mcap_range=(5, 100000),
        min_turnover_20d=0.0,
        exclude_st=True,
        exclude_new_listing_days=180,
    )
    strategy = make_strategy()
    cost = CostModel.a_share_retail_swing()
    bt = Backtest(
        strategy=strategy,
        universe=universe,
        cost_model=cost,
        random_control=True,
        # Same justification as H2: rolling smart-cube gate leaves tiny pre-2025 sample.
        train_test_split=("2025-12-31", "2026-03-01"),
        year_start=2017,
        year_end=2026,
        seed=42,
    )
    return bt.run(verbose=verbose)


def main():
    print("=" * 80)
    print("  H3 — Smart cube mass-exit event")
    print("=" * 80)
    print("  THESIS-CONFIRMING result: NEGATIVE alpha (smart-exit clusters predict drops)")
    print("=" * 80)
    result = run(verbose=True)
    report = StandardReport.from_result(result)
    report.print()

    # Note on interpretation: alpha sign reading is inverted for H3
    print()
    print("─" * 80)
    print("  H3 thesis sanity:")
    full = result.full_summary
    if full and "alpha_mean" in full:
        a, t = full["alpha_mean"] * 100, full["t_stat"]
        if a < 0 and t < -2:
            print(f"  alpha={a:+.2f}% / t={t:+.2f}  → THESIS CONFIRMED (cluster exit predicts drop)")
        elif a > 0 and t > 2:
            print(f"  alpha={a:+.2f}% / t={t:+.2f}  → THESIS REJECTED (sign reversed; smart-exit is wrong-way)")
        else:
            print(f"  alpha={a:+.2f}% / t={t:+.2f}  → INCONCLUSIVE (noise)")
    print("─" * 80)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "smart_consensus", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "h3_mass_exit_foundation.md")
    report.save(out_path)
    print(f"\n[+] Report written to {out_path}")


if __name__ == "__main__":
    main()
