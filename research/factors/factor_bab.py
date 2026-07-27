"""
BAB Factor — Betting Against Beta
===================================

Frazzini & Pedersen (2014): low-beta stocks persistently outperform
high-beta stocks on a risk-adjusted basis. In retail-heavy markets (A-share)
the effect is amplified because leverage-constrained institutions bid up
high-beta names, leaving low-beta underpriced.

Key structural difference vs. low_vol / MAX:
  - low_vol = absolute volatility (own standard deviation)
  - BAB     = *market-relative* sensitivity (covariance with HS300)
  A stock can be high-vol but low-beta (e.g. an idiosyncratic biotech);
  the two factors pick different names in the cross-section.

Definition
----------
  beta = rolling_cov(stock_ret, mkt_ret, 252) / rolling_var(mkt_ret, 252)
  factor_raw = -beta     (low beta → high score)

Sign pre-inverted: low beta → high factor score (conventional "long good").

Output mirrors factor_low_volatility.py:
    columns = [date, stock_symbol, factor_raw, factor_z]
"""

import glob
import os

import numpy as np
import pandas as pd


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def build_bab_factor(
    stock_data_dir: str,
    hs300_cache_path: str,
    start_date: str = "2015-01-01",
    end_date: str = "2025-12-31",
    window: int = 252,
    min_periods: int = 126,
    exclude_hk: bool = True,
) -> pd.DataFrame:
    """
    Compute rolling-beta factor vs. HS300 for every stock in stock_data_dir.

    Parameters
    ----------
    hs300_cache_path : path to data/market_cache/hs300_daily_cache.csv
    window           : rolling window in business days (default 252 ≈ 1 year)
    min_periods      : minimum observations required (default 126 ≈ 6 months)
    """
    # ------------------------------------------------------------------ #
    # Load HS300 daily returns (computed from close)
    # ------------------------------------------------------------------ #
    hs = pd.read_csv(hs300_cache_path, usecols=["date", "close"])
    hs["date"] = pd.to_datetime(hs["date"], errors="coerce").dt.normalize()
    hs["close"] = pd.to_numeric(hs["close"], errors="coerce")
    hs = hs.dropna().sort_values("date")
    hs["mkt_ret"] = hs["close"].pct_change()
    hs = hs.dropna(subset=["mkt_ret"]).set_index("date")["mkt_ret"]

    # Pre-compute rolling market variance (constant across stocks, so compute once)
    mkt_roll_var = hs.rolling(window, min_periods=min_periods).var()

    files = glob.glob(os.path.join(stock_data_dir, "*.csv"))
    if not files:
        raise FileNotFoundError(f"no CSVs found in {stock_data_dir}")

    start_dt = pd.to_datetime(start_date).normalize()
    end_dt   = pd.to_datetime(end_date).normalize()

    rows = []
    skipped = 0
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        if exclude_hk and sym.endswith(".HK"):
            continue
        try:
            df = pd.read_csv(fp, usecols=["日期", "收盘"])
        except Exception:
            skipped += 1
            continue
        df.columns = ["date", "close"]
        df["date"]  = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["date", "close"])
        df = df[df["close"] > 0].sort_values("date").set_index("date")
        if len(df) < min_periods + 1:
            continue

        df["stock_ret"] = df["close"].pct_change()

        # Align with market on shared dates
        aligned = df[["stock_ret"]].join(hs.rename("mkt_ret"), how="inner").dropna()
        if len(aligned) < min_periods + 1:
            continue

        # Rolling covariance of stock return with market return
        roll_cov = aligned["stock_ret"].rolling(window, min_periods=min_periods).cov(
            aligned["mkt_ret"]
        )
        # Rolling market variance (reindexed to aligned dates)
        roll_var = mkt_roll_var.reindex(aligned.index)

        beta = roll_cov / roll_var
        factor_raw = -beta  # low beta → high score

        out = pd.DataFrame({
            "date": aligned.index,
            "stock_symbol": sym,
            "factor_raw": factor_raw.values,
        })
        out = out[(out["date"] >= start_dt) & (out["date"] <= end_dt)]
        out = out.dropna(subset=["factor_raw"])
        if out.empty:
            continue
        rows.append(out)

    if not rows:
        return pd.DataFrame(columns=["date", "stock_symbol", "factor_raw", "factor_z"])

    panel = pd.concat(rows, ignore_index=True)

    # Winsorize per date at p1/p99 — extreme betas from data errors / IPO noise
    panel["factor_raw"] = panel.groupby("date")["factor_raw"].transform(
        lambda s: s.clip(s.quantile(0.01), s.quantile(0.99))
    )
    panel["factor_z"] = panel.groupby("date")["factor_raw"].transform(_zscore)
    panel = panel.sort_values(["date", "stock_symbol"]).reset_index(drop=True)

    print(
        f"[bab] built factor: {panel['stock_symbol'].nunique()} stocks, "
        f"{panel['date'].nunique()} dates, {len(panel):,} rows, skipped={skipped}"
    )
    return panel


if __name__ == "__main__":
    import sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    stock_dir  = os.path.join(ROOT, "data", "stock_data")
    hs300_path = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
    df = build_bab_factor(stock_dir, hs300_path,
                          start_date="2020-01-01", end_date="2025-12-31")
    print(df.head(5))
    print(f"factor_raw range: [{df['factor_raw'].min():.4f}, {df['factor_raw'].max():.4f}]")
    print(f"factor_z   range: [{df['factor_z'].min():.3f},  {df['factor_z'].max():.3f}]")
    # Sanity: median beta should be near 1.0 (factor_raw near -1.0)
    print(f"median factor_raw (≈ -median_beta): {df['factor_raw'].median():.4f}")
