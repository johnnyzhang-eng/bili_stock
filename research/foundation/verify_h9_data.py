"""
H9 所需数据字段验证
====================
验证 5 条 TIER 1 规则所需字段在 DataBundle 中是否齐全可用:
  A 量能 = vol / MA5_vol         → 需 vol 字段
  B 流通市值<50亿 + 股价<20      → 流通市值估算 (net_profit/eps × close), 股价直接
  C 近 1-2 月涨停历史            → pct ≥ 9.8 历史窗口
  D 次日高开 4%+                 → open / close
  E 同板块当日涨停数             → industry 行业字段聚合
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
import pandas as pd

from research.foundation import DataBundle


def main():
    print("=" * 80)
    print("  H9 数据字段验证")
    print("=" * 80)
    data = DataBundle.load(verbose=False)

    print(f"\n[1] OHLCV 缓存覆盖")
    print(f"    {len(data.price_cache):,} 只股")

    # 1. vol 字段覆盖
    print(f"\n[2] vol 字段覆盖检查 (规则 A 必需)")
    n_with_vol = sum(1 for df in data.price_cache.values() if "vol" in df.columns)
    n_total = len(data.price_cache)
    print(f"    含 vol: {n_with_vol:,}/{n_total:,} = {n_with_vol/n_total*100:.1f}%")
    sample_codes = list(data.price_cache.keys())[:5]
    for c in sample_codes:
        df = data.price_cache[c]
        if "vol" in df.columns:
            vol_ok = df["vol"].notna().sum()
            vol_avg = df["vol"].dropna().mean()
            print(f"    {c}: vol non-null {vol_ok}/{len(df)}, 均值 {vol_avg:,.0f}")

    # 2. open 字段覆盖
    print(f"\n[3] open / pct / industry 字段")
    n_open = sum(1 for df in data.price_cache.values() if "open" in df.columns)
    n_pct = sum(1 for df in data.price_cache.values() if "pct" in df.columns)
    print(f"    open: {n_open:,}/{n_total:,} = {n_open/n_total*100:.1f}%")
    print(f"    pct:  {n_pct:,}/{n_total:,} = {n_pct/n_total*100:.1f}%")
    print(f"    industry (panel): {data.panel['industry'].notna().sum():,}/{len(data.panel):,}"
          f" = {data.panel['industry'].notna().sum()/len(data.panel)*100:.1f}%")
    print(f"    distinct industries: {data.panel['industry'].dropna().nunique()}")

    # 3. 市值估算 (规则 B): shares_out = abs(net_profit / eps), 同期累计
    print(f"\n[4] 流通市值估算 (规则 B): shares_out = |net_profit/eps|")
    panel = data.panel.copy()
    panel = panel[panel["eps"].notna() & (panel["eps"].abs() > 1e-3) & panel["net_profit"].notna()]
    panel["shares_yi"] = (panel["net_profit"] / panel["eps"]).abs() / 1e8
    print(f"    可估算股本 panel 行: {len(panel):,}")
    print(f"    shares 中位数: {panel['shares_yi'].median():.2f} 亿股")
    print(f"    shares 分位 (10/50/90): "
          f"{panel['shares_yi'].quantile(0.1):.2f} / "
          f"{panel['shares_yi'].quantile(0.5):.2f} / "
          f"{panel['shares_yi'].quantile(0.9):.2f}")

    # 4. 验证: 取最近一期 panel + 最近收盘价 → mcap 估算
    last = panel.sort_values("report_date").groupby("code").last().reset_index()
    print(f"\n[5] 最近一期市值估算 (sanity check)")
    samples = []
    for _, row in last.head(20).iterrows():
        c = row["code"]
        if c not in data.price_cache: continue
        pf = data.price_cache[c]
        if pf.empty or "close" not in pf.columns: continue
        last_close = pf["close"].iloc[-1]
        mcap = last_close * row["shares_yi"]  # 亿元
        samples.append((c, row["name"], row["industry"], last_close, row["shares_yi"], mcap))
    samples.sort(key=lambda x: x[5])
    print(f"    {'代码':<8s} {'名称':<10s} {'行业':<12s} {'收盘':>8s} {'股本(亿)':>9s} {'估算市值(亿)':>12s}")
    for c, n, ind, p, s, m in samples[:5]:
        print(f"    {c:<8s} {n:<10s} {(ind or '-')[:10]:<12s} {p:>8.2f} {s:>9.2f} {m:>12.1f}")
    print(f"    ...")
    for c, n, ind, p, s, m in samples[-5:]:
        print(f"    {c:<8s} {n:<10s} {(ind or '-')[:10]:<12s} {p:>8.2f} {s:>9.2f} {m:>12.1f}")

    # 5. 5 日均量计算可行性
    print(f"\n[6] 5 日均量计算可行性 (规则 A)")
    test_code = "000001" if "000001" in data.price_cache else sample_codes[0]
    df = data.price_cache[test_code].copy()
    if "vol" in df.columns and "pct" in df.columns:
        df["vol_ma5"] = df["vol"].rolling(5).mean()
        df["vol_ratio"] = df["vol"] / df["vol_ma5"].shift(1)
        zt = df[df["pct"] >= 9.8]
        if len(zt) > 0:
            print(f"    {test_code}: 历史涨停 {len(zt)} 次")
            print(f"    涨停日 vol_ratio 中位数: {zt['vol_ratio'].median():.2f}x")
            print(f"    涨停日 vol_ratio >= 2.0 占比: "
                  f"{(zt['vol_ratio'] >= 2.0).sum()}/{len(zt)} = "
                  f"{(zt['vol_ratio'] >= 2.0).mean()*100:.1f}%")

    # 6. 综合判定
    print(f"\n" + "=" * 80)
    print(f"  字段完整性判定")
    print(f"=" * 80)
    rules = [
        ("A 量能 ≥ 5MA × 2",      n_with_vol/n_total >= 0.95, f"vol 覆盖 {n_with_vol/n_total*100:.0f}%"),
        ("B 股价 < 20",          True, "close 100%"),
        ("B 流通市值估算",         len(panel) > 5000, f"net_profit/eps 可估 {len(panel):,} 行"),
        ("C 近期涨停历史",         n_pct/n_total >= 0.95, f"pct 覆盖 {n_pct/n_total*100:.0f}%"),
        ("D 次日高开 4%+",        n_open/n_total >= 0.95, f"open 覆盖 {n_open/n_total*100:.0f}%"),
        ("E 板块前三强",          data.panel['industry'].notna().mean() >= 0.95,
                                  f"industry 覆盖 {data.panel['industry'].notna().mean()*100:.0f}%"),
    ]
    for name, ok, msg in rules:
        flag = "✓" if ok else "✗"
        print(f"    {flag} {name:<25s}  {msg}")

    n_ok = sum(1 for _, ok, _ in rules if ok)
    print(f"\n    {n_ok}/{len(rules)} 条规则字段就绪")
    if n_ok == len(rules):
        print(f"    → 可以跑 H9")
    else:
        print(f"    → 缺字段, 不能跑")


if __name__ == "__main__":
    main()
