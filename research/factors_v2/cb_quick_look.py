"""
可转债双低策略 — 快速探查
==================================
Part 1: 市场 1 年均值（集思录可转债指数）
Part 2: 当前双低 Top 30 选债
"""

import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output", "live")
os.makedirs(OUT_DIR, exist_ok=True)


def part1_market_index():
    """集思录CB等权指数近1年表现。"""
    import akshare as ak
    print("="*70)
    print("【Part 1】可转债等权指数近 1 年表现（集思录数据）")
    print("="*70)

    df = ak.bond_cb_index_jsl()
    df["price_dt"] = pd.to_datetime(df["price_dt"])
    df = df.sort_values("price_dt")

    # 核心字段
    keep = ["price_dt", "price", "avg_price", "avg_dblow", "avg_premium_rt",
            "avg_ytm_rt", "temperature"]
    sub = df[keep].copy()

    first = sub.iloc[0]
    last  = sub.iloc[-1]
    total_ret = last["price"] / first["price"] - 1
    days = (last["price_dt"] - first["price_dt"]).days

    eq = sub["price"] / sub["price"].iloc[0]
    dd = eq / eq.cummax() - 1
    mdd = dd.min()

    # 日收益波动
    sub["ret"] = sub["price"].pct_change()
    vol = sub["ret"].std() * np.sqrt(252)
    ann_ret = (1 + total_ret) ** (365.25/days) - 1

    print(f"\n  时间区间: {first['price_dt'].date()} -> {last['price_dt'].date()} ({days}天)")
    print(f"  累计涨跌: {total_ret:+.2%}   年化: {ann_ret:+.2%}")
    print(f"  年化波动: {vol:.2%}   最大回撤: {mdd:.2%}")
    print()
    print(f"  市场当前温度（集思录）: {last['temperature']:.1f}  (50=冷, 100=热)")
    print(f"  市场平均价: {last['avg_price']:.2f} 元  (起始 {first['avg_price']:.2f})")
    print(f"  市场平均双低: {last['avg_dblow']:.1f}   (起始 {first['avg_dblow']:.1f})")
    print(f"  市场平均溢价率: {last['avg_premium_rt']:.1f}%  (起始 {first['avg_premium_rt']:.1f}%)")
    print(f"  市场平均到期收益率: {last['avg_ytm_rt']:.2f}%  (起始 {first['avg_ytm_rt']:.2f}%)")

    # 保存
    sub.to_csv(os.path.join(OUT_DIR, "cb_market_index.csv"),
               index=False, encoding="utf-8-sig")


def part2_current_picks(top_n: int = 30):
    """当前双低排名前N。"""
    import akshare as ak
    print("\n" + "="*70)
    print(f"【Part 2】当前双低 Top {top_n}（集思录默认返回前30只）")
    print("="*70)

    df = ak.bond_cb_jsl()
    print(f"  返回条数: {len(df)}")

    # 排除退市/违约/已下修的
    df = df[~df["转债名称"].str.contains("退", na=False)]
    df["现价"] = pd.to_numeric(df["现价"], errors="coerce")
    df["双低"] = pd.to_numeric(df["双低"], errors="coerce")
    df["转股溢价率"] = pd.to_numeric(df["转股溢价率"], errors="coerce")
    df = df.dropna(subset=["双低"]).sort_values("双低")

    # 过滤：价格 < 135 且 > 95（双低精髓）
    mask = (df["现价"] >= 95) & (df["现价"] <= 135)
    df_f = df[mask].head(top_n)

    print(f"\n  过滤后（价格 95-135）: {len(df_f)} 只\n")
    print(f"  {'排名':<4s} {'代码':<9s} {'转债名称':<12s} {'现价':>7s} "
          f"{'溢价率':>7s} {'双低值':>7s}  {'正股名称':<10s} {'评级':<6s} {'剩余年'}")
    print(f"  {'-'*85}")
    for i, (_, r) in enumerate(df_f.iterrows(), 1):
        print(f"  {i:<4d} {str(r['代码']):<9s} {str(r['转债名称']):<12s} "
              f"{r['现价']:>7.2f} {r['转股溢价率']:>6.1f}% "
              f"{r['双低']:>7.2f}  {str(r['正股名称']):<10s} "
              f"{str(r['债券评级']):<6s} {r.get('剩余年限', 0):.1f}")

    # 统计
    avg_price   = df_f["现价"].mean()
    avg_premium = df_f["转股溢价率"].mean()
    avg_dblow   = df_f["双低"].mean()

    print(f"\n  Top {top_n} 统计:")
    print(f"    平均价: {avg_price:.2f} 元   平均溢价: {avg_premium:.1f}%   平均双低: {avg_dblow:.1f}")

    # 资金门槛
    one_hand_each = df_f["现价"].sum() * 10   # 一手=10张, 面值100
    print(f"\n  资金门槛:")
    print(f"    每只买 1 手(10张): {one_hand_each:,.0f} 元 (约 {one_hand_each/10000:.1f} 万)")
    print(f"    每只买 1 张: {df_f['现价'].sum():,.0f} 元")

    # 保存
    df_f.to_csv(os.path.join(OUT_DIR, "cb_dblow_picks_today.csv"),
                index=False, encoding="utf-8-sig")
    print(f"\n  清单 -> {os.path.join(OUT_DIR, 'cb_dblow_picks_today.csv')}")


def main():
    part1_market_index()
    part2_current_picks(top_n=30)


if __name__ == "__main__":
    main()
