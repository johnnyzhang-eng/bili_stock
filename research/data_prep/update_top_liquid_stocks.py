"""
Targeted Stock Data Updater — Top N by Liquidity
=================================================
Scans all stock CSVs, ranks by recent avg daily amount,
updates only the top N. Much faster than full refresh.

Run:
    python research/data_prep/update_top_liquid_stocks.py
"""

import glob
import os
import sys
import time

import numpy as np
import pandas as pd
import baostock as bs

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
TARGET_END = "2026-04-18"
TOP_N      = 1000


def _bs_code(sym: str) -> str:
    sym = sym.upper()
    if sym.startswith("SH"):
        return f"sh.{sym[2:]}"
    elif sym.startswith("SZ"):
        return f"sz.{sym[2:]}"
    return sym


def _download_append(bs_code: str, sym: str, fp: str, from_date: str) -> bool:
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,close,high,low,volume,amount,pctChg,turn",
        start_date=from_date,
        end_date=TARGET_END,
        frequency="d",
        adjustflag="2",
    )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return False

    new_df = pd.DataFrame(rows, columns=["date","open","close","high","low","volume","amount","pctChg","turn"])
    for c in ["open","close","high","low","volume","amount","pctChg","turn"]:
        new_df[c] = pd.to_numeric(new_df[c], errors="coerce")

    old = pd.read_csv(fp, encoding="utf-8-sig", header=0)
    old_cols = list(old.columns)

    new_mapped = pd.DataFrame()
    new_mapped[old_cols[0]] = new_df["date"]
    if len(old_cols) >= 12:
        new_mapped[old_cols[1]] = sym[2:]
        new_mapped[old_cols[2]] = new_df["open"]
        new_mapped[old_cols[3]] = new_df["close"]
        new_mapped[old_cols[4]] = new_df["high"]
        new_mapped[old_cols[5]] = new_df["low"]
        new_mapped[old_cols[6]] = new_df["volume"]
        new_mapped[old_cols[7]] = new_df["amount"]
        new_mapped[old_cols[8]] = np.nan
        new_mapped[old_cols[9]] = new_df["pctChg"]
        new_mapped[old_cols[10]] = np.nan
        new_mapped[old_cols[11]] = new_df["turn"]
    else:
        new_mapped[old_cols[1]] = new_df["open"]
        new_mapped[old_cols[2]] = new_df["close"]
        new_mapped[old_cols[3]] = new_df["high"]
        new_mapped[old_cols[4]] = new_df["low"]
        new_mapped[old_cols[5]] = new_df["volume"]
        new_mapped[old_cols[6]] = new_df["amount"]

    combined = pd.concat([old, new_mapped], ignore_index=True)
    combined = combined.drop_duplicates(subset=[old_cols[0]], keep="last")
    combined.to_csv(fp, index=False, encoding="utf-8-sig")
    return True


def main():
    target_dt = pd.Timestamp(TARGET_END)

    print("Step 1: Scanning CSVs for liquidity rank ...", flush=True)
    files = glob.glob(os.path.join(STOCK_DATA_DIR, "S[HZ]*.csv"))
    records = []
    for fp in files:
        sym = os.path.basename(fp).replace(".csv", "").upper()
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig", header=0, usecols=[0, 7])
            df.columns = ["date", "amount"]
            df["date"]   = pd.to_datetime(df["date"], errors="coerce")
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
            latest = df["date"].max()
            avg_amt = df["amount"].tail(60).mean()
            stale = pd.notna(latest) and latest < target_dt
            records.append({"sym": sym, "fp": fp, "latest": latest,
                            "avg_amt": avg_amt, "stale": stale})
        except Exception:
            pass

    df_rank = pd.DataFrame(records)
    df_rank = df_rank[df_rank["stale"]].sort_values("avg_amt", ascending=False)
    top = df_rank.head(TOP_N).reset_index(drop=True)
    print(f"  {len(df_rank)} stale files; selecting top {len(top)} by avg daily amount", flush=True)

    print(f"\nStep 2: Logging into BaoStock ...", flush=True)
    lg = bs.login()
    if str(lg.error_code) != "0":
        print(f"  Login failed: {lg.error_msg}")
        return

    t0 = time.time()
    updated = failed = skipped = 0
    for i, row in top.iterrows():
        sym    = row["sym"]
        fp     = row["fp"]
        latest = row["latest"]
        from_date = (latest + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            ok = _download_append(_bs_code(sym), sym, fp, from_date)
            if ok:
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1

        done = i + 1
        if done % 50 == 0 or done == len(top):
            elapsed = time.time() - t0
            eta     = elapsed / done * (len(top) - done)
            print(f"  [{done:4d}/{len(top)}] updated={updated} skipped={skipped} "
                  f"fail={failed}  elapsed={elapsed:.0f}s  ETA={eta:.0f}s", flush=True)

    bs.logout()
    print(f"\nDone — {updated} updated, {skipped} no new data, {failed} failed")
    print(f"Total time: {time.time()-t0:.0f}s")
    print(f"\nNext: python research/factors_v2/run_live_signal.py")


if __name__ == "__main__":
    main()
