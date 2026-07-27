"""
Low-Volatility Turnover Optimization — Grid Search
==================================================

Baseline from `run_v2_factor_ic.py`:
  window=60, hold_step=12 → turnover 35.8%, ann_cost 4.20%, net_top_ann 5.37%

Hypothesis: low-vol's 35.8% per-period churn is spurious — stocks cluster
near the top-quintile cutoff, tiny vol changes flip ranks. Longer vol
window smooths the signal; longer hold_step compounds fewer cost periods.

Grid: window ∈ {60, 120, 250} × hold_step ∈ {12, 30, 60}.

Key correctness fix vs v1 runner: compute hold-period return from actual
close prices at (d, d+hold_step), not the fixed 10-bday `fwd_ret_2w`.
`fwd_ret_2w` understates returns for hold_step > 10 and inflates
annualization factor. Required close in panel (broad panel has it).

Run:
    python research/factors_v2/run_low_vol_turnover_grid.py
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


ROUND_TRIP_BP  = 56
BDAYS_PER_YEAR = 252
QUINTILE_FRAC  = 0.20


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


# --------------------------------------------------------------------------- #
# Hold-period return, computed from close prices (not fixed fwd_ret_2w)
# --------------------------------------------------------------------------- #
def _add_hold_return(panel: pd.DataFrame, hold_step: int) -> pd.DataFrame:
    """Attach hold_ret_{hold_step} = close.shift(-hold_step)/close - 1 per stock."""
    col = f"hold_ret_{hold_step}"
    if col in panel.columns:
        return panel
    out = panel.sort_values(["stock_symbol", "date"]).copy()
    out[col] = out.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-hold_step) / s - 1.0
    )
    return out


# --------------------------------------------------------------------------- #
# IC & ICIR (rank corr of factor_z with hold_ret; stable across hold_step
# because we recompute hold_ret to match).
# --------------------------------------------------------------------------- #
def _ic_by_date(panel: pd.DataFrame, factor_col: str, ret_col: str) -> pd.Series:
    sub = panel.dropna(subset=[factor_col, ret_col])
    ics = sub.groupby("date").apply(
        lambda g: g[factor_col].corr(g[ret_col]) if len(g) >= 30 else np.nan
    )
    return ics.dropna()


# --------------------------------------------------------------------------- #
# Quintile analysis with correct hold-period return
# --------------------------------------------------------------------------- #
def _quintile_analysis(
    panel: pd.DataFrame,
    factor_col: str,
    hold_step: int,
    q: float = QUINTILE_FRAC,
) -> dict:
    ret_col = f"hold_ret_{hold_step}"
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    if sub.empty:
        return {}

    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]
    if len(rebal_dates) < 3:
        return {}

    top_rets, bot_rets, spreads, turns = [], [], [], []
    prev_top: set | None = None

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

        top_rets.append(float(top[ret_col].mean()))
        bot_rets.append(float(bot[ret_col].mean()))
        spreads.append(top_rets[-1] - bot_rets[-1])

        top_set = set(top["stock_symbol"])
        if prev_top is not None and prev_top:
            turns.append(len(top_set - prev_top) / max(len(top_set), 1))
        prev_top = top_set

    if not spreads:
        return {}

    periods_per_year = BDAYS_PER_YEAR / hold_step
    turnover = float(np.mean(turns)) if turns else np.nan

    # CAGR-style annualization: compound the actual per-period returns, then
    # take the n-th root. (1+mean)^n is naively inflated by volatility drag —
    # for volatile factors that bias matters (≈ turns 10-12%/yr into 23%/yr).
    def _cagr(rets: list[float]) -> float:
        r = np.asarray(rets, dtype=float)
        if len(r) == 0:
            return np.nan
        # floor at -99% to avoid blow-ups from a single catastrophic period
        r = np.clip(r, -0.99, None)
        cum = float(np.prod(1.0 + r))
        if cum <= 0:
            return -1.0
        years = len(r) / periods_per_year
        return cum ** (1.0 / years) - 1.0

    ann_top    = _cagr(top_rets)
    ann_bot    = _cagr(bot_rets)
    # Spread as geometric: (1+top)/(1+bot) per-period, compounded.
    ann_spread = ((1 + ann_top) / (1 + ann_bot) - 1.0) if not (np.isnan(ann_top) or np.isnan(ann_bot)) else np.nan

    ann_cost   = (turnover * periods_per_year * ROUND_TRIP_BP / 1e4
                  if not np.isnan(turnover) else np.nan)
    net_top    = ann_top - ann_cost if not np.isnan(ann_cost) else np.nan

    return {
        "top_ann":    ann_top,
        "spread_ann": ann_spread,
        "turnover":   turnover,
        "ann_cost":   ann_cost,
        "net_top":    net_top,
        "n_periods":  len(spreads),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
WINDOWS    = [60, 120, 250]
HOLD_STEPS = [12, 30, 60]


def main():
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    print(f"  panel: {len(panel):,} rows, "
          f"{panel['stock_symbol'].nunique()} stocks")

    # Pre-compute hold returns for each hold_step (once, cached on panel).
    for hs in HOLD_STEPS:
        panel = _add_hold_return(panel, hs)

    stock_dir = os.path.join(ROOT, "data", "stock_data")
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")

    rows = []
    for w in WINDOWS:
        print(f"\n[window={w}] building factor ...", flush=True)
        lv = build_low_volatility_factor(
            stock_dir, start_date=start, end_date=end,
            window=w, min_periods=max(20, w // 3),
        )
        col_raw = f"lv_raw_w{w}"
        col_z   = f"lv_z_w{w}"
        lv = lv.rename(columns={"factor_raw": col_raw, "factor_z": "_drop_"})
        lv = lv[["date", "stock_symbol", col_raw]]
        # Merge into panel; re-z on broad tradable universe
        panel_w = panel.merge(lv, on=["date", "stock_symbol"], how="left")
        panel_w[col_z] = panel_w.groupby("date")[col_raw].transform(_zscore)

        for hs in HOLD_STEPS:
            ret_col = f"hold_ret_{hs}"
            ics = _ic_by_date(panel_w, col_z, ret_col)
            ic_mean = float(ics.mean()) if not ics.empty else np.nan
            icir    = float(ics.mean() / ics.std()) if len(ics) > 1 and ics.std() > 0 else np.nan
            hit_pct = float((ics > 0).mean() * 100) if len(ics) > 0 else np.nan

            q_stats = _quintile_analysis(panel_w, col_z, hs)
            rows.append({
                "window":     w,
                "hold_step":  hs,
                "IC":         ic_mean,
                "ICIR":       icir,
                "hit_pct":    hit_pct,
                "turnover":   q_stats.get("turnover", np.nan),
                "ann_cost":   q_stats.get("ann_cost", np.nan),
                "spread_ann": q_stats.get("spread_ann", np.nan),
                "top_ann":    q_stats.get("top_ann", np.nan),
                "net_top":    q_stats.get("net_top", np.nan),
                "n_periods":  q_stats.get("n_periods", 0),
            })

    # Report
    df = pd.DataFrame(rows)
    print("\n" + "=" * 98)
    print(f"{'window':>7s} {'hold':>5s} | "
          f"{'IC':>7s} {'ICIR':>6s} {'hit%':>5s} | "
          f"{'turn/p':>7s} {'ann_cost':>9s} {'spread_ann':>11s} {'top_ann':>9s} {'net_top':>9s}")
    print("-" * 98)
    for _, r in df.iterrows():
        print(f"{int(r['window']):>7d} {int(r['hold_step']):>5d} | "
              f"{r['IC']:>7.4f} {r['ICIR']:>6.3f} {r['hit_pct']:>4.1f}% | "
              f"{r['turnover']:>6.1%} {r['ann_cost']:>8.2%} {r['spread_ann']:>10.2%} "
              f"{r['top_ann']:>8.2%} {r['net_top']:>8.2%}")

    # Best by net_top
    best = df.loc[df["net_top"].idxmax()]
    print("\nBest config by net_top:")
    print(f"  window={int(best['window'])}, hold_step={int(best['hold_step'])}")
    print(f"  net_top_ann={best['net_top']:.2%}  "
          f"(spread_ann={best['spread_ann']:.2%}, "
          f"turnover={best['turnover']:.1%}, cost={best['ann_cost']:.2%})")

    # Also compare vs the previous baseline (w=60, hs=12)
    base = df[(df["window"] == 60) & (df["hold_step"] == 12)].iloc[0]
    delta_net = best["net_top"] - base["net_top"]
    print(f"  Δ net_top vs baseline (w=60,hs=12): "
          f"{delta_net*100:+.2f}pp  ({base['net_top']:.2%} → {best['net_top']:.2%})")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "low_vol_turnover_grid.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
