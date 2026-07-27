"""
Regime-Stratified Low-Vol Analysis
==================================

Production-candidate config (buffered low_vol, w=60/hs=12/enter=0.80/keep=0.70)
shows paper net_top_ann ≈ 19.9%. The question this script answers:
**where does that return actually live?**

If the 19.9% is concentrated in 上涨 regimes, sizing needs to scale down
(we can't assume every year looks like 2020). If it's roughly uniform
across regimes, low-vol is a more all-weather signal than the numbers
suggest.

Output:
  1. Per-rebalance-date log: date, regime, period_return, n_holdings
  2. Regime split:  periods, mean_per_period, CAGR-if-always,
                    cumulative_log_contribution, share of total log
  3. Calendar year:  same metrics
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


def _buffered_period_log(
    panel: pd.DataFrame,
    factor_col: str,
    hold_step: int,
    enter_q: float,
    keep_q: float,
) -> pd.DataFrame:
    """Return a per-rebalance-date log with period return, regime, and size."""
    ret_col = f"hold_ret_{hold_step}"
    sub = panel.dropna(subset=[factor_col, ret_col, "date", "stock_symbol"]).copy()
    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")

    # Regime per date (most-common value; should be constant since regime is date-level)
    regime_by_date = sub.groupby("date")["regime"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else "震荡"
    )

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

        rows.append({
            "date":         d,
            "regime":       regime_by_date.get(d, "震荡"),
            "period_ret":   period_ret,
            "n_holdings":   len(holdings),
        })
        prev_hold = holdings

    return pd.DataFrame(rows)


def _summarize(log: pd.DataFrame, group_col: str, periods_per_year: float) -> pd.DataFrame:
    """CAGR-style summary per group."""
    out_rows = []
    total_log = float(np.log1p(np.clip(log["period_ret"], -0.99, None)).sum())
    for key, g in log.groupby(group_col):
        r = np.clip(g["period_ret"].to_numpy(dtype=float), -0.99, None)
        n = len(r)
        if n == 0:
            continue
        mean_per = float(np.mean(r))
        cum_log  = float(np.log1p(r).sum())
        # "CAGR if always this regime": annualize this subsample's CAGR by
        # assuming N periods/year continues to be the full-year cadence.
        years_eq = n / periods_per_year
        cum_mult = float(np.exp(cum_log))
        cagr = cum_mult ** (1 / years_eq) - 1 if years_eq > 0 else np.nan
        out_rows.append({
            group_col:       key,
            "periods":       n,
            "mean_per_per":  mean_per,
            "cagr_if_always": cagr,
            "cum_log":       cum_log,
            "log_share":     cum_log / total_log if total_log != 0 else np.nan,
        })
    out = pd.DataFrame(out_rows).sort_values(group_col)
    return out


def main():
    print("Loading broad panel ...", flush=True)
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    panel["stock_symbol"] = panel["stock_symbol"].astype(str).str.upper()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = _add_hold_return(panel, HOLD_STEP)
    print(f"  panel: {len(panel):,} rows, regime counts:")
    print(panel.drop_duplicates("date").groupby("regime").size().to_string())

    print(f"\nBuilding low_vol (w={VOL_WINDOW}) ...", flush=True)
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

    print(f"Running buffered backtest (enter={ENTER_Q}, keep={KEEP_Q}) ...", flush=True)
    log = _buffered_period_log(panel, "lv_z", HOLD_STEP, ENTER_Q, KEEP_Q)
    log["year"] = log["date"].dt.year
    periods_per_year = BDAYS_PER_YEAR / HOLD_STEP

    # ------------------------------------------------------------------ #
    # Overall (sanity check matches prior run)
    # ------------------------------------------------------------------ #
    r_all = np.clip(log["period_ret"].to_numpy(dtype=float), -0.99, None)
    years = len(r_all) / periods_per_year
    cagr_all = float(np.prod(1 + r_all)) ** (1 / years) - 1
    print(f"\nOverall: n_periods={len(r_all)}, years={years:.2f}, "
          f"gross CAGR (top)={cagr_all:.2%}")

    # ------------------------------------------------------------------ #
    # By regime
    # ------------------------------------------------------------------ #
    regime_df = _summarize(log, "regime", periods_per_year)
    print("\n" + "=" * 78)
    print("Regime breakdown (per-period returns, gross — no cost subtraction):")
    print(f"{'regime':<10s} {'periods':>7s} {'mean/p':>8s} "
          f"{'CAGR_if':>9s} {'cum_log':>9s} {'log_share':>10s}")
    print("-" * 78)
    for _, r in regime_df.iterrows():
        print(f"{r['regime']:<10s} {int(r['periods']):>7d} "
              f"{r['mean_per_per']:>7.2%} {r['cagr_if_always']:>8.2%} "
              f"{r['cum_log']:>+9.3f} {r['log_share']:>9.1%}")

    # ------------------------------------------------------------------ #
    # By year
    # ------------------------------------------------------------------ #
    year_df = _summarize(log, "year", periods_per_year)
    # Annual return per year = (prod of its period returns) - 1 (not CAGR — it IS the year)
    yr_returns = log.groupby("year").apply(
        lambda g: float(np.prod(1 + np.clip(g["period_ret"], -0.99, None))) - 1
    )
    year_df = year_df.merge(
        yr_returns.rename("annual_ret").reset_index(), on="year", how="left"
    )
    # Attach dominant regime per year (just the plurality regime)
    dom = log.groupby("year")["regime"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else ""
    )
    year_df = year_df.merge(dom.rename("dom_regime").reset_index(), on="year", how="left")

    print("\n" + "=" * 78)
    print("Yearly breakdown (annual_ret = raw gross, not net):")
    print(f"{'year':>4s} {'dom_reg':<8s} {'periods':>7s} {'mean/p':>8s} "
          f"{'annual_ret':>10s} {'log_share':>10s}")
    print("-" * 78)
    for _, r in year_df.iterrows():
        print(f"{int(r['year']):>4d} {r['dom_regime']:<8s} "
              f"{int(r['periods']):>7d} {r['mean_per_per']:>7.2%} "
              f"{r['annual_ret']:>9.2%} {r['log_share']:>9.1%}")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    log.to_csv(os.path.join(out_dir, "low_vol_regime_periods.csv"),
               index=False, encoding="utf-8-sig")
    regime_df.to_csv(os.path.join(out_dir, "low_vol_by_regime.csv"),
                     index=False, encoding="utf-8-sig")
    year_df.to_csv(os.path.join(out_dir, "low_vol_by_year.csv"),
                   index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_dir}/low_vol_regime_periods.csv "
          "(+ by_regime, by_year)")


if __name__ == "__main__":
    main()
