"""
对比：自制 K=15 低波 vs 红利低波ETF(512890) vs 沪深300 ETF(510300)
共同期: 各ETF上市后
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
CACHE   = os.path.join(ROOT, "data", "market_cache")


def fetch_etf(code: str, name: str) -> pd.DataFrame:
    """用 akshare 拉ETF历史日线，缓存到本地。"""
    cache_file = os.path.join(CACHE, f"etf_{code}.csv")
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, encoding="utf-8-sig")
        df["date"] = pd.to_datetime(df["date"])
        return df

    import akshare as ak
    print(f"  拉取 {code} {name}...", flush=True)
    raw = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="hfq")
    date_col  = next((c for c in raw.columns if "日期" in c), raw.columns[0])
    close_col = next((c for c in raw.columns if "收盘" in c), None)
    df = pd.DataFrame({
        "date": pd.to_datetime(raw[date_col]),
        "close": pd.to_numeric(raw[close_col], errors="coerce"),
    }).dropna().sort_values("date")
    df.to_csv(cache_file, index=False, encoding="utf-8-sig")
    print(f"    {len(df)} 天  {df['date'].min().date()} - {df['date'].max().date()}")
    return df


def compute_metrics(df: pd.DataFrame, name: str, start: pd.Timestamp = None):
    s = df.copy()
    if start is not None:
        s = s[s["date"] >= start]
    if len(s) < 100:
        return None
    s = s.sort_values("date")
    s["ret"] = s["close"].pct_change()
    s = s.dropna()

    total_ret = s["close"].iloc[-1] / s["close"].iloc[0] - 1
    years = (s["date"].iloc[-1] - s["date"].iloc[0]).days / 365.25
    cagr  = (1 + total_ret) ** (1/years) - 1 if years > 0 else np.nan

    # 回撤
    eq  = s["close"] / s["close"].iloc[0]
    dd  = eq / eq.cummax() - 1
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan

    # 波动率 + Sharpe（无风险利率2%）
    vol = s["ret"].std() * np.sqrt(252)
    sharpe = (cagr - 0.02) / vol if vol > 0 else np.nan

    # 胜率（日）
    win_day = (s["ret"] > 0).mean()

    return {
        "name": name,
        "start": s["date"].iloc[0].date(),
        "end":   s["date"].iloc[-1].date(),
        "years": years,
        "cagr":  cagr,
        "mdd":   mdd,
        "calmar": calmar,
        "vol":   vol,
        "sharpe": sharpe,
        "win_day": win_day,
        "total_ret": total_ret,
    }


def compute_annual(df: pd.DataFrame, name: str):
    s = df.copy().sort_values("date")
    s["year"] = s["date"].dt.year
    rows = []
    for yr, g in s.groupby("year"):
        if len(g) < 20: continue
        r = g["close"].iloc[-1] / g["close"].iloc[0] - 1
        rows.append({"year": yr, f"{name}": r})
    return pd.DataFrame(rows)


def main():
    # 拉取ETF数据
    etf_lv = fetch_etf("512890", "红利低波")
    etf_hs = fetch_etf("510300", "沪深300")

    # 自制K=15策略的净值
    k15_file = os.path.join(OUT_DIR, "low_vol_k15_periods.csv")
    k15 = pd.read_csv(k15_file, encoding="utf-8-sig")
    k15["date"] = pd.to_datetime(k15["date"])
    # 构造净值序列（把每期净值点作为date的收盘）
    k15 = k15.sort_values("date")
    k15_nav = pd.DataFrame({
        "date":  k15["date"],
        "close": k15["equity_net"],
    })

    # ── 汇总指标（共同起点）──────────────────────────────────────── #
    print(f"\n{'='*75}")
    print("  对比：K=15 低波 vs 红利低波ETF(512890) vs 沪深300 ETF(510300)")
    print(f"{'='*75}\n")

    # 共同起点 = max(三者起始)
    common_start = max(etf_lv["date"].min(), etf_hs["date"].min(), k15_nav["date"].min())
    print(f"  共同起点: {common_start.date()}")
    print(f"  截止:     {etf_lv['date'].max().date()}\n")

    metrics = []
    for df, nm in [(k15_nav, "K=15自制"), (etf_lv, "512890红利低波"), (etf_hs, "510300沪深300")]:
        m = compute_metrics(df, nm, start=common_start)
        if m: metrics.append(m)

    print(f"  {'标的':<18s} {'年化':>8s} {'最大回撤':>8s} {'Calmar':>7s} "
          f"{'波动率':>7s} {'Sharpe':>7s} {'累计':>8s}")
    print(f"  {'-'*68}")
    for m in metrics:
        print(f"  {m['name']:<18s} {m['cagr']:>+8.2%} {m['mdd']:>+8.2%} "
              f"{m['calmar']:>7.2f} {m['vol']:>6.1%} {m['sharpe']:>7.2f} "
              f"{m['total_ret']:>+8.2%}")

    # ── 年度收益对比 ──────────────────────────────────────────── #
    print(f"\n  年度收益对比（自然年涨跌）:\n")

    ann_k15 = compute_annual(k15_nav, "K=15自制")
    ann_lv  = compute_annual(etf_lv, "512890")
    ann_hs  = compute_annual(etf_hs, "510300")

    merged = (ann_k15.merge(ann_lv, on="year", how="outer")
                     .merge(ann_hs, on="year", how="outer")
                     .sort_values("year"))

    print(f"  {'年份':<6s} {'K=15自制':>10s} {'512890红利低波':>14s} {'510300沪深300':>14s}")
    print(f"  {'-'*50}")
    for _, r in merged.iterrows():
        def fmt(v):
            if pd.isna(v): return "    --    "
            return f"{v:+.2%}"
        print(f"  {int(r['year']):<6d} {fmt(r.get('K=15自制')):>10s} "
              f"{fmt(r.get('512890')):>14s} {fmt(r.get('510300')):>14s}")

    # ── 全周期各自起点的表现 ────────────────────────────────── #
    print(f"\n  各自从上市起的全期表现:\n")
    print(f"  {'标的':<18s} {'起点':<12s} {'年数':>5s} {'年化':>8s} {'最大回撤':>8s} {'累计':>8s}")
    print(f"  {'-'*65}")
    for df, nm in [(k15_nav, "K=15自制"), (etf_lv, "512890红利低波"), (etf_hs, "510300沪深300")]:
        m = compute_metrics(df, nm)
        if m:
            print(f"  {m['name']:<18s} {str(m['start']):<12s} {m['years']:>4.1f}年 "
                  f"{m['cagr']:>+8.2%} {m['mdd']:>+8.2%} {m['total_ret']:>+8.2%}")

    # 保存对比CSV
    merged.to_csv(os.path.join(OUT_DIR, "compare_etf_vs_lowvol.csv"),
                  index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
