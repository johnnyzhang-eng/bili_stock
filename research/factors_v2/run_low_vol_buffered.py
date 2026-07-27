"""
Low-Volatility with Buffered Rebalancing
========================================

Turnover grid showed longer hold_step loses more alpha than it saves
in cost. Test a different lever: buffered rebalancing (hysteresis).

Idea: a stock enters the portfolio when its rank percentile >= enter_q,
but only leaves when it drops below keep_q (keep_q < enter_q). Same
top-quintile target but holdings stickier → lower turnover, same alpha.

Parametrization (all on w=60, hs=12):
  enter_q = 0.80 (top 20%)
  keep_q  ∈ {0.80, 0.70, 0.60, 0.50}    keep_q=0.80 ≡ baseline (no buffer)

Run:
    python research/factors_v2/run_low_vol_buffered.py
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
VOL_WINDOW     = 60
HOLD_STEP      = 12
ENTER_Q        = 0.80


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _add_hold_return(panel: pd.DataFrame, hold_step: int) -> pd.DataFrame:
    col = f"hold_ret_{hold_step}"
    if col in panel.columns:
        return panel
    out = panel.sort_values(["stock_symbol", "date"]).copy()
    out[col] = out.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-hold_step) / s - 1.0
    )
    return out


def _cagr(rets: list[float], periods_per_year: float) -> float:
    r = np.clip(np.asarray(rets, dtype=float), -0.99, None)
    if len(r) == 0:
        return np.nan
    cum = float(np.prod(1.0 + r))
    if cum <= 0:
        return -1.0
    years = len(r) / periods_per_year
    return cum ** (1.0 / years) - 1.0


def _buffered_backtest(
    panel: pd.DataFrame,
    factor_col: str,
    hold_step: int,
    enter_q: float,
    keep_q: float,
) -> dict:
    """
    Buffered top-quintile portfolio.

    At each rebalance date d:
      - Compute per-date percentile rank of factor (high = good).
      - keep  = previous holdings that still have rank >= keep_q
      - entrants = stocks outside keep whose rank >= enter_q
      - holdings = keep ∪ entrants, capped at original target size
        (target size = count of stocks with rank >= enter_q at d)
      - Return of the holdings over [d, d+hold_step] is the period return.
    """
    ret_col = f"hold_ret_{hold_step}"
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    if sub.empty:
        return {}

    # Pre-compute rank percentile per date per factor (once).
    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")

    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]
    if len(rebal_dates) < 3:
        return {}

    hold_rets = []
    turns     = []
    bot_rets  = []
    prev_hold: set | None = None

    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:
            continue

        entrants_all = g[g["rank_pct"] >= enter_q]
        target_k = len(entrants_all)
        if target_k == 0:
            continue

        # Start with previous holdings that still pass keep threshold
        if prev_hold is not None:
            keep_set = set(g[
                (g["rank_pct"] >= keep_q) & g["stock_symbol"].isin(prev_hold)
            ]["stock_symbol"])
        else:
            keep_set = set()

        # Fill rest with best new entrants not in keep
        entrants = entrants_all[~entrants_all["stock_symbol"].isin(keep_set)]
        entrants = entrants.sort_values("rank_pct", ascending=False)
        need = max(0, target_k - len(keep_set))
        new_set = set(entrants.head(need)["stock_symbol"])

        holdings = keep_set | new_set
        if len(holdings) == 0:
            continue

        hold_df = g[g["stock_symbol"].isin(holdings)]
        hold_rets.append(float(hold_df[ret_col].mean()))

        # bottom quintile for reference spread (static definition)
        bot_df = g[g["rank_pct"] <= (1 - enter_q)]
        if not bot_df.empty:
            bot_rets.append(float(bot_df[ret_col].mean()))

        if prev_hold is not None:
            churn = len(holdings - prev_hold) / max(len(holdings), 1)
            turns.append(churn)
        prev_hold = holdings

    if not hold_rets:
        return {}

    periods_per_year = BDAYS_PER_YEAR / hold_step
    turnover = float(np.mean(turns)) if turns else np.nan

    ann_top = _cagr(hold_rets, periods_per_year)
    ann_bot = _cagr(bot_rets, periods_per_year) if bot_rets else np.nan
    ann_spread = ((1 + ann_top) / (1 + ann_bot) - 1.0
                  if not (np.isnan(ann_top) or np.isnan(ann_bot)) else np.nan)
    ann_cost = (turnover * periods_per_year * ROUND_TRIP_BP / 1e4
                if not np.isnan(turnover) else np.nan)
    net_top  = ann_top - ann_cost if not np.isnan(ann_cost) else np.nan

    return {
        "turnover":   turnover,
        "ann_cost":   ann_cost,
        "spread_ann": ann_spread,
        "top_ann":    ann_top,
        "net_top":    net_top,
        "n_periods":  len(hold_rets),
    }


def main():
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = _add_hold_return(panel, HOLD_STEP)
    print(f"  panel: {len(panel):,} rows")

    print(f"Building low_vol factor (window={VOL_WINDOW}) ...", flush=True)
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")
    lv = build_low_volatility_factor(
        stock_dir, start_date=start, end_date=end,
        window=VOL_WINDOW, min_periods=max(20, VOL_WINDOW // 3),
    )
    lv = lv.rename(columns={"factor_raw": "lv_raw"})[["date", "stock_symbol", "lv_raw"]]
    panel = panel.merge(lv, on=["date", "stock_symbol"], how="left")
    panel["lv_z"] = panel.groupby("date")["lv_raw"].transform(_zscore)

    rows = []
    print("\n" + "=" * 82)
    print(f"enter_q={ENTER_Q}, hold_step={HOLD_STEP}, window={VOL_WINDOW}")
    print(f"{'keep_q':>7s} | {'turn/p':>7s} {'ann_cost':>9s} {'spread_ann':>11s} "
          f"{'top_ann':>9s} {'net_top':>9s} {'Δnet':>7s}")
    print("-" * 82)
    baseline_net = None
    for keep_q in [0.80, 0.70, 0.60, 0.50]:
        r = _buffered_backtest(panel, "lv_z", HOLD_STEP, enter_q=ENTER_Q, keep_q=keep_q)
        if baseline_net is None:
            baseline_net = r["net_top"]
        delta = r["net_top"] - baseline_net
        note = "  ≡ baseline" if keep_q == ENTER_Q else ""
        rows.append({"keep_q": keep_q, **r, "delta_vs_baseline": delta})
        print(f"{keep_q:>7.2f} | "
              f"{r['turnover']:>6.1%} {r['ann_cost']:>8.2%} {r['spread_ann']:>10.2%} "
              f"{r['top_ann']:>8.2%} {r['net_top']:>8.2%} {delta*100:>+6.2f}pp{note}")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "low_vol_buffered.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
