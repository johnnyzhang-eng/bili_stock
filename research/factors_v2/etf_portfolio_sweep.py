"""
多 ETF 静态组合扫描 — DIV / HS300 / GEM / CSI1000 / 红利低波
=============================================================
月度再平衡至目标权重. 用 grid search 找出 Sharpe / Calmar 最优组合.
"""
import os
import sys
import itertools
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

etfs = {
    "DIV":    "etf_512890.csv",
    "HS300":  "etf_510300.csv",
    "GEM":    "etf_159915.csv",
    "CSI1K":  "etf_512100.csv",
}

df = None
for name, fp in etfs.items():
    d = load(os.path.join(MARKET, fp), name)
    df = d if df is None else df.merge(d, on="date", how="inner")

df = df.sort_values("date").reset_index(drop=True)
print(f"对齐 {len(df)} 日  {df['date'].min().date()} → {df['date'].max().date()}  {list(etfs.keys())}")

rets = df[list(etfs.keys())].pct_change().fillna(0.0)
rets.index = df["date"]

TRADE_COST = (13+43)/10000  # 全额换仓

# 月末再平衡
month_ends = df.groupby(df["date"].dt.to_period("M"))["date"].last().tolist()
month_end_mask = df["date"].isin(month_ends)


def backtest(weights):
    w = np.array(weights) / sum(weights)
    n = len(df)
    pos = np.zeros((n, len(w)))
    # 每月末恢复到目标权重; 月中漂移
    cur = w.copy()
    last_rebal = cur.copy()
    total_cost = 0.0
    daily_ret = np.zeros(n)
    for i in range(n):
        if i == 0:
            pos[i] = cur
            continue
        r = rets.iloc[i].values
        # 当日收益 = 昨日权重 * 当日涨跌
        port_ret = float((cur * r).sum())
        # 涨跌后漂移
        cur = cur * (1 + r)
        cur = cur / cur.sum() if cur.sum() > 0 else w.copy()
        daily_ret[i] = port_ret
        if month_end_mask.iloc[i]:
            # 计算换手
            turnover = np.abs(cur - w).sum() / 2
            cost = turnover * TRADE_COST
            daily_ret[i] -= cost
            total_cost += cost
            cur = w.copy()
        pos[i] = cur
    eq = pd.Series((1 + daily_ret).cumprod(), index=df["date"])
    return eq, total_cost


def metrics(eq, name, weights):
    ret = eq.pct_change().dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (1+total)**(1/years) - 1 if years > 0 else np.nan
    dd_ser = eq / eq.cummax() - 1
    mdd = dd_ser.min()
    vol = ret.std() * np.sqrt(252)
    sharpe = (cagr - 0.02) / vol if vol > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {"组合":name,"DIV":weights[0],"HS300":weights[1],"GEM":weights[2],"CSI1K":weights[3],
            "CAGR":cagr,"MDD":mdd,"Calmar":calmar,"Vol":vol,"Sharpe":sharpe,"Total":total}


# 单资产 baseline
rows = []
for i, name in enumerate(etfs.keys()):
    w = [0]*4; w[i] = 1
    eq,_ = backtest(w)
    rows.append(metrics(eq, f"{name} 持有", w))

# 双资产 DIV+X grid  (DIV权重从 0.3~0.9 步 0.1, 剩余给另一资产)
for j, name in enumerate(list(etfs.keys())[1:], start=1):
    for d_wt in np.arange(0.3, 1.0, 0.1):
        w = [0]*4; w[0] = round(d_wt,2); w[j] = round(1-d_wt,2)
        eq,_ = backtest(w)
        rows.append(metrics(eq, f"DIV{int(d_wt*100)}+{name}{int((1-d_wt)*100)}", w))

# 三元: DIV + HS300 + GEM (比例步 0.1)
for a in np.arange(0.3, 0.9, 0.1):
    for b in np.arange(0.0, 1.0-a+0.01, 0.1):
        c = 1 - a - b
        if c < 0.0 or c > 0.7: continue
        w = [round(a,2), round(b,2), round(c,2), 0]
        eq,_ = backtest(w)
        rows.append(metrics(eq, f"DIV{int(a*100)}/HS300{int(b*100)}/GEM{int(c*100)}", w))

# 四元: 等权
w = [0.25, 0.25, 0.25, 0.25]
eq,_ = backtest(w)
rows.append(metrics(eq, "四元等权 25/25/25/25", w))

# 四元: DIV重仓
for a in [0.5, 0.6, 0.7]:
    r = (1-a) / 3
    w = [a, r, r, r]
    eq,_ = backtest(w)
    rows.append(metrics(eq, f"DIV{int(a*100)}/其他各{int(r*100)}", w))


res = pd.DataFrame(rows)
res = res.sort_values("Calmar", ascending=False)
print("\n== 按 Calmar 排序 top 15 ==")
print(f"{'组合':<36s} {'CAGR':>7s} {'MDD':>7s} {'Calmar':>7s} {'Sharpe':>7s}")
print("-"*80)
for _, m in res.head(15).iterrows():
    print(f"  {m['组合']:<34s} {m['CAGR']:>+7.2%} {m['MDD']:>+7.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f}")

res2 = res.sort_values("Sharpe", ascending=False).head(10)
print("\n== 按 Sharpe 排序 top 10 ==")
print(f"{'组合':<36s} {'CAGR':>7s} {'MDD':>7s} {'Calmar':>7s} {'Sharpe':>7s}")
print("-"*80)
for _, m in res2.iterrows():
    print(f"  {m['组合']:<34s} {m['CAGR']:>+7.2%} {m['MDD']:>+7.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f}")

res.to_csv(os.path.join(OUT_DIR, "etf_portfolio_sweep.csv"), index=False, encoding="utf-8-sig")
print(f"\n  总 {len(res)} 组合  ← {os.path.join(OUT_DIR, 'etf_portfolio_sweep.csv')}")
