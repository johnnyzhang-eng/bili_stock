"""
Phase 2 of delisting backfill: fetch historical prices for delisted names.

Reads research/factors_v2/cache/delisted_tickers.csv (from discover_delistings.py),
filters to A-share equities that delisted within 2014-2026, fetches daily OHLCV
via ak.stock_zh_a_hist, and writes to data/stock_data/<code>.<EX>.csv.

  - Skips names whose target CSV already exists (resume support).
  - Throttles (sleep 0.15s) to avoid blocking.
  - Logs progress + summary of failures.

Run:
    python research/factors_v2/backfill_delistings.py
"""

import os
import sys
import time
import traceback

import pandas as pd
import akshare as ak

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors_v2.build_broad_panel import _is_a_share_equity


STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
LIST_PATH      = os.path.join(ROOT, "research", "factors_v2", "cache", "delisted_tickers.csv")
LOG_PATH       = os.path.join(ROOT, "research", "factors_v2", "cache", "backfill_log.csv")

START_DATE = "20100101"   # fetch from 2010 (same as existing names)
END_BUFFER_DAYS = 5       # fetch through delist_date + buffer
SLEEP_SEC  = 0.15


def _filename_for(symbol: str) -> str:
    """SZ300104 → 300104.SZ.csv"""
    ex, code = symbol[:2], symbol[2:]
    return f"{code}.{ex}.csv"


def main():
    tickers = pd.read_csv(LIST_PATH, encoding="utf-8-sig")
    tickers["delist_date"] = pd.to_datetime(tickers["delist_date"], errors="coerce")

    # Filter to A-share equity prefixes
    tickers = tickers[tickers["symbol"].apply(_is_a_share_equity)].copy()

    # Filter to delist_date within our study window
    tickers = tickers[
        tickers["delist_date"].between("2014-01-01", "2026-12-31")
    ].copy()
    print(f"Targeting {len(tickers)} A-share delistings within 2014-2026")

    log_rows = []
    n_skip, n_ok, n_fail = 0, 0, 0

    for i, row in tickers.reset_index(drop=True).iterrows():
        sym = row["symbol"]
        code = sym[2:]
        delist = row["delist_date"]
        end_date = (delist + pd.Timedelta(days=END_BUFFER_DAYS)).strftime("%Y%m%d")
        out_path = os.path.join(STOCK_DATA_DIR, _filename_for(sym))

        # Skip if already present and non-empty
        if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
            n_skip += 1
            log_rows.append({"symbol": sym, "status": "skip_exists", "rows": -1,
                             "delist_date": delist, "err": ""})
            continue

        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=START_DATE, end_date=end_date,
                adjust="qfq",
            )
            if df is None or len(df) < 20:
                n_fail += 1
                log_rows.append({"symbol": sym, "status": "too_few_rows",
                                 "rows": 0 if df is None else len(df),
                                 "delist_date": delist, "err": ""})
                print(f"  [{i+1}/{len(tickers)}] {sym}  too few rows "
                      f"({0 if df is None else len(df)})", flush=True)
            else:
                df.to_csv(out_path, index=False, encoding="utf-8-sig")
                n_ok += 1
                log_rows.append({"symbol": sym, "status": "ok", "rows": len(df),
                                 "delist_date": delist, "err": ""})
                if (i + 1) % 10 == 0 or i < 3:
                    print(f"  [{i+1}/{len(tickers)}] {sym}  ok  rows={len(df)}  "
                          f"range={df['日期'].iloc[0]}..{df['日期'].iloc[-1]}", flush=True)
        except Exception as e:
            n_fail += 1
            err_s = str(e)[:200]
            log_rows.append({"symbol": sym, "status": "error", "rows": 0,
                             "delist_date": delist, "err": err_s})
            print(f"  [{i+1}/{len(tickers)}] {sym}  ERROR: {err_s}", flush=True)

        time.sleep(SLEEP_SEC)

    log_df = pd.DataFrame(log_rows)
    log_df.to_csv(LOG_PATH, index=False, encoding="utf-8-sig")
    print(f"\nSummary: ok={n_ok}, skip_existing={n_skip}, fail={n_fail}")
    print(f"Log → {LOG_PATH}")


if __name__ == "__main__":
    main()
