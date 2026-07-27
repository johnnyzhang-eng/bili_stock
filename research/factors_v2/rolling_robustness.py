"""
3 年滚动窗口鲁棒性 — DIV70/GEM30 季度再平衡 vs HS300
============================================================
每天前 3 年(756 日)计算 CAGR / MDD / Calmar, 画曲线 + 统计胜率.

输出:
  - rolling_3y.csv 时间序列
  - rolling_3y.png 三联图
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

df = pd.read_csv(os.path.join(OUT_DIR, "long_history.csv"), encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

for col in ["DIV","GEM","HS300"]:
    df[f"r_{col}"] = df[col].pct_change().fillna(0.0)


def simulate_qrebal(w_div, w_gem):
    dt = df["date"]
    rebal = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    v_div, v_gem = w_div, w_gem
    vals = np.zeros(len(df))
    for i in range(len(df)):
        if i > 0:
            v_div *= (1 + df["r_DIV"].iloc[i])
            v_gem *= (1 + df["r_GEM"].iloc[i])
        if rebal.iloc[i] and i > 0:
            tot = v_div + v_gem
            tgt_d = tot * w_div
            tgt_g = tot * w_gem
            turnover = (abs(tgt_d - v_div) + abs(tgt_g - v_gem)) / tot
            cost = tot * turnover * COST * 0.5
            v_div, v_gem = tgt_d, tgt_g
            scale = 1 - cost / tot if tot > 0 else 1
            v_div *= scale
            v_gem *= scale
        vals[i] = v_div + v_gem
    return pd.Series(vals, index=df.index)


nav_t = simulate_qrebal(0.7, 0.3)
nav_hs = df["HS300"]

WIN = 756   # 约 3 年
rows = []
for i in range(WIN, len(df)):
    n0_t, n1_t = nav_t.iloc[i-WIN], nav_t.iloc[i]
    n0_h, n1_h = nav_hs.iloc[i-WIN], nav_hs.iloc[i]
    yrs = (df["date"].iloc[i] - df["date"].iloc[i-WIN]).days / 365.25
    if yrs <= 0: continue
    cagr_t = (n1_t/n0_t)**(1/yrs) - 1
    cagr_h = (n1_h/n0_h)**(1/yrs) - 1
    win_t = nav_t.iloc[i-WIN:i+1]
    win_h = nav_hs.iloc[i-WIN:i+1]
    mdd_t = (win_t/win_t.cummax() - 1).min()
    mdd_h = (win_h/win_h.cummax() - 1).min()
    cal_t = cagr_t / abs(mdd_t) if mdd_t < 0 else 0
    cal_h = cagr_h / abs(mdd_h) if mdd_h < 0 else 0
    rows.append({
        "date": df["date"].iloc[i],
        "CAGR_port": cagr_t,
        "CAGR_hs": cagr_h,
        "MDD_port": mdd_t,
        "MDD_hs": mdd_h,
        "Calmar_port": cal_t,
        "Calmar_hs": cal_h,
        "alpha": cagr_t - cagr_h,
    })

r = pd.DataFrame(rows)
r.to_csv(os.path.join(OUT_DIR, "rolling_3y.csv"), index=False, encoding="utf-8-sig")

# 统计
print(f"滚动窗口: 3 年 ({WIN} 日)  样本: {len(r)} 个窗口")
print(f"\nCAGR:")
print(f"  DIV70/GEM30: 平均 {r['CAGR_port'].mean():+.2%}  中位 {r['CAGR_port'].median():+.2%}  "
      f"最坏 {r['CAGR_port'].min():+.2%}  最好 {r['CAGR_port'].max():+.2%}")
print(f"  HS300:       平均 {r['CAGR_hs'].mean():+.2%}  中位 {r['CAGR_hs'].median():+.2%}  "
      f"最坏 {r['CAGR_hs'].min():+.2%}  最好 {r['CAGR_hs'].max():+.2%}")

print(f"\nMDD:")
print(f"  DIV70/GEM30: 平均 {r['MDD_port'].mean():+.1%}  中位 {r['MDD_port'].median():+.1%}  "
      f"最坏 {r['MDD_port'].min():+.1%}")
print(f"  HS300:       平均 {r['MDD_hs'].mean():+.1%}  中位 {r['MDD_hs'].median():+.1%}  "
      f"最坏 {r['MDD_hs'].min():+.1%}")

win_rate_cagr = (r["alpha"] > 0).mean()
pos_cagr = (r["CAGR_port"] > 0).mean()
hs_pos = (r["CAGR_hs"] > 0).mean()
print(f"\n胜率 (DIV70/GEM30 CAGR > HS300): {win_rate_cagr:.1%}  ({(r['alpha']>0).sum()}/{len(r)})")
print(f"DIV70/GEM30 3年 CAGR > 0 的窗口占比: {pos_cagr:.1%}")
print(f"HS300       3年 CAGR > 0 的窗口占比: {hs_pos:.1%}")

# 图
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
ax1, ax2, ax3 = axes

ax1.plot(r["date"], r["CAGR_port"] * 100, label="DIV70/GEM30 季度", color="#d62728", linewidth=1.8)
ax1.plot(r["date"], r["CAGR_hs"] * 100, label="HS300", color="#7f7f7f", linewidth=1.4, alpha=0.7)
ax1.axhline(0, color="black", linewidth=0.5)
ax1.set_ylabel("3年滚动 CAGR (%)")
ax1.legend(loc="best")
ax1.set_title("DIV70/GEM30 季度再平衡 3 年滚动鲁棒性 (2013-06 ~ 2026-04)")
ax1.grid(alpha=0.3)

ax2.plot(r["date"], r["MDD_port"] * 100, label="DIV70/GEM30", color="#d62728", linewidth=1.8)
ax2.plot(r["date"], r["MDD_hs"] * 100, label="HS300", color="#7f7f7f", linewidth=1.4, alpha=0.7)
ax2.set_ylabel("3年滚动 MDD (%)")
ax2.legend(loc="best")
ax2.grid(alpha=0.3)

ax3.fill_between(r["date"], r["alpha"] * 100, 0,
                 where=(r["alpha"] > 0), color="#2ca02c", alpha=0.6, label="超额>0")
ax3.fill_between(r["date"], r["alpha"] * 100, 0,
                 where=(r["alpha"] <= 0), color="#d62728", alpha=0.6, label="超额<0")
ax3.axhline(0, color="black", linewidth=0.5)
ax3.set_ylabel("3年滚动超额 CAGR (%)")
ax3.set_xlabel("窗口终点")
ax3.legend(loc="best")
ax3.grid(alpha=0.3)

plt.tight_layout()
fp = os.path.join(OUT_DIR, "rolling_3y.png")
plt.savefig(fp, dpi=130)
print(f"\n  ← 图 {fp}")
print(f"  ← 数据 rolling_3y.csv")
