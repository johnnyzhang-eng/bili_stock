"""
Trend-Filter Overlay — Targeting 2018-Type Slow Bears
=====================================================

The 20-day momentum overlay (run_low_vol_overlay.py) showed that
HS300_ret20 triggers improve MDD only at the -10% extreme — and
essentially don't help 2018 (-29%). 2018 was not a crash, it was a
grind: 20-day returns were usually in the -3% to -7% range.

This script tests longer-horizon signals that distinguish "trend-down
bear" from "dip-and-rebound":

  Signal A: HS300 60-day return < threshold
  Signal B: HS300 close below 120-day SMA (ratio_120 < 1.0)
  Signal C: HS300 close below 200-day SMA (ratio_200 < 1.0)
  Signal D: BOTH ratio_120 < 1.0 AND hs300_ret20 < 0 (confirm)

For each, same overlay mechanics as the short-horizon script:
  scale_book = 1.0 if signal safe, else scale_off.
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


def _load_hs300_signals() -> pd.DataFrame:
    """Load HS300 close and compute ret60, sma120/200 ratios."""
    cache_path = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
    idx = pd.read_csv(cache_path, encoding="utf-8-sig")
    idx["date"] = pd.to_datetime(idx["date"], errors="coerce").dt.normalize()
    idx["close"] = pd.to_numeric(idx["close"], errors="coerce")
    idx = idx.dropna(subset=["date", "close"]).sort_values("date")
    idx["hs300_ret60"]   = idx["close"] / idx["close"].shift(60) - 1.0
    idx["hs300_sma120"]  = idx["close"].rolling(120, min_periods=60).mean()
    idx["hs300_sma200"]  = idx["close"].rolling(200, min_periods=100).mean()
    idx["ratio_120"]     = idx["close"] / idx["hs300_sma120"]
    idx["ratio_200"]     = idx["close"] / idx["hs300_sma200"]
    return idx[["date", "close", "hs300_ret60", "ratio_120", "ratio_200"]]


def _buffered_log(
    panel: pd.DataFrame, factor_col: str, hold_step: int,
    enter_q: float, keep_q: float, extra_signals: pd.DataFrame,
) -> pd.DataFrame:
    """Per-rebalance-date log with factor returns + all overlay signals."""
    ret_col = f"hold_ret_{hold_step}"
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")

    dates = sorted(sub["date"].unique())
    rebal_dates = dates[::hold_step]

    sig = extra_signals.set_index("date")

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

        if prev_hold is not None:
            turn = len(holdings - prev_hold) / max(len(holdings), 1)
        else:
            turn = 1.0

        # Pull overlay signals
        hs300_ret20 = float(g["hs300_ret20"].iloc[0]) if pd.notna(g["hs300_ret20"].iloc[0]) else 0.0
        s = sig.loc[d] if d in sig.index else None
        ret60     = float(s["hs300_ret60"]) if s is not None and pd.notna(s["hs300_ret60"]) else 0.0
        ratio_120 = float(s["ratio_120"])    if s is not None and pd.notna(s["ratio_120"]) else 1.0
        ratio_200 = float(s["ratio_200"])    if s is not None and pd.notna(s["ratio_200"]) else 1.0

        rows.append({
            "date":        d,
            "period_ret":  period_ret,
            "hs300_ret20": hs300_ret20,
            "hs300_ret60": ret60,
            "ratio_120":   ratio_120,
            "ratio_200":   ratio_200,
            "turnover":    turn,
        })
        prev_hold = holdings

    return pd.DataFrame(rows)


def _apply_overlay(log: pd.DataFrame, signal_name: str, threshold: float,
                   scale_off: float, cmp: str = "lt") -> dict:
    """Apply overlay based on a signal column and threshold."""
    df = log.copy()
    sig = df[signal_name]
    if cmp == "lt":
        risk_off_mask = sig < threshold
    elif cmp == "gt":
        risk_off_mask = sig > threshold
    else:
        raise ValueError(cmp)
    df["scale"] = np.where(risk_off_mask, scale_off, 1.0)

    df["gross_ret"] = df["scale"] * df["period_ret"]
    per_period_cost = df["scale"] * df["turnover"] * ROUND_TRIP_BP / 1e4
    prev_scale = df["scale"].shift(1).fillna(1.0)
    transition_cost = (df["scale"] - prev_scale).abs() * (ROUND_TRIP_BP / 2.0) / 1e4
    df["cost"]    = per_period_cost + transition_cost
    df["net_ret"] = df["gross_ret"] - df["cost"]

    r = np.clip(df["net_ret"].to_numpy(dtype=float), -0.99, None)
    wealth = np.cumprod(1 + r)
    peak = np.maximum.accumulate(wealth)
    mdd = float((wealth / peak - 1.0).min())
    years = len(df) / (BDAYS_PER_YEAR / HOLD_STEP)
    cagr_net = float(wealth[-1]) ** (1 / years) - 1
    cagr_gross = float(np.prod(1 + np.clip(df["gross_ret"], -0.99, None))) ** (1 / years) - 1
    calmar = cagr_net / abs(mdd) if mdd < 0 else np.nan
    time_off = float((df["scale"] < 1.0).mean())

    df["year"] = df["date"].dt.year
    yr_ret = df.groupby("year").apply(
        lambda g: float(np.prod(1 + np.clip(g["net_ret"], -0.99, None))) - 1
    )

    return {
        "signal": signal_name, "threshold": threshold, "scale_off": scale_off,
        "cagr_gross": cagr_gross, "cagr_net": cagr_net,
        "mdd": mdd, "calmar": calmar, "time_off": time_off,
        "ret_2018": float(yr_ret.get(2018, np.nan)),
        "ret_2022": float(yr_ret.get(2022, np.nan)),
        "ret_2015": float(yr_ret.get(2015, np.nan)),
        "ret_2023": float(yr_ret.get(2023, np.nan)),
    }


def main():
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = _add_hold_return(panel, HOLD_STEP)
    # Trim to bare minimum columns to reduce memory before factor merge.
    panel = panel[["date", "stock_symbol", f"hold_ret_{HOLD_STEP}", "hs300_ret20"]].copy()

    # Low_vol factor — cached (winsorize step has been erroring on Py 3.14 during
    # groupby-transform concatenation; cache once, reuse across scripts).
    lv_cache = os.path.join(ROOT, "research", "factors_v2", "cache",
                            f"low_vol_w{VOL_WINDOW}.pkl")
    if os.path.exists(lv_cache):
        print(f"Loading cached low_vol factor: {lv_cache}", flush=True)
        lv = pd.read_pickle(lv_cache)
    else:
        print(f"Building low_vol (w={VOL_WINDOW}) ...", flush=True)
        stock_dir = os.path.join(ROOT, "data", "stock_data")
        start = panel["date"].min().strftime("%Y-%m-%d")
        end   = panel["date"].max().strftime("%Y-%m-%d")
        lv = build_low_volatility_factor(
            stock_dir, start_date=start, end_date=end,
            window=VOL_WINDOW, min_periods=max(20, VOL_WINDOW // 3),
        )
        lv = lv.rename(columns={"factor_raw": "lv_raw"})[["date", "stock_symbol", "lv_raw"]]
        lv.to_pickle(lv_cache)
        print(f"Cached → {lv_cache}", flush=True)
    panel = panel.merge(lv, on=["date", "stock_symbol"], how="left")
    panel["lv_z"] = panel.groupby("date")["lv_raw"].transform(_zscore)

    print("Loading HS300 extended signals ...", flush=True)
    sig = _load_hs300_signals()

    print("Building buffered log with all signals ...", flush=True)
    log = _buffered_log(panel, "lv_z", HOLD_STEP, ENTER_Q, KEEP_Q, sig)
    print(f"  n_periods={len(log)}")
    print(f"  signal distributions at rebalance dates:")
    for c in ["hs300_ret20", "hs300_ret60", "ratio_120", "ratio_200"]:
        s = log[c]
        print(f"    {c:12s}  p5={s.quantile(0.05):+7.3f} p50={s.quantile(0.5):+7.3f} p95={s.quantile(0.95):+7.3f}")

    # ------------------------------------------------------------------ #
    # Define overlay configurations to test
    # ------------------------------------------------------------------ #
    baseline = _apply_overlay(log, "hs300_ret20", -999.0, 1.0)  # never triggers
    baseline["config"] = "baseline (no overlay)"

    configs = [baseline]
    # Best from short-horizon run (for reference)
    for (sig_name, th, off, cmp) in [
        ("hs300_ret20", -0.10, 0.00, "lt"),
        # 60-day return thresholds
        ("hs300_ret60", -0.05, 0.50, "lt"),
        ("hs300_ret60", -0.10, 0.00, "lt"),
        ("hs300_ret60", -0.10, 0.50, "lt"),
        ("hs300_ret60", -0.15, 0.00, "lt"),
        # SMA-120 trend filter
        ("ratio_120",    1.00, 0.00, "lt"),
        ("ratio_120",    1.00, 0.50, "lt"),
        ("ratio_120",    0.95, 0.00, "lt"),
        ("ratio_120",    0.95, 0.50, "lt"),
        # SMA-200 trend filter
        ("ratio_200",    1.00, 0.00, "lt"),
        ("ratio_200",    1.00, 0.50, "lt"),
        ("ratio_200",    0.95, 0.00, "lt"),
        ("ratio_200",    0.95, 0.50, "lt"),
    ]:
        r = _apply_overlay(log, sig_name, th, off, cmp=cmp)
        r["config"] = f"{sig_name} {cmp} {th:+.2f} → {off:.2f}"
        configs.append(r)

    print("\n" + "=" * 115)
    print(f"{'config':<38s} | {'CAGR_n':>7s} {'MDD':>7s} {'Calmar':>7s} {'t_off':>6s} | "
          f"{'2015':>7s} {'2018':>7s} {'2022':>7s} {'2023':>7s}")
    print("-" * 115)
    for r in configs:
        print(f"{r['config']:<38s} | "
              f"{r['cagr_net']:>6.2%} {r['mdd']:>6.2%} {r['calmar']:>6.2f} {r['time_off']:>5.1%} | "
              f"{r['ret_2015']:>6.2%} {r['ret_2018']:>6.2%} {r['ret_2022']:>6.2%} {r['ret_2023']:>6.2%}")

    out_df = pd.DataFrame(configs)
    out_path = os.path.join(ROOT, "research", "factors_v2", "output", "low_vol_overlay_trend.csv")
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
