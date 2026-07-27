"""
H2 — Smart cube cluster-buy event, foundation implementation.

Thesis: when at least 3 ex-ante smart cubes newly open the same stock within
7 calendar days, the event may represent consensus formation and should
outperform same-stock random non-event days.

This file only defines/runs the foundation strategy. Event extraction lives in
research.smart_consensus.cube_events.
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
            "H2 smart-cube cluster buy "
            f"(min_cubes={min_cubes}, window={window_days}d, hold={hold_days}d)"
        ),
        detect_fn=make_cluster_detect_fn(
            side="buy",
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
        # Rolling smart-cube eligibility leaves H2 events mostly in 2025-2026.
        # This is the earliest split with a non-empty train and a 60d gap.
        train_test_split=("2025-12-31", "2026-03-01"),
        year_start=2017,
        year_end=2026,
        seed=42,
    )
    return bt.run(verbose=verbose)


def main():
    print("=" * 80)
    print("  H2 — Smart cube cluster-buy event")
    print("=" * 80)
    result = run(verbose=True)
    report = StandardReport.from_result(result)
    report.print()

    out_dir = os.path.join(os.path.dirname(__file__), "..", "smart_consensus", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "h2_cluster_buy_foundation.md")
    report.save(out_path)
    print(f"\n[+] Report written to {out_path}")


if __name__ == "__main__":
    main()
