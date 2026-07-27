"""
定投机制对比 — DIV70/GEM30 vs. 纯 DIV vs. 纯 GEM
==================================================
场景假设 (用户真实打法: 2018 年起定投 bank+GEM, 7 年 +50%):
  - 月定投 / 每 2 周定投 / 每周定投
  - 一次性梭哈 (lump sum)
  - 估值加权定投: PE 分位低时加倍投, 高时减半
  - 定投 + 季度再平衡混合

每月投入 ¥5000, 对比 CAGR / MDD / IRR 等指标.
区间: 2019-01 → 2026-04 (7.3 年, DIV ETF 上市起点)
"""
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MARKET = os.path.join(ROOT, "data", "market_cache")
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")

MONTHLY_INVEST = 5000.0     # 每月投入
TRADE_COST = (13+43)/10000   # 56bp 往返


def load(fp, col):
    df = pd.read_csv(fp, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"])[["date","close"]].rename(columns={"close":col}).sort_values("date")


DIV = load(os.path.join(MARKET, "etf_512890.csv"), "DIV")
GEM = load(os.path.join(MARKET, "etf_159915.csv"), "GEM")
HS300 = load(os.path.join(MARKET, "hs300_daily_cache.csv"), "HS300")
df = DIV.merge(GEM, on="date", how="inner").merge(HS300, on="date", how="left")
df["HS300"] = df["HS300"].ffill()
df = df.reset_index(drop=True)
print(f"区间: {df['date'].min().date()} → {df['date'].max().date()}  {len(df)}日")


def rebal_schedule(freq):
    """返回投入日期的 bool mask (每期第一个工作日投入)"""
    d = df["date"]
    if freq == "W":
        return d.dt.to_period("W") != d.dt.to_period("W").shift()
    if freq == "2W":
        idx = (d.dt.to_period("W") != d.dt.to_period("W").shift())
        # 每隔一周: 取 idx=True 的位置第 0/2/4... 个
        true_pos = np.where(idx)[0]
        keep = np.zeros(len(df), dtype=bool)
        keep[true_pos[::2]] = True
        return pd.Series(keep, index=d.index)
    if freq == "M":
        return d.dt.to_period("M") != d.dt.to_period("M").shift()
    raise ValueError(freq)


def simulate_dca(w_div, w_gem, invest_per_period, freq,
                 quarterly_rebal=False, valuation_tilt=False):
    """
    定投主循环.
    w_div/w_gem: 目标权重 (仅用于新投入分配, 旧持仓不强制再平衡, 除非 quarterly_rebal)
    invest_per_period: 每期投入金额 (若 freq=W 每周投入 = MONTHLY_INVEST/4 略)
    valuation_tilt: 根据 HS300 PE 分位调整每期投入倍数 (冷买双倍, 热卖半倍)
    """
    mask_invest = rebal_schedule(freq)
    mask_qrebal = (df["date"].dt.to_period("Q") != df["date"].dt.to_period("Q").shift()) if quarterly_rebal else None

    # 估值倍数: 用 HS300 近3年分位作为冷热
    if valuation_tilt:
        # 自身历史 750 日 (3 年) 分位
        hs = df["HS300"]
        rank = hs.rolling(750, min_periods=250).rank(pct=True)
        # 分位低 <0.3 加倍, >0.7 减半, 中间 1x
        mult = pd.Series(1.0, index=hs.index)
        mult[rank < 0.3] = 2.0
        mult[rank > 0.7] = 0.5
    else:
        mult = pd.Series(1.0, index=df.index)

    shares_div = 0.0
    shares_gem = 0.0
    total_invested = 0.0
    daily_val = np.zeros(len(df))
    daily_cash = np.zeros(len(df))

    for i in range(len(df)):
        price_d = df["DIV"].iloc[i]
        price_g = df["GEM"].iloc[i]

        # 定期投入
        if mask_invest.iloc[i]:
            amt = invest_per_period * mult.iloc[i]
            # 目标权重分钱, 扣买入成本
            amt_div = amt * w_div
            amt_gem = amt * w_gem
            sh_d_new = amt_div * (1 - 13/10000) / price_d
            sh_g_new = amt_gem * (1 - 13/10000) / price_g
            shares_div += sh_d_new
            shares_gem += sh_g_new
            total_invested += amt

        # 季度再平衡 (仅在勾选)
        if mask_qrebal is not None and mask_qrebal.iloc[i]:
            total_val = shares_div * price_d + shares_gem * price_g
            if total_val > 0:
                tgt_div_val = total_val * w_div
                tgt_gem_val = total_val * w_gem
                new_sh_div = tgt_div_val / price_d
                new_sh_gem = tgt_gem_val / price_g
                # 换手量
                turnover = (abs(new_sh_div - shares_div) * price_d + abs(new_sh_gem - shares_gem) * price_g) / total_val
                cost = total_val * turnover * TRADE_COST * 0.5
                shares_div, shares_gem = new_sh_div, new_sh_gem
                # 扣成本视为"资金损耗", 等价减少股数
                val_after = total_val - cost
                scale = val_after / total_val if total_val > 0 else 1.0
                shares_div *= scale
                shares_gem *= scale

        daily_val[i] = shares_div * price_d + shares_gem * price_g

    # IRR 等化近似: 每期投入扣成本后最终市值
    final_val = daily_val[-1]
    total_ret = final_val / total_invested - 1 if total_invested > 0 else 0.0
    years = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25

    # 近似 IRR (现金流: 每期 -invest, 最后 +final)
    cfs = []
    t0 = df["date"].iloc[0]
    for i in range(len(df)):
        if mask_invest.iloc[i]:
            amt = invest_per_period * mult.iloc[i]
            t = (df["date"].iloc[i] - t0).days / 365.25
            cfs.append((t, -amt))
    cfs.append(((df["date"].iloc[-1] - t0).days / 365.25, final_val))

    def npv(r, cfs):
        return sum(cf / (1+r)**t for t, cf in cfs)

    # bisection IRR
    lo, hi = -0.99, 5.0
    try:
        for _ in range(80):
            m = (lo + hi) / 2
            if npv(m, cfs) > 0:
                lo = m
            else:
                hi = m
        irr = (lo + hi) / 2
    except Exception:
        irr = np.nan

    # 回撤 (相对已投入本金)
    series_val = pd.Series(daily_val, index=df["date"])
    # 累计投入
    cum_inv = pd.Series(0.0, index=df["date"])
    s = 0.0
    for i in range(len(df)):
        if mask_invest.iloc[i]:
            s += invest_per_period * mult.iloc[i]
        cum_inv.iloc[i] = s
    # 净值 = 市值 / 累计投入 (代表平均每 1 元本金现价值几元)
    nav = series_val / cum_inv.replace(0, np.nan)
    nav = nav.dropna()
    dd = nav / nav.cummax() - 1
    mdd = dd.min()

    return {
        "总投入": total_invested,
        "最终市值": final_val,
        "总回报": total_ret,
        "IRR": irr,
        "MDD_相对平均成本": mdd,
        "年数": years,
    }


print(f"\n每月投入: ¥{MONTHLY_INVEST:,.0f}\n")

configs = [
    ("月定投 DIV100",          1.0, 0.0, MONTHLY_INVEST,    "M", False, False),
    ("月定投 GEM100",          0.0, 1.0, MONTHLY_INVEST,    "M", False, False),
    ("月定投 DIV70/GEM30",     0.7, 0.3, MONTHLY_INVEST,    "M", False, False),
    ("月定投 DIV50/GEM50",     0.5, 0.5, MONTHLY_INVEST,    "M", False, False),
    ("月定投 DIV70/GEM30 + 季度再平衡",  0.7, 0.3, MONTHLY_INVEST, "M", True, False),
    ("2周定投 DIV70/GEM30",    0.7, 0.3, MONTHLY_INVEST/2, "2W", False, False),
    ("周定投 DIV70/GEM30",     0.7, 0.3, MONTHLY_INVEST/4, "W", False, False),
    ("月定投 DIV70/GEM30 + 估值加权",   0.7, 0.3, MONTHLY_INVEST,  "M", False, True),
    ("月定投 DIV70/GEM30 + 估值加权+再平衡", 0.7, 0.3, MONTHLY_INVEST, "M", True, True),
]

rows = []
print(f"{'策略':<38s} {'总投入':>10s} {'市值':>10s} {'收益':>8s} {'IRR':>7s} {'年数':>5s} {'相对MDD':>8s}")
print("-" * 100)
for cfg in configs:
    name, wd, wg, amt, freq, qr, vt = cfg
    r = simulate_dca(wd, wg, amt, freq, quarterly_rebal=qr, valuation_tilt=vt)
    rows.append({"策略":name, **r})
    print(f"  {name:<36s} ¥{r['总投入']/1e4:>7.1f}w ¥{r['最终市值']/1e4:>7.1f}w "
          f"{r['总回报']:>+7.1%} {r['IRR']:>+6.1%} {r['年数']:>4.1f}y {r['MDD_相对平均成本']:>+7.1%}")

pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "dca_compare.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 {os.path.join(OUT_DIR, 'dca_compare.csv')}")
print("\n对照你的案例: 2018 起定投 bank+GEM, 7年 +50% → IRR ~5.9% (按简单计算) / 实际更高")
