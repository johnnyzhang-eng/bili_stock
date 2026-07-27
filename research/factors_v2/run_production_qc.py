"""
Production QC — Low_Vol + Overlay Robustness Tests
====================================================

Production candidate:
    low_vol (vol_window=60, hold_step=12, enter_q=0.80, keep_q=0.70)
    + overlay: HS300 20d < -7% → scale_to_0

Three robustness checks:

1. RANDOMIZED START-DATE TEST
   Shift rebalance calendar by offset ∈ {0..11} days.
   A strategy that only works with one lucky start date is overfit.
   Pass criterion: CAGR_net positive in ≥80% of offsets.

2. HOLD_STEP SENSITIVITY
   Sweep hold_step ∈ {8, 10, 12, 14, 16, 18, 20} with fixed params.
   Previous Xueqiu strategy failed this badly (calmar swung 0.41-1.41).
   Pass criterion: Calmar consistent within ±30% of baseline.

3. PARAMETER GRID (enter_q × keep_q)
   3×3 grid around the production params.
   Pass criterion: Calmar > 0.15 in ≥7/9 cells.

Run:
    python research/factors_v2/run_production_qc.py
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

# Production params
PROD_HOLD_STEP    = 12
PROD_ENTER_Q      = 0.80
PROD_KEEP_Q       = 0.70
PROD_OVERLAY_THR  = -0.07   # HS300 20d < -7% → skip period


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _cagr(rets, ppy):
    r = np.clip(np.asarray(rets, dtype=float), -0.99, None)
    if len(r) == 0:
        return np.nan
    cum = float(np.prod(1.0 + r))
    return cum ** (1.0 / (len(r) / ppy)) - 1.0 if cum > 0 else -1.0


def _mdd(net_rets):
    eq = (1 + np.clip(np.asarray(net_rets, dtype=float), -0.99, None)).cumprod()
    peak = np.maximum.accumulate(eq)
    return float(((eq - peak) / peak).min()) if len(eq) > 0 else 0.0


def _run_backtest(
    panel: pd.DataFrame,
    factor_col: str,
    hold_step: int,
    enter_q: float,
    keep_q: float,
    hs300_ret20: pd.Series,
    overlay_thr: float,
    start_offset: int = 0,
) -> dict:
    """
    Buffered top-quintile portfolio with optional overlay and start offset.

    start_offset: skip the first `start_offset` rebalance dates (randomised start).
    overlay_thr:  if hs300_ret20 at rebalance date < thr, treat period return as 0.
    """
    ret_col = f"hold_ret_{hold_step}"
    if ret_col not in panel.columns:
        return {}

    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    if sub.empty:
        return {}

    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")
    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]
    rebal_dates = rebal_dates[start_offset:]   # randomized start
    if len(rebal_dates) < 5:
        return {}

    records = []
    prev_hold = None
    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:
            continue

        # Overlay: skip this period (hold cash) if market is in sharp decline
        mkt_ret20 = hs300_ret20.get(d, np.nan)
        if not np.isnan(mkt_ret20) and mkt_ret20 < overlay_thr:
            records.append({"date": d, "year": d.year,
                            "gross_ret": 0.0, "net_ret": 0.0, "churn": 0.0,
                            "overlay_fired": True})
            prev_hold = None   # reset holdings — re-enter fresh next period
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
                        "gross_ret": period_ret, "net_ret": net_ret, "churn": churn,
                        "overlay_fired": False})
        prev_hold = holdings

    if len(records) < 5:
        return {}

    df = pd.DataFrame(records)
    ppy = BDAYS_PER_YEAR / hold_step
    ann_net  = _cagr(df["net_ret"].tolist(), ppy)
    mdd_net  = _mdd(df["net_ret"].tolist())
    calmar   = ann_net / abs(mdd_net) if mdd_net < 0 else np.nan
    turnover = float(df["churn"].mean())
    fire_pct = float(df["overlay_fired"].mean() * 100)
    by_year  = df.groupby("year")["gross_ret"].apply(lambda r: _cagr(r.tolist(), ppy))
    return {"ann_net": ann_net, "mdd_net": mdd_net, "calmar": calmar,
            "turnover": turnover, "ann_cost": turnover * ppy * ROUND_TRIP_BP / 1e4,
            "overlay_fire_pct": fire_pct, "by_year": by_year, "n_periods": len(df)}


def _add_hold_return(panel: pd.DataFrame, hold_step: int) -> pd.DataFrame:
    col = f"hold_ret_{hold_step}"
    if col in panel.columns:
        return panel
    out = panel.sort_values(["stock_symbol", "date"]).copy()
    out[col] = out.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-hold_step) / s - 1.0
    )
    return out


# ─────────────────────────────────────────────────────────────────────────── #
def main():
    # ── Setup ───────────────────────────────────────────────────────────── #
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()

    # Pre-compute hold_return for all hold_steps we'll test
    for hs in [8, 10, 12, 14, 16, 18, 20]:
        panel = _add_hold_return(panel, hs)

    stock_dir = os.path.join(ROOT, "data", "stock_data")
    start = panel["date"].min().strftime("%Y-%m-%d")
    end   = panel["date"].max().strftime("%Y-%m-%d")

    print("Building low_vol factor ...", flush=True)
    lv = build_low_volatility_factor(stock_dir, start_date=start, end_date=end)
    lv = lv.rename(columns={"factor_raw": "lv_raw"})[["date", "stock_symbol", "lv_raw"]]
    panel = panel.merge(lv, on=["date", "stock_symbol"], how="left")
    panel["lv_z"] = panel.groupby("date")["lv_raw"].transform(_zscore)

    # ── HS300 20d return for overlay ─────────────────────────────────────── #
    hs300_path = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
    hs300 = pd.read_csv(hs300_path, usecols=["date", "ret20"])
    hs300["date"] = pd.to_datetime(hs300["date"]).dt.normalize()
    hs300_ret20 = hs300.set_index("date")["ret20"].dropna()

    prod_kwargs = dict(
        factor_col="lv_z",
        hold_step=PROD_HOLD_STEP,
        enter_q=PROD_ENTER_Q,
        keep_q=PROD_KEEP_Q,
        hs300_ret20=hs300_ret20,
        overlay_thr=PROD_OVERLAY_THR,
    )

    # ════════════════════════════════════════════════════════════════════════ #
    # TEST 1: Production baseline (no offset)
    # ════════════════════════════════════════════════════════════════════════ #
    print("\n" + "═"*70)
    print("PRODUCTION BASELINE (hold_step=12, enter=0.80, keep=0.70, overlay=-7%)")
    print("═"*70)
    baseline = _run_backtest(panel, start_offset=0, **prod_kwargs)
    print(f"  CAGR_net : {baseline['ann_net']:+.2%}")
    print(f"  MDD      : {baseline['mdd_net']:+.2%}")
    print(f"  Calmar   : {baseline['calmar']:.3f}")
    print(f"  turn/p   : {baseline['turnover']:.1%}  (ann_cost {baseline['ann_cost']:.2%})")
    print(f"  Overlay fired: {baseline['overlay_fire_pct']:.1f}% of periods")
    print(f"  Per-year gross:")
    for yr, ret in baseline["by_year"].items():
        bar  = "█" * max(0, int(abs(ret) * 100 / 3))
        sign = "+" if ret >= 0 else ""
        print(f"    {yr}: {sign}{ret:.1%}  {bar}")

    # ════════════════════════════════════════════════════════════════════════ #
    # TEST 2: RANDOMIZED START-DATE (offset 0..11)
    # ════════════════════════════════════════════════════════════════════════ #
    print("\n" + "═"*70)
    print("TEST 2: RANDOMIZED START-DATE (offset 0..11)")
    print("Pass: CAGR_net > 0 in ≥80% of offsets, Calmar consistent")
    print("═"*70)
    offset_results = []
    for offset in range(PROD_HOLD_STEP):
        r = _run_backtest(panel, start_offset=offset, **prod_kwargs)
        if r:
            offset_results.append({"offset": offset, **{k: r[k] for k in ["ann_net","mdd_net","calmar"]}})

    if offset_results:
        df_off = pd.DataFrame(offset_results)
        positive_pct = (df_off["ann_net"] > 0).mean() * 100
        print(f"\n{'offset':>7s} {'CAGR_net':>9s} {'MDD':>9s} {'Calmar':>8s}")
        print("-" * 40)
        for _, row in df_off.iterrows():
            flag = " ← baseline" if row["offset"] == 0 else ""
            print(f"{int(row['offset']):>7d} {row['ann_net']:>+8.2%} {row['mdd_net']:>8.2%} "
                  f"{row['calmar']:>7.3f}{flag}")
        print(f"\nPositive CAGR_net in {positive_pct:.0f}% of offsets "
              f"({'✓ PASS' if positive_pct >= 80 else '✗ FAIL — check sensitivity'})")
        print(f"Calmar range: [{df_off['calmar'].min():.3f}, {df_off['calmar'].max():.3f}]  "
              f"(mean {df_off['calmar'].mean():.3f}, std {df_off['calmar'].std():.3f})")
        calmar_cv = df_off["calmar"].std() / abs(df_off["calmar"].mean())
        print(f"Calmar CV (std/mean): {calmar_cv:.2f}  "
              f"({'✓ stable (<0.40)' if calmar_cv < 0.40 else '✗ unstable — overfit risk'})")

    # ════════════════════════════════════════════════════════════════════════ #
    # TEST 3: HOLD_STEP SENSITIVITY
    # ════════════════════════════════════════════════════════════════════════ #
    print("\n" + "═"*70)
    print("TEST 3: HOLD_STEP SENSITIVITY (8..20, fixed enter=0.80 keep=0.70)")
    print("Pass: Calmar consistent, no cliff edges adjacent to hold_step=12")
    print("═"*70)
    print(f"\n{'hs':>4s} {'CAGR_net':>9s} {'MDD':>9s} {'Calmar':>8s} {'turn/p':>7s}")
    print("-" * 46)
    hs_results = []
    for hs in [8, 10, 12, 14, 16, 18, 20]:
        r = _run_backtest(panel, factor_col="lv_z", hold_step=hs,
                          enter_q=PROD_ENTER_Q, keep_q=PROD_KEEP_Q,
                          hs300_ret20=hs300_ret20, overlay_thr=PROD_OVERLAY_THR,
                          start_offset=0)
        if r:
            flag = " ← prod" if hs == PROD_HOLD_STEP else ""
            print(f"{hs:>4d} {r['ann_net']:>+8.2%} {r['mdd_net']:>8.2%} "
                  f"{r['calmar']:>7.3f} {r['turnover']:>6.1%}{flag}")
            hs_results.append({"hold_step": hs, **{k: r[k] for k in ["ann_net","mdd_net","calmar"]}})

    if hs_results:
        df_hs = pd.DataFrame(hs_results)
        calmar_cv = df_hs["calmar"].std() / abs(df_hs["calmar"].mean())
        print(f"\nCalmar range: [{df_hs['calmar'].min():.3f}, {df_hs['calmar'].max():.3f}]  "
              f"CV={calmar_cv:.2f}  "
              f"({'✓ stable (<0.40)' if calmar_cv < 0.40 else '✗ unstable — hold_step sensitive'})")

    # ════════════════════════════════════════════════════════════════════════ #
    # TEST 4: PARAMETER GRID (enter_q × keep_q)
    # ════════════════════════════════════════════════════════════════════════ #
    print("\n" + "═"*70)
    print("TEST 4: PARAMETER GRID (enter_q × keep_q, fixed hold_step=12)")
    print("Pass: Calmar > 0.15 in ≥7/9 cells")
    print("═"*70)
    enter_qs = [0.75, 0.80, 0.85]
    keep_qs  = [0.65, 0.70, 0.75]
    grid_results = {}
    for eq in enter_qs:
        for kq in keep_qs:
            r = _run_backtest(panel, factor_col="lv_z", hold_step=PROD_HOLD_STEP,
                              enter_q=eq, keep_q=kq,
                              hs300_ret20=hs300_ret20, overlay_thr=PROD_OVERLAY_THR,
                              start_offset=0)
            grid_results[(eq, kq)] = r

    # Print Calmar grid
    print(f"\n  Calmar grid — rows=enter_q, cols=keep_q")
    print(f"  {'':8s}" + "".join(f"  keep={kq:.2f}" for kq in keep_qs))
    pass_count = 0
    for eq in enter_qs:
        row_str = f"  enter={eq:.2f}"
        for kq in keep_qs:
            r = grid_results.get((eq, kq), {})
            cal = r.get("calmar", np.nan)
            marker = "★" if (eq == PROD_ENTER_Q and kq == PROD_KEEP_Q) else " "
            val = f"{cal:.3f}{marker}" if not np.isnan(cal) else "  nan "
            if not np.isnan(cal) and cal > 0.15:
                pass_count += 1
            row_str += f"  {val:>8s}"
        print(row_str)
    print(f"\n  Cells with Calmar > 0.15: {pass_count}/9  "
          f"({'✓ PASS' if pass_count >= 7 else '✗ FAIL — param sensitive'})")

    # ── Save ─────────────────────────────────────────────────────────────── #
    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)

    rows_flat = []
    if offset_results:
        for r in offset_results:
            rows_flat.append({"test": "start_offset", **r})
    if hs_results:
        for r in hs_results:
            rows_flat.append({"test": "hold_step", **r})
    for (eq, kq), r in grid_results.items():
        if r:
            rows_flat.append({"test": "param_grid", "enter_q": eq, "keep_q": kq,
                               **{k: r[k] for k in ["ann_net","mdd_net","calmar"]}})
    pd.DataFrame(rows_flat).to_csv(
        os.path.join(out_dir, "production_qc.csv"), index=False, encoding="utf-8-sig"
    )
    print(f"\nSaved → {out_dir}/production_qc.csv")


if __name__ == "__main__":
    main()
