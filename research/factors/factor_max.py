"""
MAX Factor (Lottery-Preference Reversal)
========================================

Bali, Cakici & Whitelaw (2011): stocks with the highest single-day return
over the past month are systematically overpriced and underperform next
period. The effect is particularly strong in retail-heavy markets (A-share
retail share ≈ 70%), where lottery-like stocks get bid up on salience bias.

Definition
----------
factor_raw = -max(daily_return, window=20 bdays)

Sign is pre-inverted: LOW past-max (un-lottery-like) → HIGH factor score,
so the factor behaves like a conventional "long good / short bad" signal.

Output shape mirrors factor_low_volatility.py:
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


def build_max_factor(
    stock_data_dir: str,
    start_date: str = "2015-01-01",
    end_date: str = "2025-12-31",
    window: int = 20,
    min_periods: int = 15,
    exclude_hk: bool = True,
) -> pd.DataFrame:
    """
    Compute MAX factor from daily close prices in stock_data_dir.

    Parameters
    ----------
    window : rolling window in business days (default 20 ≈ 1 month, per Bali 2011)
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

        # Simple daily return. Log vs arithmetic both work for MAX — use
        # arithmetic so the "max single-day pop" interpretation matches
        # Bali 2011 and what a retail investor actually sees.
        df["daily_ret"] = df["close"].pct_change()
        df["max_ret"] = df["daily_ret"].rolling(window, min_periods=min_periods).max()
        df["factor_raw"] = -df["max_ret"]  # low max → high score
        df["stock_symbol"] = sym

        out = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        out = out.dropna(subset=["factor_raw"])
        if out.empty:
            continue
        rows.append(out[["date", "stock_symbol", "factor_raw"]])

    if not rows:
        return pd.DataFrame(columns=["date", "stock_symbol", "factor_raw", "factor_z"])

    panel = pd.concat(rows, ignore_index=True)
    # Winsorize per date at p1/p99 before z-scoring — same treatment as low_vol.
    # Stocks with corporate-action-driven 10x single-day prints (e.g. post
    # reverse-splits before BaoStock adjustment) would otherwise dominate.
    panel["factor_raw"] = panel.groupby("date")["factor_raw"].transform(
        lambda s: s.clip(s.quantile(0.01), s.quantile(0.99))
    )
    panel["factor_z"] = panel.groupby("date")["factor_raw"].transform(_zscore)
    panel = panel.sort_values(["date", "stock_symbol"]).reset_index(drop=True)

    print(
        f"[max] built factor: {panel['stock_symbol'].nunique()} stocks, "
        f"{panel['date'].nunique()} dates, {len(panel):,} rows, skipped={skipped}"
    )
    return panel


if __name__ == "__main__":
    import sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    df = build_max_factor(stock_dir, start_date="2020-01-01", end_date="2025-12-31")
    print(df.head(10))
    print(df.tail(10))
    print(f"factor_raw range: [{df['factor_raw'].min():.6f}, {df['factor_raw'].max():.6f}]")
    print(f"factor_z range: [{df['factor_z'].min():.3f}, {df['factor_z'].max():.3f}]")
