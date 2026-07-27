"""
MAX Factor vs. Low-Vol Baseline — IC + Cost-Aware Comparison
============================================================

Mirrors run_v2_factor_ic.py but swaps in the MAX factor. Goal: check whether
-max_20d_return earns non-trivial IC on the broad A-share panel, and how it
compares to the low_vol baseline (IC=0.0335, ICIR=0.171) on a net-of-cost
basis.

Run:
    python research/factors_v2/run_max_factor_ic.py
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors.factor_low_volatility import build_low_volatility_factor
from research.factors.factor_max import build_max_factor
from research.factors_v2.build_broad_panel import build_broad_panel

HOLD_STEP_BDAYS = 12
ROUND_TRIP_BP   = 56
BDAYS_PER_YEAR  = 252
QUINTILE_FRAC   = 0.20


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


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


def _quintile_analysis(
    panel: pd.DataFrame,
    factor_col: str,
    ret_col: str = "fwd_ret_2w",
    q: float = QUINTILE_FRAC,
    hold_step: int = HOLD_STEP_BDAYS,
) -> dict:
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    if sub.empty:
        return {}

    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]
    if len(rebal_dates) < 3:
        return {}

    top_rets = []
    bot_rets = []
    spreads  = []
    turnovers = []
    prev_top = None

    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:
            continue
        hi = g[factor_col].quantile(1 - q)
        lo = g[factor_col].quantile(q)
        top = g[g[factor_col] >= hi]
        bot = g[g[factor_col] <= lo]
        if top.empty or bot.empty:
            continue

        top_ret = float(top[ret_col].mean())
        bot_ret = float(bot[ret_col].mean())
        top_rets.append(top_ret)
        bot_rets.append(bot_ret)
        spreads.append(top_ret - bot_ret)

        top_set = set(top["stock_symbol"].tolist())
        if prev_top is not None and prev_top:
            churn = len(top_set - prev_top) / max(len(top_set), 1)
            turnovers.append(churn)
        prev_top = top_set

    if not spreads:
        return {}

    periods_per_year = BDAYS_PER_YEAR / hold_step
    mean_top    = float(np.mean(top_rets))
    mean_bot    = float(np.mean(bot_rets))
    mean_spread = float(np.mean(spreads))
    turnover    = float(np.mean(turnovers)) if turnovers else np.nan

    ann_top    = (1 + mean_top)    ** periods_per_year - 1
    ann_bot    = (1 + mean_bot)    ** periods_per_year - 1
    ann_spread = (1 + mean_spread) ** periods_per_year - 1

    ann_cost = (
        turnover * periods_per_year * (ROUND_TRIP_BP / 1e4)
        if not np.isnan(turnover) else np.nan
    )
    net_top_ann = ann_top - ann_cost if not np.isnan(ann_cost) else np.nan

    return {
        "top_ann_ret":  ann_top,
        "bot_ann_ret":  ann_bot,
        "spread_ann":   ann_spread,
        "turnover":     turnover,
        "ann_cost":     ann_cost,
        "net_top_ann":  net_top_ann,
        "n_periods":    len(spreads),
    }


def _attach_factor(panel: pd.DataFrame, factor_df: pd.DataFrame, raw_col: str, z_col: str) -> pd.DataFrame:
    f = factor_df.rename(columns={"factor_raw": raw_col, "factor_z": z_col})
    f = f[["date", "stock_symbol", raw_col, z_col]]
    out = panel.merge(f, on=["date", "stock_symbol"], how="left")
    # Re-z within broad tradable universe (so the z-score uses the same
    # cross-section as the panel, not the factor builder's wider universe)
    out[z_col] = out.groupby("date")[raw_col].transform(_zscore)
    return out


def main():
    print("Loading broad panel (all liquid A-shares) ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    print(f"  broad panel: {len(panel):,} rows, "
          f"{panel['stock_symbol'].nunique()} stocks, "
          f"{panel['date'].nunique()} dates", flush=True)

    stock_dir = os.path.join(ROOT, "data", "stock_data")
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")

    print("Building low_volatility factor ...", flush=True)
    lv = build_low_volatility_factor(stock_dir, start_date=start, end_date=end)
    panel = _attach_factor(panel, lv, "lv_raw", "lv_z")

    print("Building MAX factor ...", flush=True)
    mx = build_max_factor(stock_dir, start_date=start, end_date=end)
    panel = _attach_factor(panel, mx, "max_raw", "max_z")

    factors = {
        "low_volatility": "lv_z",
        "MAX (lottery rev)": "max_z",
    }

    rows = []
    print("\n" + "=" * 94)
    print(f"{'factor':<20s} {'IC':>8s} {'ICIR':>7s} {'hit%':>6s} "
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
        print(f"{label:<20s} "
              f"{row['IC']:>8.4f} "
              f"{row['ICIR']:>7.3f} "
              f"{row['hit_pct']:>5.1f}% "
              f"{row['turnover']:>7.1%} "
              f"{row['ann_cost']:>9.2%} "
              f"{row['spread_ann']:>10.2%} "
              f"{row['net_top_ann']:>11.2%}")

    # Correlation between the two factors at the cross-sectional level,
    # so we know whether MAX adds orthogonal information or just echoes low_vol.
    print("\nCross-factor correlation (mean per-date Spearman):")
    corr_by_date = panel.dropna(subset=["lv_z", "max_z"]).groupby("date").apply(
        lambda g: g["lv_z"].corr(g["max_z"], method="spearman")
    ).dropna()
    print(f"  mean rank-corr(lv_z, max_z) = {corr_by_date.mean():+.3f}")
    print(f"  std of per-date rank-corr  = {corr_by_date.std():.3f}")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "max_factor_ic.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
