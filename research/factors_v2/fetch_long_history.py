"""
长历史指数/ETF 拼接 — 2005-2026
==================================
红利低波替身:
  - 2005-01 → 2018-12: sh000922 (中证红利, Sina)  ※ 无红利低波历史可得, 用中证红利逼近
  - 2019-01 → 今:       ETF 512890 (红利低波 hfq)
创业板替身:
  - 2010-06 → 2011-09:  sz399006 (创业板指, Sina)
  - 2011-09 → 今:       ETF 159915 (创业板 hfq)
HS300:
  - 全段用 sh000300 (Sina, 2005+)

输出 long_history.csv 包含 date/DIV/GEM/HS300 拼接序列 (起点归一 1.0, 每段首日对齐).
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
CACHE = os.path.join(ROOT, "data", "market_cache")
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
os.makedirs(OUT_DIR, exist_ok=True)


def sina_index(symbol: str) -> pd.DataFrame:
    df = ak.stock_zh_index_daily(symbol=symbol)
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df[["date", "close"]].dropna().sort_values("date").reset_index(drop=True)


def load_etf_cache(code: str) -> pd.DataFrame:
    fp = os.path.join(CACHE, f"etf_{code}.csv")
    df = pd.read_csv(fp, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df[["date", "close"]].dropna().sort_values("date").reset_index(drop=True)


def splice(index_df: pd.DataFrame, etf_df: pd.DataFrame, name: str) -> pd.DataFrame:
    """把 index 归一后, 在 ETF 起点接上 ETF 收益."""
    idx0 = index_df["close"].iloc[0]
    index_df["nav"] = index_df["close"] / idx0

    etf0 = etf_df["close"].iloc[0]
    etf0_date = etf_df["date"].iloc[0]

    pre = index_df[index_df["date"] < etf0_date].copy()
    if len(pre) == 0:
        pre = pd.DataFrame(columns=["date","nav"])
        nav_level = 1.0
    else:
        # pre 段最后一天对齐到 ETF 起点前一天
        nav_level = pre["nav"].iloc[-1]

    etf_df["nav"] = etf_df["close"] / etf0 * nav_level
    out = pd.concat([
        pre[["date","nav"]],
        etf_df[["date","nav"]]
    ], ignore_index=True).drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    print(f"  {name}: pre={len(pre)} days ({pre['date'].min() if len(pre) else '-'} → {pre['date'].max() if len(pre) else '-'}) "
          f"+ ETF={len(etf_df)} days → total {len(out)}")
    return out


def main():
    print("=" * 80)
    print("抓取长历史指数")
    print("=" * 80)

    # 中证红利 sh000922 (Sina, 2005-2019)
    print("\n[1/3] sh000922 中证红利 ...")
    div_idx = sina_index("sh000922")
    print(f"  {len(div_idx)} 条, {div_idx['date'].min().date()} → {div_idx['date'].max().date()}")

    # 创业板指 sz399006 (Sina)
    print("\n[2/3] sz399006 创业板指 ...")
    gem_idx = sina_index("sz399006")
    print(f"  {len(gem_idx)} 条, {gem_idx['date'].min().date()} → {gem_idx['date'].max().date()}")

    # HS300 sh000300 (Sina, 2002+)
    print("\n[3/3] sh000300 HS300 ...")
    hs_idx = sina_index("sh000300")
    print(f"  {len(hs_idx)} 条, {hs_idx['date'].min().date()} → {hs_idx['date'].max().date()}")

    print("\n" + "=" * 80)
    print("读 ETF cache")
    print("=" * 80)
    div_etf = load_etf_cache("512890")
    gem_etf = load_etf_cache("159915")
    print(f"  512890: {len(div_etf)} 条, {div_etf['date'].min().date()} → {div_etf['date'].max().date()}")
    print(f"  159915: {len(gem_etf)} 条, {gem_etf['date'].min().date()} → {gem_etf['date'].max().date()}")

    print("\n" + "=" * 80)
    print("拼接")
    print("=" * 80)
    div_long = splice(div_idx, div_etf, "DIV")
    gem_long = splice(gem_idx, gem_etf, "GEM")

    # HS300 直接用指数 (够长)
    hs_long = hs_idx.copy()
    hs_long["nav"] = hs_long["close"] / hs_long["close"].iloc[0]
    hs_long = hs_long[["date","nav"]]
    print(f"  HS300: {len(hs_long)} days")

    # 合并
    out = (div_long.rename(columns={"nav":"DIV"})
           .merge(gem_long.rename(columns={"nav":"GEM"}), on="date", how="outer")
           .merge(hs_long.rename(columns={"nav":"HS300"}), on="date", how="outer")
           .sort_values("date")
           .reset_index(drop=True))

    # 从 GEM 起点开始 (2010-06), 早期只有 DIV+HS300 的段单独保存
    out_gem = out[out["date"] >= gem_idx["date"].min()].copy()
    out_gem = out_gem.dropna(subset=["DIV","GEM","HS300"])
    # 归一起点
    for col in ["DIV","GEM","HS300"]:
        out_gem[col] = out_gem[col] / out_gem[col].iloc[0]

    fp = os.path.join(OUT_DIR, "long_history.csv")
    out_gem.to_csv(fp, index=False, encoding="utf-8-sig")
    print(f"\n  ← 已写 {fp}  ({len(out_gem)} 行, {out_gem['date'].min().date()} → {out_gem['date'].max().date()})")

    # 额外: 仅 DIV+HS300 段 (2005-2010, 可跑 DIV100 / DIV+HS 组合长历史)
    out_div_only = out[out["date"] < gem_idx["date"].min()].dropna(subset=["DIV","HS300"]).copy()
    if len(out_div_only):
        fp2 = os.path.join(OUT_DIR, "long_history_div_hs300.csv")
        # 归一起点
        for col in ["DIV","HS300"]:
            out_div_only[col] = out_div_only[col] / out_div_only[col].iloc[0]
        out_div_only[["date","DIV","HS300"]].to_csv(fp2, index=False, encoding="utf-8-sig")
        print(f"  ← 已写 {fp2}  (DIV+HS300 段 {len(out_div_only)} 行, {out_div_only['date'].min().date()} → {out_div_only['date'].max().date()})")

    print("\n完成。")


if __name__ == "__main__":
    main()
