"""
H4 — Skill-weighted Buy Intensity, foundation implementation (cycle 001).

Thesis: stocks with high skill-weighted "fresh buy" activity from smart cubes
over the past 30 trading days have positive cross-sectional predictive power
for the next quarter's return.

Per PHASE_1_PLAN.md prior_pr_alpha = 0.10. This is the weakest of cycle 001's
4 hypotheses because it still rides the skill axis (uses rolling_ann_gain to
weight by cube skill). Codex's H5 (cycle 002) abandons skill axis entirely.

Factor construction:
- For each smart-cube event with target_weight > prev_weight (a buy/add):
    delta = target_weight - prev_weight
    skill = log1p(clip(rolling_ann_gain[cube, event_bucket], 25, 200))
    contribution = skill * delta
- Sum contributions per (date, stock).
- Rolling 30-day sum per stock = current buy-intensity.
- factor_fn returns the most recent value <= sig_date for each stock,
  with deterministic jitter to break zero-intensity ties (B7).
"""
import hashlib
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

import numpy as np
import pandas as pd

from research.foundation import (
    Backtest,
    CostModel,
    CrossSectionalStrategy,
    DataBundle,
    StandardReport,
    Universe,
)
from research.smart_consensus.cube_events import iter_trade_events, load_rolling_ann


_INTENSITY_CACHE: dict = {}


def _load_intensity_panel() -> pd.DataFrame:
    """Build daily date × stock buy-intensity panel with 30-day rolling sum.

    Computed once per session. Reuses cube_events.iter_trade_events to get
    smart-cube-filtered buy events.
    """
    if "df" not in _INTENSITY_CACHE:
        rolling = load_rolling_ann()

        rows = []
        for e in iter_trade_events(rolling_ann=rolling):
            # Only count buys (target > prev)
            delta = e.target_weight - e.prev_weight
            if delta <= 0:
                continue
            bucket = e.dt.to_period("W-SUN").start_time.normalize()
            if bucket not in rolling.index or e.cube not in rolling.columns:
                continue
            ann = rolling.at[bucket, e.cube]
            if pd.isna(ann):
                continue
            skill = float(np.log1p(np.clip(float(ann), 25.0, 200.0)))
            rows.append({
                "date": e.dt.normalize(),
                "stock": e.stock,
                "contribution": skill * delta,
            })

        if not rows:
            _INTENSITY_CACHE["df"] = pd.DataFrame()
            return _INTENSITY_CACHE["df"]

        df = pd.DataFrame(rows)
        panel = df.groupby(["date", "stock"])["contribution"].sum().unstack(fill_value=0.0)
        panel = panel.sort_index()
        # Rolling 30 calendar-day sum (~22 trading days, close enough to "past 30 trading days")
        panel = panel.rolling("30D").sum()
        _INTENSITY_CACHE["df"] = panel
    return _INTENSITY_CACHE["df"]


def _stable_jitter(code: str, sig_date) -> float:
    """B7 tie-order avoidance jitter, deterministic per (code, sig_date)."""
    key = f"{code}|{pd.Timestamp(sig_date).strftime('%Y-%m-%d')}".encode()
    return (int(hashlib.md5(key).hexdigest()[:12], 16) % 10**9) / 10**9


def factor_h4_intensity(row, price_cache, sig_date) -> float:
    panel = _load_intensity_panel()
    if panel.empty:
        return float("nan")
    code = str(row["code"]).zfill(6)
    if code not in panel.columns:
        return float("nan")
    col = panel[code].loc[:pd.Timestamp(sig_date)]
    if col.empty:
        return float("nan")
    val = float(col.iloc[-1])
    # Jitter for zero-intensity ties (most of universe will be 0)
    return val + _stable_jitter(code, sig_date) * 1e-6


def make_strategy(
    *,
    top_pct: float = 0.20,
    n_signal_cap: int = 30,
    hold_days: int = 63,
) -> CrossSectionalStrategy:
    return CrossSectionalStrategy(
        name=(
            "H4 skill-weighted buy intensity (quarterly; "
            f"top {int(top_pct * 100)}%, hold={hold_days}d)"
        ),
        factor_fn=factor_h4_intensity,
        top_pct=top_pct,
        n_signal_cap=n_signal_cap,
        hold_days=hold_days,
    )


def run(data: DataBundle | None = None, verbose: bool = True):
    if data is None:
        data = DataBundle.load(verbose=False)

    universe = Universe.broad(
        data,
        mcap_range=(30, 500),
        min_turnover_20d=0.15,
        exclude_st=True,
        exclude_new_listing_days=180,
    )
    strategy = make_strategy()
    cost = CostModel.a_share_retail_quarterly()
    bt = Backtest(
        strategy=strategy,
        universe=universe,
        cost_model=cost,
        random_control=True,
        train_test_split=("2021-12-31", "2022-01-01"),
        year_start=2017,
        year_end=2026,
        seed=42,
    )
    return bt.run(verbose=verbose)


def main():
    print("=" * 80)
    print("  H4 — Skill-weighted Buy Intensity (quarterly)")
    print("=" * 80)
    print("  Prior Pr(VALIDATE) = 0.10 (weakest of cycle 001; still on skill axis)")
    print()
    result = run(verbose=True)
    report = StandardReport.from_result(result)
    report.print()

    out_dir = os.path.join(os.path.dirname(__file__), "..", "smart_consensus", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "h4_buy_intensity_foundation.md")
    report.save(out_path)
    print(f"\n[+] Report written to {out_path}")


if __name__ == "__main__":
    main()
