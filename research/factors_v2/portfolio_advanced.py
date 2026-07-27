"""
DIV70/GEM30 进阶测试
====================
1) 再平衡频率: W/M/Q/H/Y  —  成本 vs tracking 权衡
2) Target vol (年化 8%): 根据 20 日波动率缩放整体仓位
3) 回撤熔断: 组合 DD > 10% 减半仓
4) DIV/GEM 网格 (细分 step=0.05)
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

def load(fp, col):
    df = pd.read_csv(fp, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"])[["date","close"]].rename(columns={"close":col}).sort_values("date")

DIV = load(os.path.join(MARKET, "etf_512890.csv"), "DIV")
GEM = load(os.path.join(MARKET, "etf_159915.csv"), "GEM")
df = DIV.merge(GEM, on="date", how="inner").reset_index(drop=True)
rets = df[["DIV","GEM"]].pct_change().fillna(0.0)
rets.index = df["date"]

TRADE_COST = (13+43)/10000


def rebal_mask(freq):
    d = df["date"]
    if freq == "D":  return pd.Series(True, index=d.index)
    if freq == "W":  return d.dt.to_period("W") != d.dt.to_period("W").shift()
    if freq == "M":  return d.dt.to_period("M") != d.dt.to_period("M").shift()
    if freq == "Q":  return d.dt.to_period("Q") != d.dt.to_period("Q").shift()
    if freq == "H":  return (d.dt.month.isin([1,7])) & (d.dt.to_period("M") != d.dt.to_period("M").shift())
    if freq == "Y":  return (d.dt.month==1) & (d.dt.to_period("M") != d.dt.to_period("M").shift())
    if freq == "NEVER":
        m = pd.Series(False, index=d.index); m.iloc[0]=True; return m
    raise ValueError(freq)


def backtest(div_w, gem_w, freq="M", target_vol=None, dd_brake=None):
    w_tgt = np.array([div_w, gem_w])
    mask = rebal_mask(freq).tolist()
    cur = w_tgt.copy()
    daily_ret = np.zeros(len(df))
    expo = np.ones(len(df))   # 全仓占比
    peak = 1.0
    cum = 1.0
    # 波动率 (组合预估)
    port_ret_pre = rets.values @ w_tgt   # 不考虑仓位缩放的组合收益
    vol20 = pd.Series(port_ret_pre).rolling(20).std().values * np.sqrt(252)
    for i in range(len(df)):
        r = rets.iloc[i].values
        # 先确定今天仓位缩放
        if i == 0:
            e = 1.0
        else:
            e = expo[i-1]
            if target_vol is not None and not np.isnan(vol20[i-1]) and vol20[i-1]>0:
                e = min(1.0, target_vol / vol20[i-1])
            if dd_brake is not None:
                dd = cum/peak - 1
                if dd < -dd_brake:
                    e = e * 0.5
        expo[i] = e
        port_r = float((cur * r).sum()) * e
        cum = cum * (1 + port_r)
        peak = max(peak, cum)
        # 权重漂移
        cur = cur * (1 + r)
        cur = cur / cur.sum() if cur.sum() > 0 else w_tgt.copy()
        # 再平衡
        cost = 0.0
        if i > 0 and mask[i]:
            turnover = np.abs(cur - w_tgt).sum() / 2
            cost = turnover * TRADE_COST * e
            cur = w_tgt.copy()
        daily_ret[i] = port_r - cost
        cum = cum - cost   # 扣完 cost 的真实净值
        peak = max(peak, cum)
    eq = pd.Series((1 + daily_ret).cumprod(), index=df["date"])
    return eq, expo


def metrics(eq, name):
    ret = eq.pct_change().dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (1+total)**(1/years) - 1 if years > 0 else np.nan
    dd_ser = eq / eq.cummax() - 1
    mdd = dd_ser.min()
    vol = ret.std() * np.sqrt(252)
    sharpe = (cagr - 0.02) / vol if vol > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {"策略":name,"CAGR":cagr,"MDD":mdd,"Calmar":calmar,"Vol":vol,"Sharpe":sharpe,"Total":total}


rows = []

# 1) 再平衡频率对比 (DIV70/GEM30)
print("\n== 再平衡频率 (DIV70/GEM30) ==")
print(f"{'频率':<10s} {'CAGR':>8s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s} {'Vol':>6s}")
for freq in ["NEVER","Y","H","Q","M","W","D"]:
    eq,_ = backtest(0.7, 0.3, freq=freq)
    m = metrics(eq, f"70/30 @{freq}")
    rows.append(m)
    print(f"  {freq:<8s} {m['CAGR']:>+8.2%} {m['MDD']:>+8.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f} {m['Vol']:>5.1%}")

# 2) Target vol (月再平衡)
print("\n== Target vol 仓位缩放 (DIV70/GEM30 月再平衡) ==")
print(f"{'年化目标波动':<12s} {'CAGR':>8s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s} {'平均仓位':>7s}")
for tv in [0.06, 0.08, 0.10, 0.12]:
    eq, expo = backtest(0.7, 0.3, freq="M", target_vol=tv)
    m = metrics(eq, f"70/30 TV={tv:.0%}")
    rows.append(m)
    avg_e = float(np.mean(expo))
    print(f"  TV={tv:.0%}      {m['CAGR']:>+8.2%} {m['MDD']:>+8.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f}   {avg_e:>5.0%}")

# 3) DD brake (月再平衡)
print("\n== DD 熔断 (DIV70/GEM30 月再平衡) ==")
print(f"{'熔断阈值':<10s} {'CAGR':>8s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s}")
for dd in [0.05, 0.08, 0.10, 0.12, 0.15]:
    eq,_ = backtest(0.7, 0.3, freq="M", dd_brake=dd)
    m = metrics(eq, f"70/30 DD={dd:.0%}")
    rows.append(m)
    print(f"  DD<-{dd:.0%}    {m['CAGR']:>+8.2%} {m['MDD']:>+8.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f}")

# 4) DIV/GEM 细分网格 (月再平衡)
print("\n== DIV/GEM 网格 (月再平衡) step=0.05 ==")
print(f"{'DIV/GEM':<10s} {'CAGR':>8s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s}")
grid = []
for d in np.arange(0.5, 1.01, 0.05):
    d = round(d,2); g = round(1-d,2)
    eq,_ = backtest(d, g, freq="M")
    m = metrics(eq, f"DIV{int(d*100)}/GEM{int(g*100)}")
    grid.append(m)
    print(f"  {d:.2f}/{g:.2f}  {m['CAGR']:>+8.2%} {m['MDD']:>+8.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f}")
rows += grid

pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "portfolio_advanced.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 {os.path.join(OUT_DIR, 'portfolio_advanced.csv')}")
