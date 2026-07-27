"""
Short-Term Reversal Factor
===========================

Jegadeesh (1990): stocks with the lowest return over the past ~5 business
days tend to outperform next week (mean reversion). The effect is strongest
in retail-heavy markets where overreaction to short-term news is common.

Key difference from low_vol / MAX:
  - low_vol = 60-day rolling std (slow signal, stable holdings)
  - MAX     = 20-day peak return (medium signal)
  - Reversal = 5-day return (fast signal, different timing cycle)
  → Hypothesis: reversal's timing cycle is orthogonal to low_vol's,
    so stacking could diversify period-by-period timing risk.

Definition
----------
  factor_raw = -(close / close.shift(5) - 1)   i.e. -ret_5d
  Sign pre-inverted: low past return → high factor score (expect rebound).

Important caveat: reversal alpha decays fast. IC should be measured over
a 5-day forward window, not the standard 10-day (fwd_ret_2w). The runner
tests both horizons.
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


def build_reversal_factor(
    stock_data_dir: str,
    start_date: str = "2015-01-01",
    end_date: str = "2025-12-31",
    window: int = 5,
    min_periods: int = 4,
    exclude_hk: bool = True,
) -> pd.DataFrame:
    """
    Compute short-term reversal factor from daily close prices.

    Parameters
    ----------
    window : lookback in business days (default 5 ≈ 1 week)
    """
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
        df = df[df["close"] > 0].sort_values("date")
        if len(df) < min_periods + 1:
            continue

        df["ret_5d"]     = df["close"] / df["close"].shift(window) - 1.0
        df["factor_raw"] = -df["ret_5d"]   # low past return → high score
        df["stock_symbol"] = sym

        out = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        out = out.dropna(subset=["factor_raw"])
        if out.empty:
            continue
        rows.append(out[["date", "stock_symbol", "factor_raw"]])

    if not rows:
        return pd.DataFrame(columns=["date", "stock_symbol", "factor_raw", "factor_z"])

    panel = pd.concat(rows, ignore_index=True)
    panel["factor_raw"] = panel.groupby("date")["factor_raw"].transform(
        lambda s: s.clip(s.quantile(0.01), s.quantile(0.99))
    )
    panel["factor_z"] = panel.groupby("date")["factor_raw"].transform(_zscore)
    panel = panel.sort_values(["date", "stock_symbol"]).reset_index(drop=True)

    print(
        f"[reversal] built factor: {panel['stock_symbol'].nunique()} stocks, "
        f"{panel['date'].nunique()} dates, {len(panel):,} rows, skipped={skipped}"
    )
    return panel


if __name__ == "__main__":
    import sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    df = build_reversal_factor(stock_dir, start_date="2020-01-01", end_date="2025-12-31")
    print(df.head(5))
    print(f"factor_raw range: [{df['factor_raw'].min():.4f}, {df['factor_raw'].max():.4f}]")
    print(f"median factor_raw: {df['factor_raw'].median():.4f}")
