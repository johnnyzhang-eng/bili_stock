"""
红利低波 (512890) ↔ 创业板 (159915) regime 轮动
================================================
思路: 低波红利是防守, 创业板是进攻. HS300 ret60 作为风险偏好代理.
规则对比:
  R1: ret60 > +5% → GEM, 否则 → DIV
  R2: ret60 > 0   → GEM, 否则 → DIV
  R3: ret60 > +10% → GEM, 否则 → DIV  (更保守)
  R4: 固定 50/50 (无轮动)
  R5: GEM 60日动量 > 512890 60日动量 → GEM, 否则 DIV
  R6: 两只中 6 月夏普高者 (每月重算)
基准:
  DIV buy&hold, GEM buy&hold
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

def load(fp):
    df = pd.read_csv(fp, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)

DIV  = load(os.path.join(MARKET, "etf_512890.csv")).rename(columns={"close":"div"})
GEM  = load(os.path.join(MARKET, "etf_159915.csv")).rename(columns={"close":"gem"})
HS300 = load(os.path.join(MARKET, "hs300_daily_cache.csv"))[["date","close"]].rename(columns={"close":"hs300"})

df = DIV.merge(GEM, on="date", how="inner").merge(HS300, on="date", how="left")
df["hs300"] = df["hs300"].ffill()
df["div_ret"] = df["div"].pct_change()
df["gem_ret"] = df["gem"].pct_change()
df["hs300_ret60"] = df["hs300"].pct_change(60)
df["div_mom60"] = df["div"].pct_change(60)
df["gem_mom60"] = df["gem"].pct_change(60)
df["div_mom120"] = df["div"].pct_change(120)
df["gem_mom120"] = df["gem"].pct_change(120)
print(f"对齐后 {len(df)} 日  {df['date'].min().date()} → {df['date'].max().date()}")

TRADE_COST = (13+43)/10000  # 每次全额换仓


def run(weights_div, label):
    """weights_div: pd.Series 0..1, 剩余给 GEM"""
    wd = weights_div.shift(1).fillna(0).clip(0,1)
    wg = 1 - wd
    switches = (wd.diff().abs().fillna(0))  # 比例变化近似成本
    daily = wd * df["div_ret"] + wg * df["gem_ret"] - switches * TRADE_COST
    eq = (1 + daily.fillna(0)).cumprod()
    eq.index = df["date"]
    return eq, label, float(wd.mean()), float(switches.sum())


def metrics(eq, name, **extra):
    ret = eq.pct_change().dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (1+total)**(1/years) - 1 if years > 0 else np.nan
    dd_ser = eq / eq.cummax() - 1
    mdd = dd_ser.min()
    vol = ret.std() * np.sqrt(252)
    sharpe = (cagr - 0.02) / vol if vol > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {"策略":name,"年数":years,"CAGR":cagr,"MDD":mdd,"Calmar":calmar,"Vol":vol,"Sharpe":sharpe,"Total":total, **extra}


# 基准
div_eq  = (1 + df["div_ret"].fillna(0)).cumprod(); div_eq.index = df["date"]
gem_eq  = (1 + df["gem_ret"].fillna(0)).cumprod(); gem_eq.index = df["date"]

rows = [
    metrics(div_eq, "DIV 买入持有"),
    metrics(gem_eq, "GEM 买入持有"),
]

def strat(wd, label):
    eq,_,avg,sw = run(wd, label)
    rows.append(metrics(eq, label, 平均DIV=avg, 切换量=sw))


# R1: >+5% GEM
sig = (df["hs300_ret60"] > 0.05)
strat((~sig).astype(float), "R1: hs300_ret60>+5%→GEM")
# R2: >0 GEM
sig = (df["hs300_ret60"] > 0.0)
strat((~sig).astype(float), "R2: hs300_ret60>0→GEM")
# R3: >+10% GEM
sig = (df["hs300_ret60"] > 0.10)
strat((~sig).astype(float), "R3: hs300_ret60>+10%→GEM")
# R4: 固定 50/50
strat(pd.Series(0.5, index=df.index), "R4: 固定 50/50")
# R5: 60d 动量谁强选谁
sig = df["gem_mom60"] > df["div_mom60"]
strat((~sig).astype(float), "R5: 60d 动量赢家")
# R6: 120d 动量
sig = df["gem_mom120"] > df["div_mom120"]
strat((~sig).astype(float), "R6: 120d 动量赢家")
# R7: 动量 + 同向 (仅 GEM 动量正且高于 DIV 才进 GEM, 否则 DIV)
sig = (df["gem_mom60"] > df["div_mom60"]) & (df["gem_mom60"] > 0)
strat((~sig).astype(float), "R7: GEM动量>DIV且正")
# R8: 60/40 混合 (稳一点)
strat(pd.Series(0.6, index=df.index), "R8: 固定 DIV60/GEM40")
# R9: 70/30
strat(pd.Series(0.7, index=df.index), "R9: 固定 DIV70/GEM30")

print(f"\n{'策略':<32s} {'年数':>5s} {'CAGR':>8s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s} {'Total':>9s}")
print("-"*90)
for m in rows:
    print(f"  {m['策略']:<30s} {m['年数']:>4.1f}y {m['CAGR']:>+8.2%} {m['MDD']:>+8.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f} {m['Total']:>+9.2%}")

pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "rotate_div_gem.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 {os.path.join(OUT_DIR, 'rotate_div_gem.csv')}")
