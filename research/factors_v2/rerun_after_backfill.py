"""
Re-run the low_vol pipeline after delisted names have been backfilled
into data/stock_data/. Compares pre-backfill ("survivorship-biased")
vs post-backfill ("survivorship-adjusted") numbers.

Steps:
  1. Re-run survivorship audit (should show many more early-last-date
     names than the original 14).
  2. Invalidate panel cache + low_vol cache; rebuild.
  3. Re-run buffered backtest with production config.
  4. Print pre/post comparison: CAGR_gross, CAGR_net, MDD, spread,
     bottom-quintile return.
"""

import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


CACHE_PANEL   = os.path.join(ROOT, "research", "factors_v2", "cache",
                             "broad_panel_2015_2025_fwd10.pkl")
CACHE_LOW_VOL = os.path.join(ROOT, "research", "factors_v2", "cache",
                             "low_vol_w60.pkl")


def _invalidate_caches():
    for p in [CACHE_PANEL, CACHE_LOW_VOL]:
        if os.path.exists(p):
            # Move aside rather than delete, in case we want to diff
            bak = p + ".pre_backfill"
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(p, bak)
            print(f"Moved aside: {p} → {os.path.basename(bak)}")


def main():
    print("Step 1: re-running survivorship audit ...")
    subprocess.run([sys.executable, os.path.join(ROOT, "research", "factors_v2",
                                                 "check_survivorship.py")], check=False)

    print("\nStep 2: invalidating caches ...")
    _invalidate_caches()

    # Step 3: build new panel + low_vol
    print("\nStep 3: rebuilding caches ...")
    subprocess.run([sys.executable, "-c",
                    "from research.factors_v2.build_broad_panel import build_broad_panel;"
                    "build_broad_panel('2015-01-01','2025-12-31')"], check=False, cwd=ROOT)
    subprocess.run([sys.executable, os.path.join(ROOT, "research", "factors_v2",
                                                 "build_low_vol_cache.py")], check=False)

    # Step 4: re-run buffered backtest (regime script reports full stats)
    print("\nStep 4: re-running regime-stratified backtest ...")
    subprocess.run([sys.executable, os.path.join(ROOT, "research", "factors_v2",
                                                 "run_low_vol_regime.py")], check=False)

    # Step 5: re-run overlay to refresh the 19.9% → new-number table
    print("\nStep 5: re-running overlay grid ...")
    subprocess.run([sys.executable, os.path.join(ROOT, "research", "factors_v2",
                                                 "run_low_vol_overlay.py")], check=False)


if __name__ == "__main__":
    main()
