"""
All-Weather 30/30/40 3 年滚动鲁棒性
==========================================
对比:
  - 30% 股(DIV/GEM 7:3) / 30% 债 / 40% 金, 季度再平衡  ← 新胜出
  - DIV70/GEM30 季度 (长周期基准)
  - HS300
"""
import os, sys
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei","SimHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")

COST = (13+43)/10000

df = pd.read_csv(os.path.join(OUT_DIR, "long_history_4asset.csv"), encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)
for c in ["DIV","GEM","BOND","GOLD"]:
    df[f"r_{c}"] = df[c].pct_change().fillna(0.0)


def simulate(w_stk, w_bond, w_gold):
    dt = df["date"]
    rebal = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    vals = {"DIV": w_stk*0.7, "GEM": w_stk*0.3, "BOND": w_bond, "GOLD": w_gold}
    series = np.zeros(len(df))
    for i in range(len(df)):
        if i > 0:
            for k in vals:
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])
        if rebal.iloc[i] and i > 0:
            tot = sum(vals.values())
            tgt = {"DIV": tot*w_stk*0.7, "GEM": tot*w_stk*0.3, "BOND": tot*w_bond, "GOLD": tot*w_gold}
            tov = sum(abs(tgt[k]-vals[k]) for k in tgt) / tot
            cost = tot * tov * COST * 0.5
            vals = dict(tgt)
            scale = 1 - cost/tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())
    return pd.Series(series, index=df.index)


nav_aw = simulate(0.30, 0.30, 0.40)
nav_dg = simulate(1.0, 0.0, 0.0)  # 对应 DIV70/GEM30 (无债金) via w_stk=1
nav_hs = df["HS300"]

# 3 年滚动
WIN = 756
rows = []
for i in range(WIN, len(df)):
    def cagr(s, ii):
        return (s.iloc[ii] / s.iloc[ii-WIN])**(365.25/(df["date"].iloc[ii] - df["date"].iloc[ii-WIN]).days) - 1
    def mdd(s, ii):
        w = s.iloc[ii-WIN:ii+1]
        return (w / w.cummax() - 1).min()
    rows.append({
        "date": df["date"].iloc[i],
        "CAGR_aw": cagr(nav_aw, i),
        "CAGR_dg": cagr(nav_dg, i),
        "CAGR_hs": cagr(nav_hs, i),
        "MDD_aw": mdd(nav_aw, i),
        "MDD_dg": mdd(nav_dg, i),
        "MDD_hs": mdd(nav_hs, i),
    })
r = pd.DataFrame(rows)
r["alpha_vs_hs"] = r["CAGR_aw"] - r["CAGR_hs"]
r["alpha_vs_dg"] = r["CAGR_aw"] - r["CAGR_dg"]

r.to_csv(os.path.join(OUT_DIR, "all_weather_rolling_3y.csv"), index=False, encoding="utf-8-sig")

print(f"滚动 3 年窗口: {len(r)} 个")
print(f"\nCAGR 统计:")
print(f"  AW 30/30/40: 平均 {r['CAGR_aw'].mean():+.2%}  中位 {r['CAGR_aw'].median():+.2%}  "
      f"最坏 {r['CAGR_aw'].min():+.2%}  最好 {r['CAGR_aw'].max():+.2%}")
print(f"  DIV70/GEM30: 平均 {r['CAGR_dg'].mean():+.2%}  中位 {r['CAGR_dg'].median():+.2%}  "
      f"最坏 {r['CAGR_dg'].min():+.2%}  最好 {r['CAGR_dg'].max():+.2%}")
print(f"  HS300:       平均 {r['CAGR_hs'].mean():+.2%}  中位 {r['CAGR_hs'].median():+.2%}  "
      f"最坏 {r['CAGR_hs'].min():+.2%}  最好 {r['CAGR_hs'].max():+.2%}")

print(f"\nMDD 统计:")
print(f"  AW 30/30/40: 平均 {r['MDD_aw'].mean():+.1%}  最坏 {r['MDD_aw'].min():+.1%}")
print(f"  DIV70/GEM30: 平均 {r['MDD_dg'].mean():+.1%}  最坏 {r['MDD_dg'].min():+.1%}")
print(f"  HS300:       平均 {r['MDD_hs'].mean():+.1%}  最坏 {r['MDD_hs'].min():+.1%}")

print(f"\n胜率:")
print(f"  AW 跑赢 HS300: {(r['alpha_vs_hs']>0).mean():.1%}")
print(f"  AW 跑赢 DIV70/GEM30: {(r['alpha_vs_dg']>0).mean():.1%}")
print(f"  AW 3 年不亏: {(r['CAGR_aw']>0).mean():.1%}")
print(f"  DIV70/GEM30 3 年不亏: {(r['CAGR_dg']>0).mean():.1%}")
print(f"  HS300 3 年不亏: {(r['CAGR_hs']>0).mean():.1%}")

# 绘图
fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
ax1, ax2, ax3 = axes

ax1.plot(r["date"], r["CAGR_aw"]*100, label="AW 30/30/40", color="#2ca02c", linewidth=1.8)
ax1.plot(r["date"], r["CAGR_dg"]*100, label="DIV70/GEM30 季度", color="#d62728", linewidth=1.4, alpha=0.8)
ax1.plot(r["date"], r["CAGR_hs"]*100, label="HS300", color="#7f7f7f", linewidth=1.2, alpha=0.6)
ax1.axhline(0, color="black", linewidth=0.5)
ax1.set_ylabel("3 年滚动 CAGR (%)")
ax1.legend(loc="best")
ax1.set_title("全天候 30/30/40 (股 30%, 债 30%, 金 40%) 3 年滚动鲁棒性")
ax1.grid(alpha=0.3)

ax2.plot(r["date"], r["MDD_aw"]*100, label="AW 30/30/40", color="#2ca02c", linewidth=1.8)
ax2.plot(r["date"], r["MDD_dg"]*100, label="DIV70/GEM30", color="#d62728", linewidth=1.4, alpha=0.8)
ax2.plot(r["date"], r["MDD_hs"]*100, label="HS300", color="#7f7f7f", linewidth=1.2, alpha=0.6)
ax2.set_ylabel("3 年滚动 MDD (%)")
ax2.legend(loc="best")
ax2.grid(alpha=0.3)

ax3.fill_between(r["date"], r["alpha_vs_hs"]*100, 0,
                 where=(r["alpha_vs_hs"]>0), color="#2ca02c", alpha=0.6, label="超 HS300 >0")
ax3.fill_between(r["date"], r["alpha_vs_hs"]*100, 0,
                 where=(r["alpha_vs_hs"]<=0), color="#d62728", alpha=0.6, label="超 HS300 <0")
ax3.axhline(0, color="black", linewidth=0.5)
ax3.set_ylabel("AW vs HS300 超额 CAGR (%)")
ax3.set_xlabel("窗口终点")
ax3.legend(loc="best")
ax3.grid(alpha=0.3)

plt.tight_layout()
fp = os.path.join(OUT_DIR, "all_weather_rolling_3y.png")
plt.savefig(fp, dpi=130)
print(f"\n  ← 图 {fp}")

# 绘净值对比图
fig2, ax = plt.subplots(figsize=(14, 6))
ax.plot(df["date"], nav_aw, label="AW 30/30/40", color="#2ca02c", linewidth=1.8)
ax.plot(df["date"], nav_dg, label="DIV70/GEM30 季度", color="#d62728", linewidth=1.4)
ax.plot(df["date"], nav_hs, label="HS300", color="#7f7f7f", linewidth=1.2, alpha=0.7)
ax.set_yscale("log")
ax.set_ylabel("累计净值 (log)")
ax.set_title("全天候 30/30/40 vs DIV70/GEM30 vs HS300 (16 年)")
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
fp2 = os.path.join(OUT_DIR, "all_weather_nav_compare.png")
plt.savefig(fp2, dpi=130)
print(f"  ← 图 {fp2}")
