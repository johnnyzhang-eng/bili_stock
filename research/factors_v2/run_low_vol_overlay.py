"""
Bear-Market Overlay Test on Buffered Low-Vol
============================================

2026-04 findings showed the buffered low_vol config posted -26.9% in
2018 — broad bear market drags quality down too. This script tests
a simple protective overlay:

  scale_book = 1.00 if hs300_ret20 at rebalance date >= threshold
             = scale_off otherwise

Grid:
  threshold    ∈ {-3%, -5%, -7%, -10%}
  scale_off    ∈ {0.00, 0.25, 0.50, 0.75}

Plus baseline (scale always = 1.00).

Metrics reported per config:
  - gross CAGR (before cost)
  - net CAGR  (after cost, scaled with book)
  - MDD       (max drawdown on net wealth curve)
  - Calmar    = CAGR / |MDD|
  - 2018_ret  (year 2018 full-year return under overlay)
  - time_off  (% of periods in scaled-down mode)

Cost model:
  - Per-period cost = scale × turnover × ROUND_TRIP_BP / 1e4
  - Transition cost = |scale_t - scale_{t-1}| × ROUND_TRIP_BP / 2 / 1e4
    (half-round-trip at each scale change — selling/buying Δ of book)
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
KEEP_Q         = 0.70


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


def _buffered_log(
    panel: pd.DataFrame, factor_col: str, hold_step: int,
    enter_q: float, keep_q: float,
) -> pd.DataFrame:
    """Per-rebalance-date log: date, period_ret, hs300_ret20, turnover."""
    ret_col = f"hold_ret_{hold_step}"
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")

    hs300_by_date = sub.groupby("date")["hs300_ret20"].first()

    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]

    rows = []
    prev_hold: set | None = None
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
        need = max(0, target_k - len(keep_set))
        new_set = set(entrants.head(need)["stock_symbol"])

        holdings = keep_set | new_set
        if not holdings:
            continue

        hold_df = g[g["stock_symbol"].isin(holdings)]
        period_ret = float(hold_df[ret_col].mean())

        # per-period turnover (for cost accounting)
        if prev_hold is not None:
            turn = len(holdings - prev_hold) / max(len(holdings), 1)
        else:
            turn = 1.0  # initial all-new

        rows.append({
            "date":        d,
            "period_ret":  period_ret,
            "hs300_ret20": float(hs300_by_date.get(d, 0.0)) if pd.notna(hs300_by_date.get(d, np.nan)) else 0.0,
            "turnover":    turn,
            "n_holdings":  len(holdings),
        })
        prev_hold = holdings

    return pd.DataFrame(rows)


def _apply_overlay(
    log: pd.DataFrame, threshold: float, scale_off: float,
) -> dict:
    """Apply overlay to per-period log, return summary metrics."""
    df = log.copy()
    df["scale"] = np.where(df["hs300_ret20"] < threshold, scale_off, 1.0)

    # Scaled gross period return (cash yields 0)
    df["gross_ret"] = df["scale"] * df["period_ret"]

    # Per-period cost: scale × turnover × rt_bp
    per_period_cost = df["scale"] * df["turnover"] * ROUND_TRIP_BP / 1e4

    # Transition cost: |Δscale| × half-round-trip
    prev_scale = df["scale"].shift(1).fillna(1.0)  # assume entering at full book
    transition_cost = (df["scale"] - prev_scale).abs() * (ROUND_TRIP_BP / 2.0) / 1e4

    df["cost"] = per_period_cost + transition_cost
    df["net_ret"] = df["gross_ret"] - df["cost"]

    # Wealth curve
    r = np.clip(df["net_ret"].to_numpy(dtype=float), -0.99, None)
    wealth = np.cumprod(1 + r)
    peak = np.maximum.accumulate(wealth)
    drawdown = wealth / peak - 1.0
    mdd = float(drawdown.min())

    years = len(df) / (BDAYS_PER_YEAR / HOLD_STEP)
    cagr_net = float(wealth[-1]) ** (1 / years) - 1 if years > 0 else np.nan
    cagr_gross = float(np.prod(1 + np.clip(df["gross_ret"], -0.99, None))) ** (1 / years) - 1

    calmar = cagr_net / abs(mdd) if mdd < 0 else np.nan
    time_off = float((df["scale"] < 1.0).mean())

    # 2018 specific
    df["year"] = df["date"].dt.year
    yr_ret = df.groupby("year").apply(
        lambda g: float(np.prod(1 + np.clip(g["net_ret"], -0.99, None))) - 1
    )
    ret_2018 = float(yr_ret.get(2018, np.nan))
    ret_2022 = float(yr_ret.get(2022, np.nan))

    ann_cost = float(df["cost"].sum()) / years

    return {
        "threshold":  threshold,
        "scale_off":  scale_off,
        "cagr_gross": cagr_gross,
        "cagr_net":   cagr_net,
        "mdd":        mdd,
        "calmar":     calmar,
        "ann_cost":   ann_cost,
        "time_off":   time_off,
        "ret_2018":   ret_2018,
        "ret_2022":   ret_2022,
        "yr_returns": yr_ret.to_dict(),
    }


def main():
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = _add_hold_return(panel, HOLD_STEP)

    print(f"Building low_vol (w={VOL_WINDOW}) ...", flush=True)
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

    print("Building buffered log ...", flush=True)
    log = _buffered_log(panel, "lv_z", HOLD_STEP, ENTER_Q, KEEP_Q)
    print(f"  n_periods={len(log)}, years={len(log)/(BDAYS_PER_YEAR/HOLD_STEP):.2f}")

    # ------------------------------------------------------------------ #
    # Baseline (no overlay)
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 98)
    print("OVERLAY GRID (buffered low_vol, w=60, hs=12, enter=0.80, keep=0.70)")
    print("=" * 98)
    print(f"{'threshold':>10s} {'scale_off':>10s} | "
          f"{'CAGR_g':>7s} {'CAGR_n':>7s} {'MDD':>7s} {'Calmar':>7s} "
          f"{'cost':>6s} {'time_off':>9s} | {'2018':>7s} {'2022':>7s}")
    print("-" * 98)

    configs = [{"threshold": None, "scale_off": 1.0, "_label": "baseline (no overlay)"}]
    for th in [-0.03, -0.05, -0.07, -0.10]:
        for off in [0.00, 0.25, 0.50, 0.75]:
            configs.append({"threshold": th, "scale_off": off})

    results = []
    for cfg in configs:
        if cfg.get("_label") == "baseline (no overlay)":
            # threshold below any hs300_ret20 → never triggers
            r = _apply_overlay(log, threshold=-1.0, scale_off=1.0)
            r["threshold_str"] = "  none"
            r["scale_off"]     = 1.00
        else:
            r = _apply_overlay(log, threshold=cfg["threshold"], scale_off=cfg["scale_off"])
            r["threshold_str"] = f"{cfg['threshold']*100:>+5.0f}%"
        results.append(r)

        print(f"{r['threshold_str']:>10s} {r['scale_off']:>10.2f} | "
              f"{r['cagr_gross']:>6.2%} {r['cagr_net']:>6.2%} "
              f"{r['mdd']:>6.2%} {r['calmar']:>6.2f} "
              f"{r['ann_cost']:>5.2%} {r['time_off']:>8.1%} | "
              f"{r['ret_2018']:>6.2%} {r['ret_2022']:>6.2%}")

    # Dump to CSV
    out_df = pd.DataFrame([{k: v for k, v in r.items() if k != "yr_returns"} for r in results])
    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    out_path = os.path.join(out_dir, "low_vol_overlay_grid.csv")
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_path}")

    # Highlight best by Calmar
    best = out_df.loc[out_df["calmar"].idxmax()]
    print(f"\nBest by Calmar: threshold={best['threshold_str']} scale_off={best['scale_off']:.2f}")
    print(f"  CAGR_net={best['cagr_net']:.2%}  MDD={best['mdd']:.2%}  Calmar={best['calmar']:.2f}")
    print(f"  2018={best['ret_2018']:.2%}  2022={best['ret_2022']:.2%}")


if __name__ == "__main__":
    main()
