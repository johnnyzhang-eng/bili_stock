"""
V2 Factor Library — IC & Cost-Aware Comparison
==============================================

Groundwork for the post-audit pivot. Per `docs/quant_strategy_lessons.md`,
the Xueqiu consensus signal is in an academically unstable category
(social sentiment + short-term momentum). This runner starts building the
alternative: value / quality / low-volatility factors with longer half-life.

First cut: low_volatility vs. existing Xueqiu factor (baseline).

Adds explicit turnover + annual-cost accounting that the existing
`run_signal_ic_comparison.py` does not report, so factors can be compared
on a net-of-cost basis — the thing that actually matters.

Output table columns:
    factor | IC | ICIR | hit% | turnover_per_period | annual_cost | top-bot spread (ann) | net after cost

Run:
    python research/factors_v2/run_v2_factor_ic.py
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors.factor_low_volatility import build_low_volatility_factor
from research.factors_v2.build_broad_panel import build_broad_panel

# --------------------------------------------------------------------------- #
# Cost & rebalance assumptions (matched to production CLAUDE.md)
# --------------------------------------------------------------------------- #
HOLD_STEP_BDAYS = 12                # production rebalance cadence
ROUND_TRIP_BP   = 56                # buy 13bp + sell 43bp
FWD_HORIZON_BP  = 10                # fwd_ret_2w ≈ 10 business days
BDAYS_PER_YEAR  = 252
QUINTILE_FRAC   = 0.20              # top / bottom 20% for spread


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


# --------------------------------------------------------------------------- #
# IC analysis
# --------------------------------------------------------------------------- #
def _ic_by_date(panel: pd.DataFrame, factor_col: str, ret_col: str = "fwd_ret_2w") -> pd.Series:
    sub = panel.dropna(subset=[factor_col, ret_col])
    ics = sub.groupby("date").apply(
        lambda g: g[factor_col].corr(g[ret_col]) if len(g) >= 10 else np.nan
    )
    return ics.dropna()


def _ic_summary(ics: pd.Series) -> dict:
    if ics.empty:
        return {"IC": np.nan, "ICIR": np.nan, "hit_rate": np.nan, "n_dates": 0}
    ic = float(ics.mean())
    icir = float(ic / ics.std()) if ics.std() > 0 else np.nan
    return {
        "IC": ic,
        "ICIR": icir,
        "hit_rate": float((ics > 0).mean() * 100),
        "n_dates": int(len(ics)),
    }


# --------------------------------------------------------------------------- #
# Quintile portfolio: top-bot spread + turnover
# --------------------------------------------------------------------------- #
def _quintile_analysis(
    panel: pd.DataFrame,
    factor_col: str,
    ret_col: str = "fwd_ret_2w",
    q: float = QUINTILE_FRAC,
    hold_step: int = HOLD_STEP_BDAYS,
) -> dict:
    """
    Build a paper top-quintile vs bottom-quintile portfolio that rebalances
    every `hold_step` business days. Measure:
      - per-period mean fwd return (top, bot, spread)
      - per-period turnover in the top quintile (fraction of names changed)
      - annualized spread and annualized trading cost

    fwd_ret_2w covers ~10 bdays, but we rebalance every hold_step=12 bdays.
    For the annualization, we conservatively use hold_step as the period length.
    """
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    if sub.empty:
        return {}

    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]
    if len(rebal_dates) < 3:
        return {}

    top_spreads = []
    bot_spreads = []
    spreads    = []
    turnovers  = []
    prev_top   = None

    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:  # need a reasonable cross-section
            continue
        hi = g[factor_col].quantile(1 - q)
        lo = g[factor_col].quantile(q)
        top = g[g[factor_col] >= hi]
        bot = g[g[factor_col] <= lo]
        if top.empty or bot.empty:
            continue

        top_ret = float(top[ret_col].mean())
        bot_ret = float(bot[ret_col].mean())
        top_spreads.append(top_ret)
        bot_spreads.append(bot_ret)
        spreads.append(top_ret - bot_ret)

        top_set = set(top["stock_symbol"].tolist())
        if prev_top is not None and prev_top:
            # turnover = fraction of top-quintile names that changed since last rebalance
            churn = len(top_set - prev_top) / max(len(top_set), 1)
            turnovers.append(churn)
        prev_top = top_set

    if not spreads:
        return {}

    periods_per_year = BDAYS_PER_YEAR / hold_step
    mean_top = float(np.mean(top_spreads))
    mean_bot = float(np.mean(bot_spreads))
    mean_spread = float(np.mean(spreads))
    turnover = float(np.mean(turnovers)) if turnovers else np.nan

    # Annualize: compound per-period returns (approximate, using mean)
    ann_top    = (1 + mean_top)    ** periods_per_year - 1
    ann_bot    = (1 + mean_bot)    ** periods_per_year - 1
    ann_spread = (1 + mean_spread) ** periods_per_year - 1

    # Annual cost: turnover applies to BOTH sides (top long + bot short, or
    # long-only top needs buying new names and selling old ones per period).
    # For long-only fair compare we cost only the top side.
    # One period churn=turnover% of names → pay round-trip on that fraction.
    ann_cost_long_only = (
        turnover * periods_per_year * (ROUND_TRIP_BP / 1e4)
        if not np.isnan(turnover) else np.nan
    )
    net_top_ann = ann_top - ann_cost_long_only if not np.isnan(ann_cost_long_only) else np.nan

    return {
        "top_ann_ret":  ann_top,
        "bot_ann_ret":  ann_bot,
        "spread_ann":   ann_spread,
        "turnover":     turnover,
        "ann_cost":     ann_cost_long_only,
        "net_top_ann":  net_top_ann,
        "n_periods":    len(spreads),
    }


# --------------------------------------------------------------------------- #
# Factor builders
# --------------------------------------------------------------------------- #
def _build_low_vol(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute low_vol factor scoped to the dates already in the panel."""
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    lv = build_low_volatility_factor(stock_dir, start_date=start, end_date=end)
    lv = lv.rename(columns={"factor_raw": "lv_raw", "factor_z": "lv_z"})
    return lv[["date", "stock_symbol", "lv_raw", "lv_z"]]


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    # ------------------------------------------------------------------- #
    # Load BROAD panel (all liquid A-share equities, not Xueqiu-filtered)
    # ------------------------------------------------------------------- #
    print("Loading broad panel (all liquid A-shares) ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    print(f"  broad panel: {len(panel):,} rows, "
          f"{panel['stock_symbol'].nunique()} stocks, "
          f"{panel['date'].nunique()} dates")

    # ------------------------------------------------------------------- #
    # Baseline Xueqiu factor: merged in from v5 panel for same date range.
    # Note: Xueqiu factor is defined only on the ~561-stock Xueqiu-active
    # subset, so within the broad panel it will be NaN for ~80% of rows.
    # IC is still computed over non-NaN rows — this is the fair comparison
    # (each factor evaluated where it has a value).
    # ------------------------------------------------------------------- #
    print("Loading Xueqiu baseline factor from v5 panel ...", flush=True)
    from research.baseline_v5.code.run_baseline_v5_with_costs import _prepare_panel_v5
    v5 = _prepare_panel_v5(start_date="2015-01-01", end_date="2025-12-31")
    v5["stock_symbol"] = v5["stock_symbol"].astype(str).str.upper()
    v5["date"] = pd.to_datetime(v5["date"]).dt.normalize()
    xq = v5[["date", "stock_symbol", "factor_z_raw"]].rename(columns={"factor_z_raw": "xueqiu_raw"})
    panel = panel.merge(xq, on=["date", "stock_symbol"], how="left")
    # Cross-sectional z-score for Xueqiu on BROAD universe.
    # Stocks not in Xueqiu subset stay NaN — they get excluded by
    # `_ic_by_date` / `_quintile_analysis` automatically.
    panel["xueqiu_z"] = panel.groupby("date")["xueqiu_raw"].transform(
        lambda s: _zscore(s.dropna()).reindex(s.index) if s.notna().any() else s
    )

    # ------------------------------------------------------------------- #
    # Build low_vol factor on the full stock_data directory, then merge.
    # ------------------------------------------------------------------- #
    print("Building low_volatility factor ...", flush=True)
    lv = _build_low_vol(panel)
    panel = panel.merge(lv, on=["date", "stock_symbol"], how="left")
    # Re-z within broad tradable universe.
    panel["lv_z"] = panel.groupby("date")["lv_raw"].transform(_zscore)

    factors = {
        "xueqiu (baseline)": "xueqiu_z",
        "low_volatility":    "lv_z",
    }

    rows = []
    print("\n" + "=" * 94)
    print(f"{'factor':<22s} {'IC':>8s} {'ICIR':>7s} {'hit%':>6s} "
          f"{'turn/p':>8s} {'ann_cost':>10s} {'spread_ann':>11s} {'net_top_ann':>12s}")
    print("-" * 94)
    for label, col in factors.items():
        ics = _ic_by_date(panel, col)
        ic_stats = _ic_summary(ics)
        q_stats  = _quintile_analysis(panel, col)

        row = {
            "factor":       label,
            "IC":           ic_stats["IC"],
            "ICIR":         ic_stats["ICIR"],
            "hit_pct":      ic_stats["hit_rate"],
            "n_dates":      ic_stats["n_dates"],
            "turnover":     q_stats.get("turnover", np.nan),
            "ann_cost":     q_stats.get("ann_cost", np.nan),
            "spread_ann":   q_stats.get("spread_ann", np.nan),
            "top_ann":      q_stats.get("top_ann_ret", np.nan),
            "bot_ann":      q_stats.get("bot_ann_ret", np.nan),
            "net_top_ann":  q_stats.get("net_top_ann", np.nan),
            "n_periods":    q_stats.get("n_periods", 0),
        }
        rows.append(row)
        print(f"{label:<22s} "
              f"{row['IC']:>8.4f} "
              f"{row['ICIR']:>7.3f} "
              f"{row['hit_pct']:>5.1f}% "
              f"{row['turnover']:>7.1%} "
              f"{row['ann_cost']:>9.2%} "
              f"{row['spread_ann']:>10.2%} "
              f"{row['net_top_ann']:>11.2%}")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "v2_factor_ic_comparison.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_path}")

    print("""
Reading the table
-----------------
  IC          : cross-sectional rank corr with fwd_ret_2w, mean over dates
  ICIR        : IC / std(IC); >0.5 is respectable for a single factor
  turn/p      : fraction of top-quintile names that changed per rebalance
  ann_cost    : turnover × 21 rebals/yr × 56bp round-trip
  spread_ann  : (top-quintile - bot-quintile) annualized; raw alpha proxy
  net_top_ann : top-quintile annualized minus trading cost (long-only net)

What to look for
----------------
  - If low_vol net_top_ann > xueqiu net_top_ann, the pivot direction is real.
  - If IC sign flips vs raw returns, winsorization or universe is probably off.
  - Turnover gap is where the structural cost advantage lives.
""")


if __name__ == "__main__":
    main()
