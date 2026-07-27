"""
T2 双动量参数敏感性 — 确认不是单点过拟合
==============================================
T2 默认: 12 个月收益 + SMA200
扫: SMA 周期 (100/150/200/250) x 动量 lookback (126/189/252/315 日)
"""
import os, sys
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
COST = (13+43)/10000

df = pd.read_csv(os.path.join(OUT_DIR, "long_history_4asset.csv"), encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

for c in ["DIV","GEM","BOND","GOLD"]:
    df[f"r_{c}"] = df[c].pct_change().fillna(0.0)
df["STK"] = 0.7*df["DIV"] + 0.3*df["GEM"]

W = {"STK":0.30, "BOND":0.30, "GOLD":0.40}


def simulate(sma_p, mom_lb):
    df["STK_sma"] = df["STK"].rolling(sma_p).mean()
    df["retM_STK"] = df["STK"].pct_change(mom_lb)
    df["retM_GOLD"] = df["GOLD"].pct_change(mom_lb)

    dt = df["date"]
    mask = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()

    vals = {"DIV": W["STK"]*0.7, "GEM": W["STK"]*0.3, "BOND": W["BOND"], "GOLD": W["GOLD"]}
    series = np.zeros(len(df))

    for i in range(len(df)):
        if i > 0:
            for k in vals:
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])
        if mask.iloc[i] and i > 0:
            tot = sum(vals.values())
            w = dict(W)
            # STK 双滤
            rm = df["retM_STK"].iloc[i]
            above = df["STK"].iloc[i] > df["STK_sma"].iloc[i]
            if pd.isna(rm) or rm < 0 or not above:
                w["BOND"] += w["STK"]; w["STK"] = 0.0
            # GOLD 单滤
            rg = df["retM_GOLD"].iloc[i]
            if pd.isna(rg) or rg < 0:
                w["BOND"] += w["GOLD"]; w["GOLD"] = 0.0
            tgt = {"DIV": tot*w["STK"]*0.7, "GEM": tot*w["STK"]*0.3,
                   "BOND": tot*w["BOND"], "GOLD": tot*w["GOLD"]}
            tov = sum(abs(tgt[k]-vals[k]) for k in tgt) / tot
            cost = tot * tov * COST * 0.5
            vals = dict(tgt)
            scale = 1 - cost/tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())
    nav = pd.Series(series, index=df.index)
    ret = nav.iloc[-1]/nav.iloc[0] - 1
    yrs = (df["date"].iloc[-1]-df["date"].iloc[0]).days / 365.25
    cagr = (1+ret)**(1/yrs) - 1
    dr = nav.pct_change().dropna()
    sh = (dr.mean()*252 - 0.02) / (dr.std()*np.sqrt(252))
    dd = (nav/nav.cummax() - 1).min()
    cal = cagr / abs(dd) if dd < 0 else 0
    return cagr, dd, cal, sh

print(f"{'SMA':<6s}{'MOM':<8s}{'CAGR':>7s}{'MDD':>8s}{'Calmar':>8s}{'Sharpe':>8s}")
print("-" * 50)
rows = []
for sma in [100, 150, 200, 250]:
    for mom in [126, 189, 252, 315]:
        cagr, mdd, cal, sh = simulate(sma, mom)
        rows.append({"SMA":sma, "MOM":mom, "CAGR":cagr, "MDD":mdd, "Calmar":cal, "Sharpe":sh})
        print(f"  {sma:<4d}{mom:>4d}  {cagr:>+6.2%} {mdd:>+7.1%}  {cal:>6.2f}  {sh:>6.2f}")

out = pd.DataFrame(rows)
out.to_csv(os.path.join(OUT_DIR, "t2_sensitivity.csv"), index=False, encoding="utf-8-sig")
print(f"\nCAGR 范围: {out['CAGR'].min():+.2%} ~ {out['CAGR'].max():+.2%}  (σ={out['CAGR'].std():.2%})")
print(f"Calmar 范围: {out['Calmar'].min():.2f} ~ {out['Calmar'].max():.2f}")
print(f"所有 16 个组合的 Calmar >= {out['Calmar'].min():.2f} — 单点过拟合? {'否' if out['Calmar'].min() >= 0.4 else '是'}")
