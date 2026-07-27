"""
Short-Term Reversal — IC + Backtest vs. low_vol baseline
==========================================================

Two key tests:
1. IC over 5-day AND 10-day forward return — reversal decays fast, the
   standard fwd_ret_2w (10 bday) window may miss the signal.
2. Buffered backtest with hold_step=5 (1 week) vs hold_step=12 (2 weeks)
   — reversal needs faster rebalancing to capture the alpha before it decays.
3. Stack low_vol + reversal — does orthogonal timing cycle reduce MDD?

Run:
    python research/factors_v2/run_reversal_ic.py
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors.factor_low_volatility import build_low_volatility_factor
from research.factors.factor_reversal import build_reversal_factor
from research.factors_v2.build_broad_panel import build_broad_panel

ROUND_TRIP_BP  = 56
BDAYS_PER_YEAR = 252
ENTER_Q        = 0.80


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _add_fwd_return(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    col = f"fwd_ret_{horizon}d"
    if col in panel.columns:
        return panel
    out = panel.sort_values(["stock_symbol", "date"]).copy()
    out[col] = out.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-horizon) / s - 1.0
    )
    return out


def _ic_by_date(panel, factor_col, ret_col):
    sub = panel.dropna(subset=[factor_col, ret_col])
    return sub.groupby("date").apply(
        lambda g: g[factor_col].corr(g[ret_col]) if len(g) >= 10 else np.nan
    ).dropna()


def _ic_summary(ics):
    if ics.empty:
        return {"IC": np.nan, "ICIR": np.nan, "hit_rate": np.nan, "n_dates": 0}
    ic = float(ics.mean())
    return {"IC": ic,
            "ICIR": float(ic / ics.std()) if ics.std() > 0 else np.nan,
            "hit_rate": float((ics > 0).mean() * 100),
            "n_dates": int(len(ics))}


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
    ret_col = f"fwd_ret_{hold_step}d"
    if ret_col not in panel.columns:
        return {}
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
        records.append({"date": d, "year": d.year,
                        "gross_ret": period_ret, "net_ret": net_ret, "churn": churn})
        prev_hold = holdings

    if not records:
        return {}
    df = pd.DataFrame(records)
    ppy = BDAYS_PER_YEAR / hold_step
    eq  = (1 + df["net_ret"]).cumprod()
    by_year = df.groupby("year")["gross_ret"].apply(lambda r: _cagr(r.tolist(), ppy))
    turnover = float(df["churn"].mean())
    ann_net  = _cagr(df["net_ret"].tolist(), ppy)
    mdd_net  = _mdd(eq)
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
    # Add both 5-day and 10-day (12-day ≈ 2w) forward returns
    panel = _add_fwd_return(panel, 5)
    panel = _add_fwd_return(panel, 12)
    # fwd_ret_2w from panel is ~10 bdays; also use 12 to match hold_step
    if "fwd_ret_2w" in panel.columns:
        panel["fwd_ret_10d"] = panel["fwd_ret_2w"]

    stock_dir = os.path.join(ROOT, "data", "stock_data")
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")

    print("Building low_vol factor ...", flush=True)
    lv = build_low_volatility_factor(stock_dir, start_date=start, end_date=end)
    lv = lv.rename(columns={"factor_raw": "lv_raw"})[["date", "stock_symbol", "lv_raw"]]
    panel = panel.merge(lv, on=["date", "stock_symbol"], how="left")
    panel["lv_z"] = panel.groupby("date")["lv_raw"].transform(_zscore)

    print("Building reversal factor ...", flush=True)
    rv = build_reversal_factor(stock_dir, start_date=start, end_date=end)
    rv = rv.rename(columns={"factor_raw": "rv_raw"})[["date", "stock_symbol", "rv_raw"]]
    panel = panel.merge(rv, on=["date", "stock_symbol"], how="left")
    panel["rv_z"] = panel.groupby("date")["rv_raw"].transform(_zscore)

    # Stack
    panel["stack_z"] = 0.5 * panel["lv_z"].fillna(0) + 0.5 * panel["rv_z"].fillna(0)
    panel["stack_z"] = panel.groupby("date")["stack_z"].transform(_zscore)

    # ── IC over two horizons ──────────────────────────────────────────── #
    print("\n" + "=" * 80)
    print("IC by forward-return horizon (reversal decays fast — 5d should beat 12d):")
    print(f"{'factor':<20s} {'fwd=5d IC':>10s} {'ICIR':>7s} | {'fwd=12d IC':>11s} {'ICIR':>7s}")
    print("-" * 80)
    for label, col in [("low_vol", "lv_z"), ("reversal", "rv_z"), ("stack", "stack_z")]:
        i5  = _ic_summary(_ic_by_date(panel, col, "fwd_ret_5d"))
        i12 = _ic_summary(_ic_by_date(panel, col, "fwd_ret_12d"))
        print(f"{label:<20s} {i5['IC']:>10.4f} {i5['ICIR']:>7.3f} | "
              f"{i12['IC']:>11.4f} {i12['ICIR']:>7.3f}")

    # ── Cross-factor correlation ──────────────────────────────────────── #
    print("\nCross-factor Spearman correlation (mean per-date):")
    c = (panel.dropna(subset=["lv_z", "rv_z"])
         .groupby("date")
         .apply(lambda g: g["lv_z"].corr(g["rv_z"], method="spearman"))
         .dropna())
    print(f"  corr(low_vol, reversal) = {c.mean():+.3f}  (std {c.std():.3f})")
    print(f"  → MAX had +0.592, BAB had +0.194 — reversal target: <0.20")

    # ── Buffered backtest: hold_step=5 and hold_step=12 ──────────────── #
    configs = [
        ("low_vol   hs=12 kq=0.70", "lv_z",    12, 0.70),
        ("reversal  hs=5  kq=0.80", "rv_z",     5, 0.80),
        ("reversal  hs=5  kq=0.70", "rv_z",     5, 0.70),
        ("reversal  hs=12 kq=0.70", "rv_z",    12, 0.70),
        ("stack     hs=12 kq=0.70", "stack_z", 12, 0.70),
        ("stack     hs=5  kq=0.70", "stack_z",  5, 0.70),
    ]

    results = {}
    for label, col, hs, kq in configs:
        print(f"\nRunning: {label} ...", flush=True)
        r = _buffered_backtest(panel, col, hs, ENTER_Q, kq)
        results[label] = r

    print(f"\n\n{'='*72}")
    print(f"{'Config':<32s} {'CAGR_net':>9s} {'MDD':>9s} {'Calmar':>7s} {'turn/p':>7s}")
    print("-" * 72)
    for label, r in results.items():
        if not r:
            print(f"{label:<32s}  (no result)")
            continue
        print(f"{label:<32s} {r['ann_net']:>+8.2%} {r['mdd_net']:>8.2%} "
              f"{r['calmar']:>6.3f} {r['turnover']:>6.1%}")

    # Per-year for best stack
    best = "stack     hs=12 kq=0.70"
    if results.get(best):
        print(f"\nPer-year gross — {best}:")
        for yr, ret in results[best]["by_year"].items():
            bar  = "█" * max(0, int(abs(ret) * 100 / 3))
            sign = "+" if ret >= 0 else ""
            print(f"  {yr}: {sign}{ret:.1%}  {bar}")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    summary = [{"config": k, **{x: v.get(x) for x in ["ann_net","mdd_net","calmar","turnover","ann_cost"]}}
               for k, v in results.items() if v]
    pd.DataFrame(summary).to_csv(
        os.path.join(out_dir, "reversal_ic.csv"), index=False, encoding="utf-8-sig"
    )
    print(f"\nSaved → {out_dir}/reversal_ic.csv")


if __name__ == "__main__":
    main()
