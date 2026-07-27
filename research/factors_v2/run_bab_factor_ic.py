"""
BAB Factor — IC + Buffered Backtest vs. low_vol baseline
=========================================================

Tests whether Betting-Against-Beta:
  1. Has independent IC from low_vol (cross-factor correlation < 0.59 achieved by MAX)
  2. Improves MDD when stacked with low_vol (the key failure point of MAX stack)

Run:
    python research/factors_v2/run_bab_factor_ic.py
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors.factor_bab import build_bab_factor
from research.factors.factor_low_volatility import build_low_volatility_factor
from research.factors_v2.build_broad_panel import build_broad_panel

ROUND_TRIP_BP  = 56
BDAYS_PER_YEAR = 252
HOLD_STEP      = 12
ENTER_Q        = 0.80


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _ic_by_date(panel, factor_col, ret_col="fwd_ret_2w"):
    sub = panel.dropna(subset=[factor_col, ret_col])
    return sub.groupby("date").apply(
        lambda g: g[factor_col].corr(g[ret_col]) if len(g) >= 10 else np.nan
    ).dropna()


def _ic_summary(ics):
    if ics.empty:
        return {"IC": np.nan, "ICIR": np.nan, "hit_rate": np.nan, "n_dates": 0}
    ic = float(ics.mean())
    return {
        "IC": ic,
        "ICIR": float(ic / ics.std()) if ics.std() > 0 else np.nan,
        "hit_rate": float((ics > 0).mean() * 100),
        "n_dates": int(len(ics)),
    }


def _add_hold_return(panel, hold_step):
    col = f"hold_ret_{hold_step}"
    if col in panel.columns:
        return panel
    out = panel.sort_values(["stock_symbol", "date"]).copy()
    out[col] = out.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-hold_step) / s - 1.0
    )
    return out


def _cagr(rets, ppy):
    r = np.clip(np.asarray(rets, dtype=float), -0.99, None)
    if len(r) == 0:
        return np.nan
    cum = float(np.prod(1.0 + r))
    return cum ** (1.0 / (len(r) / ppy)) - 1.0 if cum > 0 else -1.0


def _mdd(equity):
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())


def _buffered_backtest(panel, factor_col, hold_step, enter_q, keep_q):
    ret_col = f"hold_ret_{hold_step}"
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    if sub.empty:
        return {}
    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")
    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]

    records = []
    prev_hold = None
    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:
            continue
        entrants_all = g[g["rank_pct"] >= enter_q]
        target_k = len(entrants_all)
        if target_k == 0:
            continue
        keep_set = (set(g[(g["rank_pct"] >= keep_q) & g["stock_symbol"].isin(prev_hold)]["stock_symbol"])
                    if prev_hold else set())
        entrants = (entrants_all[~entrants_all["stock_symbol"].isin(keep_set)]
                    .sort_values("rank_pct", ascending=False))
        new_set  = set(entrants.head(max(0, target_k - len(keep_set)))["stock_symbol"])
        holdings = keep_set | new_set
        if not holdings:
            continue
        period_ret = float(g[g["stock_symbol"].isin(holdings)][ret_col].mean())
        churn = (len(holdings - prev_hold) / max(len(holdings), 1)) if prev_hold else 0.0
        net_ret = period_ret - churn * (ROUND_TRIP_BP / 1e4)
        records.append({"date": d, "year": d.year, "gross_ret": period_ret,
                        "net_ret": net_ret, "churn": churn})
        prev_hold = holdings

    if not records:
        return {}
    df = pd.DataFrame(records)
    ppy = BDAYS_PER_YEAR / hold_step
    eq  = (1 + df["net_ret"]).cumprod()
    ann_net  = _cagr(df["net_ret"].tolist(), ppy)
    mdd_net  = _mdd(eq)
    turnover = float(df["churn"].mean())
    by_year  = df.groupby("year")["gross_ret"].apply(lambda r: _cagr(r.tolist(), ppy))
    return {
        "ann_net":  ann_net,
        "mdd_net":  mdd_net,
        "calmar":   ann_net / abs(mdd_net) if mdd_net < 0 else np.nan,
        "turnover": turnover,
        "ann_cost": turnover * ppy * ROUND_TRIP_BP / 1e4,
        "by_year":  by_year,
    }


def main():
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = _add_hold_return(panel, HOLD_STEP)

    stock_dir  = os.path.join(ROOT, "data", "stock_data")
    hs300_path = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")

    print("Building low_vol factor ...", flush=True)
    lv = build_low_volatility_factor(stock_dir, start_date=start, end_date=end)
    lv = lv.rename(columns={"factor_raw": "lv_raw"})[["date", "stock_symbol", "lv_raw"]]
    panel = panel.merge(lv, on=["date", "stock_symbol"], how="left")
    panel["lv_z"] = panel.groupby("date")["lv_raw"].transform(_zscore)

    print("Building BAB factor ...", flush=True)
    bab = build_bab_factor(stock_dir, hs300_path, start_date=start, end_date=end)
    bab = bab.rename(columns={"factor_raw": "bab_raw"})[["date", "stock_symbol", "bab_raw"]]
    panel = panel.merge(bab, on=["date", "stock_symbol"], how="left")
    panel["bab_z"] = panel.groupby("date")["bab_raw"].transform(_zscore)

    # Stack
    panel["stack_z"] = 0.5 * panel["lv_z"].fillna(0) + 0.5 * panel["bab_z"].fillna(0)
    panel["stack_z"] = panel.groupby("date")["stack_z"].transform(_zscore)

    # ── IC table ──────────────────────────────────────────────────────── #
    print("\n" + "=" * 88)
    print(f"{'factor':<20s} {'IC':>8s} {'ICIR':>7s} {'hit%':>6s} {'n_dates':>8s}")
    print("-" * 88)
    ic_rows = []
    for label, col in [("low_vol", "lv_z"), ("BAB", "bab_z"), ("stack lv+bab", "stack_z")]:
        ics = _ic_by_date(panel, col)
        s   = _ic_summary(ics)
        ic_rows.append({"factor": label, **s})
        print(f"{label:<20s} {s['IC']:>8.4f} {s['ICIR']:>7.3f} {s['hit_rate']:>5.1f}% {s['n_dates']:>8d}")

    # ── Cross-factor correlations ─────────────────────────────────────── #
    print("\nCross-factor Spearman correlations (mean per-date):")
    for a, b, la, lb in [("lv_z", "bab_z", "low_vol", "BAB"),
                          ("lv_z", "stack_z", "low_vol", "stack")]:
        c = (panel.dropna(subset=[a, b])
             .groupby("date")
             .apply(lambda g: g[a].corr(g[b], method="spearman"))
             .dropna())
        print(f"  corr({la:10s}, {lb:10s}) = {c.mean():+.3f}  (std {c.std():.3f})")

    # ── Buffered backtest: best configs ───────────────────────────────── #
    configs = [
        ("low_vol only  keep_q=0.70", "lv_z",    0.70),
        ("BAB only      keep_q=0.70", "bab_z",   0.70),
        ("BAB only      keep_q=0.60", "bab_z",   0.60),
        ("STACK lv+bab  keep_q=0.70", "stack_z", 0.70),
        ("STACK lv+bab  keep_q=0.60", "stack_z", 0.60),
    ]

    results = {}
    for label, col, kq in configs:
        print(f"\nRunning backtest: {label} ...", flush=True)
        r = _buffered_backtest(panel, col, HOLD_STEP, ENTER_Q, kq)
        results[label] = r

    print(f"\n\n{'='*72}")
    print(f"{'Config':<32s} {'CAGR_net':>9s} {'MDD':>9s} {'Calmar':>7s} {'turn/p':>7s}")
    print("-" * 72)
    for label, r in results.items():
        print(f"{label:<32s} {r['ann_net']:>+8.2%} {r['mdd_net']:>8.2%} "
              f"{r['calmar']:>6.3f} {r['turnover']:>6.1%}")

    # ── Per-year breakdown for best BAB stack config ──────────────────── #
    best_label = "STACK lv+bab  keep_q=0.70"
    print(f"\nPer-year gross returns — {best_label}:")
    for yr, ret in results[best_label]["by_year"].items():
        bar  = "█" * max(0, int(abs(ret) * 100 / 3))
        sign = "+" if ret >= 0 else ""
        print(f"  {yr}: {sign}{ret:.1%}  {bar}")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    summary = [{"config": k, "ann_net": v["ann_net"], "mdd_net": v["mdd_net"],
                "calmar": v["calmar"], "turnover": v["turnover"], "ann_cost": v["ann_cost"]}
               for k, v in results.items()]
    pd.DataFrame(summary).to_csv(
        os.path.join(out_dir, "bab_factor_ic.csv"), index=False, encoding="utf-8-sig"
    )
    print(f"\nSaved → {out_dir}/bab_factor_ic.csv")


if __name__ == "__main__":
    main()
