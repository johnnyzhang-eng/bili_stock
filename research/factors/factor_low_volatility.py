"""
Low-Volatility Factor
=====================

Classic low-vol anomaly (Ang et al. 2006; Baker-Bradley-Wurgler 2011):
low-idiosyncratic-vol stocks persistently outperform high-vol stocks on
risk-adjusted basis. Academic half-life is long — a real groundwork factor.

Definition
----------
factor_raw = -rolling_std(log_return, window=60 bdays)

Sign is pre-inverted: low realized vol → high factor score, so the factor
behaves like a conventional "long good / short bad" signal.

Output shape matches `factor_rebalance_momentum.py` convention:
    columns = [date, stock_symbol, factor_raw, factor_z]
    factor_z = cross-sectional z-score per date.
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


def build_low_volatility_factor(
    stock_data_dir: str,
    start_date: str = "2015-01-01",
    end_date: str = "2025-12-31",
    window: int = 60,
    min_periods: int = 40,
    exclude_hk: bool = True,
) -> pd.DataFrame:
    """
    Compute realized-volatility factor from daily close prices in stock_data_dir.

    Parameters
    ----------
    stock_data_dir : path to data/stock_data/ (per-stock CSVs from BaoStock)
    window : rolling window in business days (default 60 ≈ 3 months)
    min_periods : min observations required; stocks with fewer are skipped
    exclude_hk : drop HK-listed files (*.HK.csv) — universe is A-shares only
    """
    files = glob.glob(os.path.join(stock_data_dir, "*.csv"))
    if not files:
        raise FileNotFoundError(f"no CSVs found in {stock_data_dir}")

    start_dt = pd.to_datetime(start_date).normalize()
    end_dt = pd.to_datetime(end_date).normalize()

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
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["date", "close"])
        df = df[df["close"] > 0].sort_values("date")
        if len(df) < min_periods + 1:
            continue

        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
        df["realized_vol"] = df["log_ret"].rolling(window, min_periods=min_periods).std()
        df["factor_raw"] = -df["realized_vol"]  # low vol → high score
        df["stock_symbol"] = sym

        out = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        out = out.dropna(subset=["factor_raw"])
        if out.empty:
            continue
        rows.append(out[["date", "stock_symbol", "factor_raw"]])

    if not rows:
        return pd.DataFrame(columns=["date", "stock_symbol", "factor_raw", "factor_z"])

    panel = pd.concat(rows, ignore_index=True)
    # Winsorize per date at p1/p99 before z-scoring.
    # Without this, data-error stocks (e.g. bad adjusted prices) with
    # implausibly large vol dominate the cross-section and blow up z-scores.
    panel["factor_raw"] = panel.groupby("date")["factor_raw"].transform(
        lambda s: s.clip(s.quantile(0.01), s.quantile(0.99))
    )
    panel["factor_z"] = panel.groupby("date")["factor_raw"].transform(_zscore)
    panel = panel.sort_values(["date", "stock_symbol"]).reset_index(drop=True)

    print(
        f"[low_vol] built factor: {panel['stock_symbol'].nunique()} stocks, "
        f"{panel['date'].nunique()} dates, {len(panel):,} rows, skipped={skipped}"
    )
    return panel


if __name__ == "__main__":
    import sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    df = build_low_volatility_factor(stock_dir, start_date="2020-01-01", end_date="2025-12-31")
    print(df.head(10))
    print(df.tail(10))
    print(f"factor_raw range: [{df['factor_raw'].min():.6f}, {df['factor_raw'].max():.6f}]")
    print(f"factor_z range: [{df['factor_z'].min():.3f}, {df['factor_z'].max():.3f}]")
