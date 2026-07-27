"""
拉取 债券 + 黄金 长历史, 拼进 long_history.csv
=================================================
债: sh000012 上证国债指数 (Sina, 2003-2026, 23 年)
金: AU0   沪金主力连续 (Sina 期货, 2008-2026, 18 年)

输出: long_history_4asset.csv  — 从 2010-06-01 起对齐 (继承 GEM 起点),
列: date / DIV / GEM / HS300 / BOND / GOLD  (全部首日归一 1.0)
"""
import os, sys
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
for k in ["HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"]:
    os.environ.pop(k, None)

import pandas as pd
import numpy as np
import akshare as ak

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")


def main():
    print("[1] 读已有 long_history.csv")
    base = pd.read_csv(os.path.join(OUT_DIR, "long_history.csv"), encoding="utf-8-sig")
    base["date"] = pd.to_datetime(base["date"])
    print(f"  {len(base)} 行  {base['date'].min().date()} → {base['date'].max().date()}")

    print("\n[2] sh000012 上证国债指数")
    bond = ak.stock_zh_index_daily(symbol="sh000012")
    bond["date"] = pd.to_datetime(bond["date"])
    bond["close"] = pd.to_numeric(bond["close"], errors="coerce")
    bond = bond[["date", "close"]].dropna().sort_values("date")
    print(f"  {len(bond)} 行  {bond['date'].min().date()} → {bond['date'].max().date()}")

    print("\n[3] AU0 沪金主力")
    gold = ak.futures_main_sina(symbol="AU0", start_date="20050101", end_date="20260421")
    gold = gold.rename(columns={"日期":"date", "收盘价":"close"})
    gold["date"] = pd.to_datetime(gold["date"])
    gold["close"] = pd.to_numeric(gold["close"], errors="coerce")
    gold = gold[["date","close"]].dropna().sort_values("date")
    print(f"  {len(gold)} 行  {gold['date'].min().date()} → {gold['date'].max().date()}")

    print("\n[4] 合并 + 首日归一")
    out = base.merge(bond.rename(columns={"close":"BOND"}), on="date", how="left") \
              .merge(gold.rename(columns={"close":"GOLD"}), on="date", how="left")

    # BOND / GOLD 前向填充 (交易日不完全一致)
    out["BOND"] = out["BOND"].ffill()
    out["GOLD"] = out["GOLD"].ffill()
    # 从第一个 BOND & GOLD 都有值的日子开始
    out = out.dropna(subset=["BOND","GOLD"]).reset_index(drop=True)

    for col in ["DIV","GEM","HS300","BOND","GOLD"]:
        out[col] = out[col] / out[col].iloc[0]

    fp = os.path.join(OUT_DIR, "long_history_4asset.csv")
    out.to_csv(fp, index=False, encoding="utf-8-sig")
    print(f"\n  ← 已写 {fp}")
    print(f"     {len(out)} 行  {out['date'].min().date()} → {out['date'].max().date()}")

    # 快速看各资产 16 年表现
    print("\n" + "=" * 70)
    print("各资产单独 buy-and-hold")
    print("=" * 70)
    yrs = (out["date"].iloc[-1] - out["date"].iloc[0]).days / 365.25
    for c in ["DIV","GEM","HS300","BOND","GOLD"]:
        total = out[c].iloc[-1] - 1
        cagr = (out[c].iloc[-1]) ** (1/yrs) - 1
        r = out[c].pct_change()
        vol = r.std() * np.sqrt(252)
        dd = (out[c] / out[c].cummax() - 1).min()
        print(f"  {c:<6s} 累计 {total:>+7.1%}  CAGR {cagr:>+6.2%}  波动 {vol:>5.1%}  MDD {dd:>+6.1%}")


if __name__ == "__main__":
    main()
