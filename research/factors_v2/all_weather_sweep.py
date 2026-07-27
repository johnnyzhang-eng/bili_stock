"""
B 方案精调 — 股/债/金 比例 sweep
===================================
在 B (40/40/20) 周围扫, 目标: CAGR 接近 E 基准 (9.3%), Calmar 仍 ≥ 0.30.
也加一个黄金趋势 overlay 的变体 (GOLD < SMA200 时关掉).
"""
import os, sys
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import numpy as np
import pandas as pd
import itertools

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")

COST = (13+43)/10000

df = pd.read_csv(os.path.join(OUT_DIR, "long_history_4asset.csv"), encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

for c in ["DIV","GEM","BOND","GOLD"]:
    df[f"r_{c}"] = df[c].pct_change().fillna(0.0)

# 预计算黄金 SMA200
df["GOLD_sma200"] = df["GOLD"].rolling(200).mean()
df["GOLD_trend"] = df["GOLD"] > df["GOLD_sma200"]


def simulate(w_stk, w_bond, w_gold, rebal="Q", gold_overlay=False):
    """股内部固定 DIV70/GEM30"""
    dt = df["date"]
    if rebal == "Q":
        mask_rb = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    elif rebal == "M":
        mask_rb = dt.dt.to_period("M") != dt.dt.to_period("M").shift()

    vals = {
        "DIV": w_stk * 0.7,
        "GEM": w_stk * 0.3,
        "BOND": w_bond,
        "GOLD": w_gold,
    }
    series = np.zeros(len(df))
    turnover = 0.0

    for i in range(len(df)):
        if i > 0:
            for k in vals:
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])
        if mask_rb.iloc[i] and i > 0:
            tot = sum(vals.values())
            # overlay: 若黄金不在 SMA200 上方, 把金配给债
            if gold_overlay:
                trend_on = bool(df["GOLD_trend"].iloc[i]) if not pd.isna(df["GOLD_trend"].iloc[i]) else True
                eff_gold = w_gold if trend_on else 0.0
                eff_bond = w_bond + (w_gold - eff_gold)
            else:
                eff_gold = w_gold
                eff_bond = w_bond
            tgt = {
                "DIV":  tot * w_stk * 0.7,
                "GEM":  tot * w_stk * 0.3,
                "BOND": tot * eff_bond,
                "GOLD": tot * eff_gold,
            }
            tov = sum(abs(tgt[k] - vals[k]) for k in tgt) / tot
            cost = tot * tov * COST * 0.5
            turnover += tov
            vals = dict(tgt)
            scale = 1 - cost / tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())

    nav = pd.Series(series, index=df.index)
    return nav, turnover


def metrics(nav):
    ret = nav.iloc[-1] / nav.iloc[0] - 1
    yrs = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25
    cagr = (1 + ret)**(1/yrs) - 1
    dr = nav.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sh = (dr.mean()*252 - 0.02) / vol if vol > 0 else 0
    dd = nav / nav.cummax() - 1
    mdd = dd.min()
    cal = cagr / abs(mdd) if mdd < 0 else 0
    # 2015 股灾区间 DD
    m15 = (df["date"] >= "2015-06-12") & (df["date"] <= "2016-01-31")
    sub = nav[m15.values]
    dd15 = (sub / sub.cummax() - 1).min() if len(sub) > 10 else np.nan
    return cagr, vol, mdd, cal, sh, dd15


# sweep
print(f"{'股':>4s} {'债':>4s} {'金':>4s} {'CAGR':>7s} {'波动':>5s} {'MDD':>7s} {'Calmar':>7s} {'Sharpe':>6s} {'15股灾':>8s} {'换手':>5s}")
print("-" * 80)
rows = []
for w_stk, w_bond in itertools.product(
    [0.30, 0.40, 0.50, 0.60, 0.70],
    [0.20, 0.30, 0.40, 0.50, 0.60],
):
    w_gold = 1.0 - w_stk - w_bond
    if w_gold < 0.10 or w_gold > 0.40: continue

    nav, tov = simulate(w_stk, w_bond, w_gold, rebal="Q")
    cagr, vol, mdd, cal, sh, dd15 = metrics(nav)
    rows.append({
        "w_stk": w_stk, "w_bond": w_bond, "w_gold": w_gold,
        "CAGR":cagr, "Vol":vol, "MDD":mdd, "Calmar":cal, "Sharpe":sh, "DD2015":dd15, "Turnover":tov,
    })
    print(f"  {w_stk:>3.0%} {w_bond:>3.0%} {w_gold:>3.0%} {cagr:>+6.2%} {vol:>4.1%} {mdd:>+6.1%} "
          f"{cal:>6.2f} {sh:>5.2f} {dd15:>+7.1%} {tov:>4.1f}")

out = pd.DataFrame(rows).sort_values("Calmar", ascending=False)
out.to_csv(os.path.join(OUT_DIR, "all_weather_sweep.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 all_weather_sweep.csv")

print("\nTop 5 by Calmar:")
print(out.head(5)[["w_stk","w_bond","w_gold","CAGR","MDD","Calmar","Sharpe","DD2015"]].to_string(index=False))
print("\nTop 5 by CAGR (Calmar >= 0.30):")
t5 = out[out["Calmar"] >= 0.30].sort_values("CAGR", ascending=False).head(5)
print(t5[["w_stk","w_bond","w_gold","CAGR","MDD","Calmar","Sharpe","DD2015"]].to_string(index=False))

# overlay 对比: 选 Top 1 权重跑 gold-overlay 版
print("\n" + "=" * 80)
print("黄金 SMA200 overlay (GOLD 跌破 200日均线 → 转债) vs 不 overlay")
print("=" * 80)
best = out.iloc[0]
w_stk, w_bond, w_gold = best["w_stk"], best["w_bond"], best["w_gold"]
print(f"  权重: 股 {w_stk:.0%} / 债 {w_bond:.0%} / 金 {w_gold:.0%}")
nav0, _ = simulate(w_stk, w_bond, w_gold, rebal="Q", gold_overlay=False)
nav1, _ = simulate(w_stk, w_bond, w_gold, rebal="Q", gold_overlay=True)
c0 = metrics(nav0); c1 = metrics(nav1)
print(f"  {'无 overlay':<20s} CAGR {c0[0]:+.2%}  MDD {c0[2]:+.1%}  Calmar {c0[3]:.2f}  Sharpe {c0[4]:.2f}")
print(f"  {'黄金 SMA200 overlay':<20s} CAGR {c1[0]:+.2%}  MDD {c1[2]:+.1%}  Calmar {c1[3]:.2f}  Sharpe {c1[4]:.2f}")
