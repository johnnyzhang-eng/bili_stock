"""
基本面初筛层 (Layer 1)
=======================
从 panel_quarterly.csv 构建股票池：
  - 最新季报为最近 1 个季度（~3 个月内）
  - ROE >= 10%
  - 净利润同比增长 >= 0% (不倒退)
  - 营收同比增长 >= -5% (允许微降)
  - 毛利率 >= 15%
  - 排除 ST / 退
  - 排除创业板/科创板/北交所（主板才有稳定基本面）

输出候选池 -> output/live/fundamental_pool_<date>.csv
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import numpy as np
import pandas as pd

ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
OUT   = os.path.join(ROOT, "research", "factors_v2", "output", "live")
os.makedirs(OUT, exist_ok=True)

MIN_ROE       = 10.0
MIN_NP_YOY    = 0.0
MIN_REV_YOY   = -5.0
MIN_GROSS     = 15.0


def is_main_board(code: str) -> bool:
    """主板 only: 沪 60x (排除 688/689 科创板) + 深 000/001/002/003 (排除 30x 创业板)
    排除：北交所 (43/83/87/88/92)、B股 (200/900)、ETF/REITs。"""
    c = str(code).zfill(6)
    # 北交所
    if c.startswith(("43","83","87","88","92","4","8","9")): return False
    # 科创板 / 创业板
    if c.startswith(("30","301","302","688","689")): return False
    # ETF / REITs / 基金
    if c.startswith(("159","510","511","512","513","514","515","516","517","518","519","520","588","18")): return False
    # B股
    if c.startswith(("200","201","900")): return False
    # 主板：沪60 + 深 000/001/002/003
    return c.startswith(("60","000","001","002","003"))


def load_latest_snapshot() -> pd.DataFrame:
    if not os.path.exists(PANEL):
        raise FileNotFoundError(f"先跑 fetch_fundamentals.py 生成 {PANEL}")
    df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str})
    df["report_date"] = pd.to_datetime(df["report_date"])
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce")
    # 每只股取最新已披露季报
    df = df.sort_values(["code","report_date"])
    last = df.groupby("code").tail(1).reset_index(drop=True)
    return last


def main():
    snap = load_latest_snapshot()
    print(f"全市场最新季报: {len(snap)} 只股")
    print(f"  报告期范围: {snap['report_date'].min().date()} — {snap['report_date'].max().date()}\n")

    # 筛选
    mask = pd.Series(True, index=snap.index)
    filters = [
        ("主板", snap["code"].apply(is_main_board)),
        ("非ST", ~snap["name"].astype(str).str.contains("ST|退", na=False)),
        (f"ROE >= {MIN_ROE}", snap["roe"] >= MIN_ROE),
        (f"净利润YoY >= {MIN_NP_YOY}", snap["np_yoy"] >= MIN_NP_YOY),
        (f"营收YoY >= {MIN_REV_YOY}", snap["rev_yoy"] >= MIN_REV_YOY),
        (f"毛利率 >= {MIN_GROSS}", snap["gross_margin"] >= MIN_GROSS),
    ]

    print(f"  {'过滤条件':<28s} {'剩余':>6s}")
    print(f"  {'-'*40}")
    for name, m in filters:
        mask = mask & m.fillna(False)
        print(f"  {name:<28s} {mask.sum():>6d}")

    pool = snap[mask].copy()
    pool = pool.sort_values("roe", ascending=False)

    # 打分: ROE 70% + 净利润增长 30% (z-score)
    for col in ["roe","np_yoy"]:
        z = (pool[col] - pool[col].mean()) / pool[col].std()
        pool[f"{col}_z"] = z
    pool["fund_score"] = 0.7 * pool["roe_z"] + 0.3 * pool["np_yoy_z"]
    pool = pool.sort_values("fund_score", ascending=False)

    # 展示 Top 30
    print(f"\n  基本面 Top 30:")
    print(f"  {'排名':<4s} {'代码':<8s} {'名称':<12s} {'ROE':>6s} "
          f"{'净利润YoY':>8s} {'营收YoY':>8s} {'毛利率':>6s} {'行业':<12s}")
    print(f"  {'-'*72}")
    for i, (_, r) in enumerate(pool.head(30).iterrows(), 1):
        print(f"  {i:<4d} {r['code']:<8s} {str(r['name'])[:10]:<12s} "
              f"{r['roe']:>5.1f}% {r['np_yoy']:>+7.1f}% {r['rev_yoy']:>+7.1f}% "
              f"{r['gross_margin']:>5.1f}% {str(r.get('industry',''))[:10]}")

    # 保存
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    out = os.path.join(OUT, f"fundamental_pool_{today}.csv")
    pool.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n  候选池 {len(pool)} 只 -> {out}")

    # 行业分布
    top100 = pool.head(100)
    print(f"\n  Top 100 行业分布:")
    ind_ct = top100["industry"].value_counts().head(10)
    for ind, ct in ind_ct.items():
        print(f"    {ind:<16s} {ct} 只")


if __name__ == "__main__":
    main()
