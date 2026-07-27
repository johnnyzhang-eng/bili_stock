"""
Delisting backfill via baostock (replaces eastmoney-based attempt that got
rate-limited). Baostock handles delisted stocks and has no IP throttling
in practice for this volume.

Reads research/factors_v2/cache/delisted_tickers.csv, filters to A-share
equity prefixes delisting 2014-2026, fetches daily OHLCV with qfq, writes
CSVs in exact format of existing data/stock_data/ files.

Requires:
  pip install baostock (already in the project; used by _load_hs300)
"""

import os
import sys
import time

import numpy as np
import pandas as pd
import baostock as bs

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors_v2.build_broad_panel import _is_a_share_equity


STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
LIST_PATH      = os.path.join(ROOT, "research", "factors_v2", "cache", "delisted_tickers.csv")
LOG_PATH       = os.path.join(ROOT, "research", "factors_v2", "cache", "backfill_log_baostock.csv")


START_DATE = "2010-01-01"


def _filename_for(symbol: str) -> str:
    ex, code = symbol[:2], symbol[2:]
    return f"{code}.{ex}.csv"


def _bs_code(symbol: str) -> str:
    """SZ300104 → sz.300104"""
    return f"{symbol[:2].lower()}.{symbol[2:]}"


def _fetch_one(bs_code: str, end_date: str) -> pd.DataFrame | None:
    """Fetch daily data via baostock, return DataFrame or None."""
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,amount,pctChg,turn",
        start_date=START_DATE,
        end_date=end_date,
        frequency="d",
        adjustflag="2",  # 前复权
    )
    if rs.error_code != "0":
        return None
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=rs.fields)
    return df


def _to_stock_data_format(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """
    Reshape baostock output to match existing data/stock_data/ CSVs:
      columns: 日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
    """
    out = pd.DataFrame()
    out["日期"]     = df["date"]
    out["股票代码"] = code
    for src, dst in [("open", "开盘"), ("close", "收盘"),
                     ("high", "最高"), ("low", "最低"),
                     ("volume", "成交量"), ("amount", "成交额"),
                     ("pctChg", "涨跌幅"), ("turn", "换手率")]:
        out[dst] = pd.to_numeric(df[src], errors="coerce")
    # 振幅 and 涨跌额 — derive
    with np.errstate(divide="ignore", invalid="ignore"):
        out["振幅"]  = (out["最高"] - out["最低"]) / out["收盘"].shift(1) * 100
        out["涨跌额"] = out["收盘"] - out["收盘"].shift(1)
    # Column order matches existing files
    return out[[
        "日期", "股票代码", "开盘", "收盘", "最高", "最低",
        "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率",
    ]]


def main():
    tickers = pd.read_csv(LIST_PATH, encoding="utf-8-sig")
    tickers["delist_date"] = pd.to_datetime(tickers["delist_date"], errors="coerce")
    tickers = tickers[tickers["symbol"].apply(_is_a_share_equity)].copy()
    tickers = tickers[
        tickers["delist_date"].between("2014-01-01", "2026-12-31")
    ].copy().reset_index(drop=True)
    print(f"Targeting {len(tickers)} A-share delistings within 2014-2026")

    print("Logging into baostock ...")
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")

    log_rows = []
    n_skip, n_ok, n_fail = 0, 0, 0
    try:
        for i, row in tickers.iterrows():
            sym = row["symbol"]
            delist = row["delist_date"]
            end_dt = (delist + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            out_path = os.path.join(STOCK_DATA_DIR, _filename_for(sym))

            if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                n_skip += 1
                log_rows.append({"symbol": sym, "status": "skip_exists",
                                 "rows": -1, "delist_date": delist, "err": ""})
                continue

            try:
                df = _fetch_one(_bs_code(sym), end_dt)
                if df is None or len(df) < 20:
                    n_fail += 1
                    log_rows.append({"symbol": sym, "status": "too_few_rows",
                                     "rows": 0 if df is None else len(df),
                                     "delist_date": delist, "err": ""})
                    print(f"  [{i+1}/{len(tickers)}] {sym}  too few rows", flush=True)
                    continue
                out_df = _to_stock_data_format(df, row["symbol"][2:])
                out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
                n_ok += 1
                log_rows.append({"symbol": sym, "status": "ok", "rows": len(out_df),
                                 "delist_date": delist, "err": ""})
                if (i + 1) % 20 == 0 or i < 5:
                    print(f"  [{i+1}/{len(tickers)}] {sym}  ok  rows={len(out_df)}  "
                          f"end={out_df['日期'].iloc[-1]}", flush=True)
            except Exception as e:
                n_fail += 1
                err_s = str(e)[:200]
                log_rows.append({"symbol": sym, "status": "error",
                                 "rows": 0, "delist_date": delist, "err": err_s})
                print(f"  [{i+1}/{len(tickers)}] {sym}  ERROR: {err_s}", flush=True)
    finally:
        bs.logout()

    log_df = pd.DataFrame(log_rows)
    log_df.to_csv(LOG_PATH, index=False, encoding="utf-8-sig")
    print(f"\nSummary: ok={n_ok}, skip={n_skip}, fail={n_fail}")
    print(f"Log → {LOG_PATH}")


if __name__ == "__main__":
    main()
