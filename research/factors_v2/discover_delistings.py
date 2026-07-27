"""
Phase 1 of delisting backfill: just enumerate the list.

Calls:
  ak.stock_info_sh_delist()   — 上海退市股
  ak.stock_info_sz_delist(symbol="终止上市公司")  — 深交所终止上市

We want:
  - Ticker with SH/SZ prefix
  - Name
  - Delisting date
  - First trading year (if available) — helps decide whether to fetch

Output:
  research/factors_v2/cache/delisted_tickers.csv

No price-fetching here; this is just scoping the problem.
"""

import os
import sys

import pandas as pd
import akshare as ak

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _fetch_sh() -> pd.DataFrame:
    """SH delisted — columns vary by akshare version; keep flexible."""
    try:
        df = ak.stock_info_sh_delist()
    except Exception as e:
        print(f"SH fetch failed: {e}")
        return pd.DataFrame()
    df["exchange"] = "SH"
    return df


def _fetch_sz() -> pd.DataFrame:
    """SZ delisted — akshare has multiple endpoints; try a few."""
    # Standard call
    for candidate in [
        lambda: ak.stock_info_sz_delist(symbol="终止上市公司"),
        lambda: ak.stock_info_sz_delist(),
    ]:
        try:
            df = candidate()
            df["exchange"] = "SZ"
            return df
        except Exception as e:
            print(f"SZ candidate failed: {e}")
            continue
    return pd.DataFrame()


def main():
    print("Fetching SH delisted list ...")
    sh = _fetch_sh()
    print(f"  SH rows: {len(sh)}, columns: {list(sh.columns)}")
    if not sh.empty:
        print(sh.head().to_string())

    print("\nFetching SZ delisted list ...")
    sz = _fetch_sz()
    print(f"  SZ rows: {len(sz)}, columns: {list(sz.columns)}")
    if not sz.empty:
        print(sz.head().to_string())

    # Attempt a unified schema: code, name, delisting_date, exchange
    def _unify(df: pd.DataFrame, exchange: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["symbol", "name", "delist_date", "exchange"])
        col_map = {}
        for want, options in {
            "code":        ["公司代码", "证券代码", "COMPANY_CODE", "股票代码"],
            "name":        ["公司简称", "证券简称", "公司名称", "股票名称"],
            "delist_date": ["暂停上市日期", "终止上市日期", "摘牌日期", "DELIST_DATE"],
        }.items():
            for opt in options:
                if opt in df.columns:
                    col_map[opt] = want
                    break
        df2 = df.rename(columns=col_map)
        if "code" not in df2.columns:
            print(f"  WARNING: couldn't find code column in {exchange}; cols={list(df.columns)}")
            return pd.DataFrame()
        df2["code"] = df2["code"].astype(str).str.zfill(6)
        df2["symbol"] = exchange + df2["code"]
        keep = ["symbol"] + [c for c in ["name", "delist_date"] if c in df2.columns]
        out = df2[keep].copy()
        out["exchange"] = exchange
        return out

    uni = pd.concat([_unify(sh, "SH"), _unify(sz, "SZ")], ignore_index=True)
    print(f"\nUnified: {len(uni)} rows")

    if "delist_date" in uni.columns:
        uni["delist_date"] = pd.to_datetime(uni["delist_date"], errors="coerce")
        print("\nDelistings by year:")
        year_hist = uni["delist_date"].dt.year.value_counts().sort_index()
        for y, n in year_hist.items():
            bar = "█" * min(80, n)
            print(f"  {int(y) if pd.notna(y) else 'NaN':>5}: {n:>4}  {bar}")
        # Rows relevant to 2015-2025 study
        in_window = uni[uni["delist_date"].between("2014-01-01", "2025-12-31")]
        print(f"\nDelistings within 2014-2025 window: {len(in_window)}")

    cache_dir = os.path.join(ROOT, "research", "factors_v2", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    out_path = os.path.join(cache_dir, "delisted_tickers.csv")
    uni.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
