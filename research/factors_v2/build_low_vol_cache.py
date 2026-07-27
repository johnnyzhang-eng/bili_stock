"""
Build low_vol factor once, pickle to cache. Run once; downstream scripts
load from cache to avoid re-computing the groupby-winsorize step that
has been hitting a pandas/numpy memory allocation error on Py 3.14.
"""

import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors.factor_low_volatility import build_low_volatility_factor


VOL_WINDOW = 60
START = "2015-01-01"
END   = "2025-12-31"


def main():
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    print(f"Building low_vol (w={VOL_WINDOW}) over {START} → {END} ...", flush=True)
    lv = build_low_volatility_factor(
        stock_dir, start_date=START, end_date=END,
        window=VOL_WINDOW, min_periods=max(20, VOL_WINDOW // 3),
    )
    lv = lv.rename(columns={"factor_raw": "lv_raw"})[["date", "stock_symbol", "lv_raw"]]
    cache_dir = os.path.join(ROOT, "research", "factors_v2", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    out_path = os.path.join(cache_dir, f"low_vol_w{VOL_WINDOW}.pkl")
    lv.to_pickle(out_path)
    print(f"Saved → {out_path}  ({len(lv):,} rows)")


if __name__ == "__main__":
    main()
