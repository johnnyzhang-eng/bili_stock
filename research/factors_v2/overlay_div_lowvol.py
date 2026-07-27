"""
红利低波 (512890) + 择时 overlay — 看能否在保留 12%+ CAGR 的前提下进一步压 MDD
================================================================================
Overlay 规则（每个单独测试）:
  A. MA trend: 收盘 < SMA60 → 空仓, 否则 100% 持有
  B. MA trend + buffer: 收盘 < SMA60*0.98 → 空仓, > SMA60*1.00 → 满仓 (滞回)
  C. HS300 regime: HS300 ret60 < -5% → 空仓, 否则持有
  D. 回撤熔断: 自身高点回撤 > 8% → 空仓, 回到高点 95% → 重新建仓
  E. 组合: MA trend 同时满足 HS300 regime
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

DIV  = pd.read_csv(os.path.join(MARKET, "etf_512890.csv"), encoding="utf-8-sig")
HS300 = pd.read_csv(os.path.join(MARKET, "hs300_daily_cache.csv"))

DIV.columns = [c.strip().replace("\ufeff","") for c in DIV.columns]
DIV["date"] = pd.to_datetime(DIV["date"])
DIV["close"] = pd.to_numeric(DIV["close"], errors="coerce")
DIV = DIV.dropna().sort_values("date").reset_index(drop=True)

HS300["date"] = pd.to_datetime(HS300["date"])
HS300 = HS300[["date","close"]].dropna().sort_values("date").reset_index(drop=True)

# 对齐交易日
df = DIV.merge(HS300.rename(columns={"close":"hs300"}), on="date", how="left")
df["hs300"] = df["hs300"].ffill()
df["ret"]   = df["close"].pct_change()
df["hs300_ret"] = df["hs300"].pct_change()

# 指标
df["sma60"]       = df["close"].rolling(60).mean()
df["sma120"]      = df["close"].rolling(120).mean()
df["hs300_ret60"] = df["hs300"].pct_change(60)
df["peak"]        = df["close"].cummax()
df["dd"]          = df["close"] / df["peak"] - 1

# 交易成本: 一次开仓 13bp, 一次清仓 43bp, 每次状态切换全额进出
TRADE_COST = (13 + 43) / 10000


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
    return {"策略":name,"年数":years,"CAGR":cagr,"MDD":mdd,"Calmar":calmar,"Vol":vol,"Sharpe":sharpe,"Total":total}


def apply_overlay(signal: pd.Series, name: str):
    """signal: 1=持有, 0=空仓"""
    pos = signal.shift(1).fillna(0)   # T+1 执行
    switches = (pos != pos.shift(1)).astype(int)
    # 每次切换扣一次总交易成本 (进出一趟)
    daily_ret = df["ret"] * pos - switches * TRADE_COST
    eq = (1 + daily_ret.fillna(0)).cumprod()
    eq.index = df["date"]
    n_switch = int(switches.sum())
    expo = float(pos.mean())
    m = metrics(eq, name)
    m["切换次数"] = n_switch
    m["持仓占比"] = expo
    return m, eq


def overlay_A():
    sig = (df["close"] > df["sma60"]).astype(int)
    sig[df["sma60"].isna()] = 1
    return apply_overlay(sig, "A: SMA60")


def overlay_B():
    # 滞回: 上穿 sma60 进场, 下穿 sma60*0.97 出场
    pos = np.zeros(len(df))
    for i in range(1, len(df)):
        if np.isnan(df["sma60"].iloc[i]):
            pos[i] = 1; continue
        if pos[i-1] == 1:
            pos[i] = 0 if df["close"].iloc[i] < df["sma60"].iloc[i] * 0.97 else 1
        else:
            pos[i] = 1 if df["close"].iloc[i] > df["sma60"].iloc[i] else 0
    return apply_overlay(pd.Series(pos, index=df.index), "B: SMA60滞回(-3%)")


def overlay_C():
    sig = (df["hs300_ret60"] > -0.05).astype(int)
    sig[df["hs300_ret60"].isna()] = 1
    return apply_overlay(sig, "C: HS300 ret60>-5%")


def overlay_D():
    pos = np.zeros(len(df))
    pos[0] = 1
    in_mkt = True
    peak_when_out = 0
    for i in range(1, len(df)):
        dd_now = df["dd"].iloc[i]
        if in_mkt:
            if dd_now < -0.08:
                in_mkt = False
                peak_when_out = df["peak"].iloc[i]
                pos[i] = 0
            else:
                pos[i] = 1
        else:
            if df["close"].iloc[i] > peak_when_out * 0.95:
                in_mkt = True
                pos[i] = 1
            else:
                pos[i] = 0
    return apply_overlay(pd.Series(pos, index=df.index), "D: DD熔断(-8%/回95%)")


def overlay_E():
    s_a = (df["close"] > df["sma60"]).astype(int)
    s_a[df["sma60"].isna()] = 1
    s_c = (df["hs300_ret60"] > -0.05).astype(int)
    s_c[df["hs300_ret60"].isna()] = 1
    sig = ((s_a + s_c) == 2).astype(int)
    return apply_overlay(sig, "E: SMA60 & HS300趋势")


def overlay_F():
    # 激进: sma120 趋势
    sig = (df["close"] > df["sma120"]).astype(int)
    sig[df["sma120"].isna()] = 1
    return apply_overlay(sig, "F: SMA120")


# 基准: 纯持有
base_eq = (1 + df["ret"].fillna(0)).cumprod(); base_eq.index = df["date"]
base_m = metrics(base_eq, "Baseline: 512890 买入持有")

results = [base_m]
for fn in [overlay_A, overlay_B, overlay_C, overlay_D, overlay_E, overlay_F]:
    m, _ = fn()
    results.append(m)

print(f"\n{'策略':<32s} {'年数':>5s} {'CAGR':>8s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s} {'Total':>9s} {'切换':>5s} {'持仓%':>6s}")
print("-" * 108)
for m in results:
    sw = m.get("切换次数",0); ex = m.get("持仓占比",1.0)
    print(f"  {m['策略']:<30s} {m['年数']:>4.1f}y {m['CAGR']:>+8.2%} {m['MDD']:>+8.2%} {m['Calmar']:>7.2f} {m['Sharpe']:>7.2f} {m['Total']:>+9.2%} {sw:>5d} {ex:>5.0%}")

pd.DataFrame(results).to_csv(os.path.join(OUT_DIR, "overlay_div_lowvol.csv"),
                              index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 {os.path.join(OUT_DIR, 'overlay_div_lowvol.csv')}")
