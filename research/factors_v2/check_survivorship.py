"""
Survivorship check on data/stock_data/
======================================

Question: does the CSV set include stocks that delisted during 2015-2025,
or only stocks that are still listed as of the last data pull?

Method:
  1. Read last date from every A-share equity CSV.
  2. Histogram the last-dates. Living stocks cluster at the data-pull date.
     Delisted stocks (if preserved) have last-dates scattered earlier.
  3. Spot-check known delistings: 乐视网 (SZ300104), 康得新 (SZ002450),
     华锐风电 (SH601558), 退市海润 (SH600401).

If the "long tail" of early last-dates is missing, the factor backtest has
survivorship bias — bottom-quintile returns are understated because
high-vol names that went to zero are absent.
"""

import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors_v2.build_broad_panel import _is_a_share_equity


def _normalize_symbol(filename: str) -> str:
    """Canonicalize e.g. '600000.SH.csv' and 'SH510050.csv' → 'SH600000' / 'SH510050'."""
    stem = os.path.splitext(os.path.basename(filename))[0].upper()
    # format 1: '600000.SH' → 'SH600000'
    if "." in stem and len(stem) >= 9:
        parts = stem.split(".")
        if len(parts) == 2 and parts[1] in ("SH", "SZ", "BJ") and parts[0].isdigit():
            return parts[1] + parts[0]
    # format 2: 'SH510050' (already in SH/SZ/BJ+6digit form)
    return stem


def main():
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    files = glob.glob(os.path.join(stock_dir, "*.csv"))
    print(f"Total CSVs: {len(files)}")

    rows = []
    for fp in files:
        sym = _normalize_symbol(fp)
        if not _is_a_share_equity(sym):
            continue
        try:
            df = pd.read_csv(fp, usecols=["日期"])
        except Exception as e:
            continue
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df = df.dropna(subset=["日期"])
        if df.empty:
            continue
        first = df["日期"].min()
        last = df["日期"].max()
        rows.append({
            "symbol": sym,
            "first_date": first,
            "last_date": last,
            "n_days": len(df),
        })

    meta = pd.DataFrame(rows)
    print(f"A-share equity CSVs (after filter): {len(meta)}")
    print(f"\nFirst-date range:  {meta['first_date'].min().date()} → {meta['first_date'].max().date()}")
    print(f"Last-date range:   {meta['last_date'].min().date()} → {meta['last_date'].max().date()}")

    # ------------------------------------------------------------------ #
    # Last-date distribution: how many stocks have stopped updating early?
    # ------------------------------------------------------------------ #
    max_last = meta["last_date"].max()
    print(f"\nLatest last-date in set: {max_last.date()}")
    print("Stocks by how far their last-date is from the latest:")
    bins = [0, 5, 30, 90, 365, 730, 1825, 100000]
    labels = ["≤5d", "≤30d", "≤90d", "≤1y", "≤2y", "≤5y", ">5y"]
    gap_days = (max_last - meta["last_date"]).dt.days
    binned = pd.cut(gap_days, bins=bins, labels=labels, right=True, include_lowest=True)
    print(binned.value_counts().reindex(labels).to_string())

    # ------------------------------------------------------------------ #
    # Year-of-last-date histogram — look for the long tail
    # ------------------------------------------------------------------ #
    year_hist = meta["last_date"].dt.year.value_counts().sort_index()
    print("\nStocks by year-of-last-trade:")
    for yr, n in year_hist.items():
        bar = "█" * min(80, n // 5)
        print(f"  {yr}: {n:>5}  {bar}")

    # ------------------------------------------------------------------ #
    # Spot-check known delisted names
    # ------------------------------------------------------------------ #
    known_delisted = {
        "SZ300104": "乐视网 (delisted 2020-07)",
        "SZ002450": "康得新 (delisted 2021-07)",
        "SH601558": "华锐风电 (delisted 2020-05)",
        "SH600401": "退市海润 (delisted 2019-05)",
        "SH600634": "*ST富控 (delisted 2020)",
        "SH600087": "退市长油 (delisted 2014, re-listed 2019)",
        "SZ002680": "*ST长生 (delisted 2019)",
        "SH600485": "信威集团 (delisted 2020)",
    }
    meta_idx = meta.set_index("symbol")
    print("\nSpot-check of known delisted tickers:")
    for sym, note in known_delisted.items():
        if sym in meta_idx.index:
            last = meta_idx.loc[sym, "last_date"]
            n = meta_idx.loc[sym, "n_days"]
            print(f"  {sym}  present   last={last.date()}  n_days={n}  ({note})")
        else:
            print(f"  {sym}  MISSING                                    ({note})")

    out_dir = os.path.join(ROOT, "research", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "survivorship_meta.csv")
    meta.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved metadata → {out_path}")


if __name__ == "__main__":
    main()
