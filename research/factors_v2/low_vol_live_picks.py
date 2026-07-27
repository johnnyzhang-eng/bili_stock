"""
低波因子实测 — 真实成本回测 + 当前选股
========================================
原理：
  factor_raw = -rolling_std(log_return, window=60)
  每12个交易日调仓一次，从约3200只主板股中选波动率最低的20%（~640只）
  buffered：若已持仓且波动率仍在最低30%内则保留，减少换手

本脚本：
  1. 读取已有 period log，按每期换手扣除交易成本（56bp/单边成本法）
  2. 基于最新数据算出"如果今天调仓会选哪些股"（展示前30）
"""

import glob
import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STOCK_DIR  = os.path.join(ROOT, "data", "stock_data")
PERIODS    = os.path.join(ROOT, "research", "factors_v2", "output",
                          "low_vol_regime_periods.csv")

WINDOW    = 60
HOLD_STEP = 12
BDAYS     = 252
BUY_BP    = 13
SELL_BP   = 43
# 缓冲区实测换手率（estimate from enter=0.80, keep=0.70，历史约30%-40%）
TURNOVER_PER_REBAL = 0.35


def load_prices_recent(days: int = 90) -> pd.DataFrame:
    """只加载最近90个交易日的收盘价，用于计算当前vol。"""
    files = glob.glob(os.path.join(STOCK_DIR, "S[HZ]*.csv"))
    frames = []
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        code = sym[2:]
        # 主板过滤
        if sym.startswith("SH") and code[:3] in {"510","511","512","513","514",
                                                  "515","516","517","518","519","588","688","689"}: continue
        if sym.startswith("SH") and code[:2] == "56": continue
        if sym.startswith("SZ") and code[:3] in {"159","300","301","302"}: continue
        if code[:1] in {"8","4"}: continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig",
                             usecols=["日期","收盘","成交额"])
        except Exception:
            continue
        df.columns = ["date","close","amount"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        df = df.dropna(subset=["date","close"]).sort_values("date").tail(days)
        if len(df) < 40: continue
        df["stock_symbol"] = sym
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def part1_cost_adjusted():
    """Part 1: 扣除交易成本后的历史表现。"""
    print("="*65)
    print("【实测 Part 1】扣除交易成本后的年度表现")
    print("="*65)

    df = pd.read_csv(PERIODS, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year

    # 每期成本 = 换手率 × (买入费 + 卖出费) = 0.35 × 56bp = ~19.6bp
    cost_per_period = TURNOVER_PER_REBAL * (BUY_BP + SELL_BP) / 10000
    df["period_ret_net"] = df["period_ret"] - cost_per_period

    periods_per_year = BDAYS / HOLD_STEP

    print(f"\n  假设每期换手 {TURNOVER_PER_REBAL*100:.0f}%，买入{BUY_BP}bp + 卖出{SELL_BP}bp")
    print(f"  每期成本 ≈ {cost_per_period*10000:.1f}bp （年化约 {cost_per_period*periods_per_year*100:.1f}%）\n")

    print(f"  {'年份':<6s} {'毛年化':>8s} {'净年化':>8s} {'毛累计':>8s} {'净累计':>8s}  主导")
    print(f"  {'-'*52}")
    for yr, g in df.groupby("year"):
        r_g = np.clip(g["period_ret"].to_numpy(float), -0.99, None)
        r_n = np.clip(g["period_ret_net"].to_numpy(float), -0.99, None)
        yrs_eq = len(g) / periods_per_year
        cum_g = float(np.exp(np.log1p(r_g).sum()))
        cum_n = float(np.exp(np.log1p(r_n).sum()))
        cagr_g = cum_g ** (1/yrs_eq) - 1 if yrs_eq > 0 else np.nan
        cagr_n = cum_n ** (1/yrs_eq) - 1 if yrs_eq > 0 else np.nan
        dom = g["regime"].mode().iloc[0] if not g["regime"].mode().empty else ""
        print(f"  {int(yr):<6d} {cagr_g:>+8.2%} {cagr_n:>+8.2%} "
              f"{cum_g-1:>+8.2%} {cum_n-1:>+8.2%}  {dom}")

    # 全周期
    r_all_g = np.clip(df["period_ret"].to_numpy(float), -0.99, None)
    r_all_n = np.clip(df["period_ret_net"].to_numpy(float), -0.99, None)
    yrs_total = len(df) / periods_per_year
    cum_g_all = float(np.exp(np.log1p(r_all_g).sum()))
    cum_n_all = float(np.exp(np.log1p(r_all_n).sum()))
    cagr_g_all = cum_g_all ** (1/yrs_total) - 1
    cagr_n_all = cum_n_all ** (1/yrs_total) - 1

    # 最大回撤（净值序列）
    eq = np.exp(np.log1p(r_all_n).cumsum())
    dd = (eq / np.maximum.accumulate(eq)) - 1
    mdd = dd.min()

    # Calmar
    calmar = cagr_n_all / abs(mdd) if mdd < 0 else np.nan

    # 胜率（期）
    win_period = (df["period_ret_net"] > 0).mean()

    print(f"  {'-'*52}")
    print(f"\n  全周期（{yrs_total:.1f}年 / {len(df)}期）:")
    print(f"    毛年化: {cagr_g_all:+.2%}   毛累计: {cum_g_all-1:+.2%}")
    print(f"    净年化: {cagr_n_all:+.2%}   净累计: {cum_n_all-1:+.2%}")
    print(f"    最大回撤（净）: {mdd:.2%}   Calmar: {calmar:.2f}")
    print(f"    单期胜率: {win_period:.0%}")


def part2_current_picks():
    """Part 2: 今天调仓会选哪些股。"""
    print("\n\n" + "="*65)
    print("【实测 Part 2】今天调仓会选哪些股（波动率最低20%）")
    print("="*65)

    from research.factors_v2.stock_names import get_name_map
    try: name_map = get_name_map()
    except Exception: name_map = {}

    print("\n加载最近90天数据...", flush=True)
    prices = load_prices_recent(days=90)
    prices = prices.sort_values(["stock_symbol","date"])
    print(f"  {len(prices):,} 行, {prices['stock_symbol'].nunique()} 只股")

    print("计算60日波动率...", flush=True)
    prices["log_ret"] = prices.groupby("stock_symbol")["close"].transform(
        lambda s: np.log(s / s.shift(1)))
    prices["vol60"] = prices.groupby("stock_symbol")["log_ret"].transform(
        lambda s: s.rolling(60, min_periods=40).std())

    # 取最新日期每只股的vol
    latest_date = prices["date"].max()
    latest = prices[prices["date"] == latest_date].copy()
    latest = latest.dropna(subset=["vol60"])
    latest["amount_m"] = latest["amount"] / 1e6   # 百万
    # 简单流动性过滤：日成交额 > 2亿
    latest = latest[latest["amount_m"] > 200]

    # 年化波动率
    latest["vol_ann"] = latest["vol60"] * np.sqrt(252)

    # 排序：波动率最低
    latest = latest.sort_values("vol60")
    n_pool = len(latest)
    target_k = int(n_pool * 0.20)

    print(f"  截止日期: {latest_date.date()}")
    print(f"  池子大小（主板+流动性>2亿）: {n_pool}")
    print(f"  选股数（最低20%）: {target_k}")

    picks = latest.head(target_k).copy()
    picks["name"] = picks["stock_symbol"].apply(
        lambda s: name_map.get(s[2:], s))

    # ST过滤
    from research.factors_v2.stock_names import is_st
    picks = picks[~picks["name"].apply(is_st)]

    # 展示前30
    print(f"\n  ↓ 波动率最低的30只（共选 {target_k} 只）")
    print(f"  {'排名':<4s} {'代码':<10s} {'名称':<12s} {'现价':>7s} "
          f"{'年化波动':>8s} {'日成交(亿)':>10s}")
    print(f"  {'-'*60}")
    for i, (_, r) in enumerate(picks.head(30).iterrows(), 1):
        print(f"  {i:<4d} {r['stock_symbol']:<10s} {r['name']:<12s} "
              f"{r['close']:>7.2f} {r['vol_ann']*100:>7.1f}% "
              f"{r['amount']/1e8:>9.1f}亿")

    # 行业集中度（从名称粗判）
    print(f"\n  前{target_k}只涉及约 {picks['stock_symbol'].nunique()} 只不同代码")

    # 保存完整持仓
    out = os.path.join(ROOT, "research", "factors_v2", "output", "live",
                       f"low_vol_picks_{latest_date.date()}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    picks[["stock_symbol","name","close","vol_ann","amount_m"]].to_csv(
        out, index=False, encoding="utf-8-sig")
    print(f"\n  完整清单 -> {out}")


if __name__ == "__main__":
    part1_cost_adjusted()
    part2_current_picks()
