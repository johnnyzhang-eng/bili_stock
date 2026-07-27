"""
Low-Vol + MAX Stack — Combined Factor Backtest
===============================================

Cross-factor correlation = +0.592, meaning ~41% of MAX's information is
orthogonal to low_vol. This runner tests whether combining them as a simple
equal-weight z-score stack improves net_top AND MDD vs. low_vol alone.

Stack: stack_z = 0.5 * lv_z + 0.5 * max_z  (both cross-sectionally z-scored)

Also reports per-year returns so we can see if 2018-type drawdown improves.

Run:
    python research/factors_v2/run_lv_max_stack.py
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

ROUND_TRIP_BP  = 56
BDAYS_PER_YEAR = 252
HOLD_STEP      = 12
ENTER_Q        = 0.80
KEEP_Q         = 0.70   # low_vol sweet spot; stack may differ but start here


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


def _cagr(rets: list, periods_per_year: float) -> float:
    r = np.clip(np.asarray(rets, dtype=float), -0.99, None)
    if len(r) == 0:
        return np.nan
    cum = float(np.prod(1.0 + r))
    if cum <= 0:
        return -1.0
    return cum ** (1.0 / (len(r) / periods_per_year)) - 1.0


def _mdd(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min())


def _buffered_backtest_full(
    panel: pd.DataFrame,
    factor_col: str,
    hold_step: int,
    enter_q: float,
    keep_q: float,
) -> dict:
    """Full backtest: returns per-period returns + equity curve for MDD."""
    ret_col = f"hold_ret_{hold_step}"
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    if sub.empty:
        return {}

    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")
    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]

    records = []   # (date, period_ret)
    prev_hold = None

    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:
            continue

        entrants_all = g[g["rank_pct"] >= enter_q]
        target_k = len(entrants_all)
        if target_k == 0:
            continue

        if prev_hold is not None:
            keep_set = set(g[
                (g["rank_pct"] >= keep_q) & g["stock_symbol"].isin(prev_hold)
            ]["stock_symbol"])
        else:
            keep_set = set()

        entrants = entrants_all[~entrants_all["stock_symbol"].isin(keep_set)]
        entrants = entrants.sort_values("rank_pct", ascending=False)
        new_set  = set(entrants.head(max(0, target_k - len(keep_set)))["stock_symbol"])
        holdings = keep_set | new_set
        if not holdings:
            continue

        hold_df = g[g["stock_symbol"].isin(holdings)]
        period_ret = float(hold_df[ret_col].mean())

        if prev_hold is not None:
            churn = len(holdings - prev_hold) / max(len(holdings), 1)
        else:
            churn = 0.0
        cost = churn * (ROUND_TRIP_BP / 1e4)
        net_ret = period_ret - cost

        records.append({"date": d, "gross_ret": period_ret, "net_ret": net_ret,
                         "n_hold": len(holdings), "churn": churn})
        prev_hold = holdings

    if not records:
        return {}

    df = pd.DataFrame(records)
    df["year"] = pd.to_datetime(df["date"]).dt.year
    ppy = BDAYS_PER_YEAR / hold_step

    equity_gross = (1 + df["gross_ret"]).cumprod()
    equity_net   = (1 + df["net_ret"]).cumprod()

    ann_gross = _cagr(df["gross_ret"].tolist(), ppy)
    ann_net   = _cagr(df["net_ret"].tolist(), ppy)
    mdd_net   = _mdd(equity_net)
    calmar    = ann_net / abs(mdd_net) if mdd_net < 0 else np.nan
    turnover  = float(df["churn"].mean())
    ann_cost  = turnover * ppy * (ROUND_TRIP_BP / 1e4)

    by_year = df.groupby("year")["gross_ret"].apply(
        lambda r: _cagr(r.tolist(), ppy)
    )

    return {
        "ann_gross": ann_gross,
        "ann_net":   ann_net,
        "mdd_net":   mdd_net,
        "calmar":    calmar,
        "turnover":  turnover,
        "ann_cost":  ann_cost,
        "by_year":   by_year,
        "n_periods": len(df),
    }


def _print_result(label: str, r: dict) -> None:
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(f"  CAGR_gross : {r['ann_gross']:+.2%}")
    print(f"  CAGR_net   : {r['ann_net']:+.2%}   ← main number")
    print(f"  MDD_net    : {r['mdd_net']:+.2%}")
    print(f"  Calmar     : {r['calmar']:.3f}")
    print(f"  Turnover/p : {r['turnover']:.1%}  (ann_cost {r['ann_cost']:.2%})")
    print(f"  Periods    : {r['n_periods']}")
    print(f"\n  Annual gross returns:")
    for yr, ret in r["by_year"].items():
        bar = "█" * int(abs(ret) * 100 / 3)
        sign = "+" if ret >= 0 else ""
        print(f"    {yr}: {sign}{ret:.1%}  {bar}")


def main():
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = _add_hold_return(panel, HOLD_STEP)

    stock_dir = os.path.join(ROOT, "data", "stock_data")
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")

    print("Building low_vol factor ...", flush=True)
    lv = build_low_volatility_factor(stock_dir, start_date=start, end_date=end)
    lv = lv.rename(columns={"factor_raw": "lv_raw"})[["date", "stock_symbol", "lv_raw"]]
    panel = panel.merge(lv, on=["date", "stock_symbol"], how="left")
    panel["lv_z"] = panel.groupby("date")["lv_raw"].transform(_zscore)

    print("Building MAX factor ...", flush=True)
    mx = build_max_factor(stock_dir, start_date=start, end_date=end, window=20)
    mx = mx.rename(columns={"factor_raw": "max_raw"})[["date", "stock_symbol", "max_raw"]]
    panel = panel.merge(mx, on=["date", "stock_symbol"], how="left")
    panel["max_z"] = panel.groupby("date")["max_raw"].transform(_zscore)

    # Equal-weight stack
    panel["stack_z"] = 0.5 * panel["lv_z"].fillna(0) + 0.5 * panel["max_z"].fillna(0)
    # Re-z so the combined score is on the same scale
    panel["stack_z"] = panel.groupby("date")["stack_z"].transform(_zscore)

    configs = [
        ("low_vol only  (keep_q=0.70)", "lv_z",    0.70),
        ("MAX only      (keep_q=0.60)", "max_z",   0.60),
        ("STACK lv+max  (keep_q=0.70)", "stack_z", 0.70),
        ("STACK lv+max  (keep_q=0.60)", "stack_z", 0.60),
    ]

    results = {}
    for label, col, kq in configs:
        print(f"\nRunning: {label} ...", flush=True)
        r = _buffered_backtest_full(panel, col, HOLD_STEP, ENTER_Q, kq)
        results[label] = r
        _print_result(label, r)

    # Summary table
    print(f"\n\n{'='*72}")
    print(f"{'Config':<32s} {'CAGR_net':>9s} {'MDD':>9s} {'Calmar':>7s} {'turn/p':>7s}")
    print("-" * 72)
    for label, r in results.items():
        print(f"{label:<32s} {r['ann_net']:>+8.2%} {r['mdd_net']:>8.2%} "
              f"{r['calmar']:>6.3f} {r['turnover']:>6.1%}")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    summary = [{"config": k, **{x: v[x] for x in ["ann_gross","ann_net","mdd_net","calmar","turnover","ann_cost","n_periods"]}}
               for k, v in results.items()]
    pd.DataFrame(summary).to_csv(
        os.path.join(out_dir, "lv_max_stack.csv"), index=False, encoding="utf-8-sig"
    )
    print(f"\nSaved → {out_dir}/lv_max_stack.csv")


if __name__ == "__main__":
    main()
