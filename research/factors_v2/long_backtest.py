"""
长周期回测 DIV70/GEM30 季度再平衡 — 2010-2026 (16 年)
===========================================================
分段输出 CAGR / MDD / Calmar / Sharpe, 并对比:
  - DIV100 / GEM100 / HS300
  - DIV70/GEM30 月度 / 季度 / 年度再平衡
  - DIV50/GEM50 / DIV60/GEM40

注意: 2010-2019 DIV 段为 中证红利 替身 (红利低波指数无长历史).
     2019+ 切换到真实红利低波 ETF 512890.
"""
import os, sys
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")

COST = (13+43)/10000  # 56bp 往返

df = pd.read_csv(os.path.join(OUT_DIR, "long_history.csv"), encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)
print(f"区间: {df['date'].min().date()} → {df['date'].max().date()}  {len(df)}日")

# 日收益
for col in ["DIV","GEM","HS300"]:
    df[f"r_{col}"] = df[col].pct_change().fillna(0.0)


def simulate(w_div, w_gem, rebal_freq):
    """rebal_freq: 'D'每日再平衡(纯权重), 'M'月度, 'Q'季度, 'Y'年度, 'NONE'不再平衡"""
    if rebal_freq == "D":
        daily_r = w_div * df["r_DIV"] + w_gem * df["r_GEM"]
        nav = (1 + daily_r).cumprod()
        return nav, 0.0  # 不计再平衡成本 (理论上限)

    if rebal_freq == "NONE":
        v_div = w_div
        v_gem = w_gem
        vals = []
        for i in range(len(df)):
            if i > 0:
                v_div *= (1 + df["r_DIV"].iloc[i])
                v_gem *= (1 + df["r_GEM"].iloc[i])
            vals.append(v_div + v_gem)
        nav = pd.Series(vals, index=df.index)
        return nav, 0.0

    # 再平衡日
    dt = df["date"]
    if rebal_freq == "M":
        rebal = dt.dt.to_period("M") != dt.dt.to_period("M").shift()
    elif rebal_freq == "Q":
        rebal = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    elif rebal_freq == "Y":
        rebal = dt.dt.to_period("Y") != dt.dt.to_period("Y").shift()
    else:
        raise ValueError(rebal_freq)

    v_div = w_div
    v_gem = w_gem
    total_turnover = 0.0
    vals = np.zeros(len(df))
    for i in range(len(df)):
        if i > 0:
            v_div *= (1 + df["r_DIV"].iloc[i])
            v_gem *= (1 + df["r_GEM"].iloc[i])
        if rebal.iloc[i] and i > 0:
            tot = v_div + v_gem
            tgt_div = tot * w_div
            tgt_gem = tot * w_gem
            turnover = (abs(tgt_div - v_div) + abs(tgt_gem - v_gem)) / tot
            cost = tot * turnover * COST * 0.5
            total_turnover += turnover
            v_div = tgt_div
            v_gem = tgt_gem
            # 扣成本
            v_div *= (1 - cost / tot) if tot > 0 else 1
            v_gem *= (1 - cost / tot) if tot > 0 else 1
        vals[i] = v_div + v_gem
    nav = pd.Series(vals, index=df.index)
    return nav, total_turnover


def metrics(nav, label, total_turnover=0.0):
    ret_total = nav.iloc[-1] / nav.iloc[0] - 1
    years = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25
    cagr = (1 + ret_total) ** (1/years) - 1
    daily_r = nav.pct_change().dropna()
    vol = daily_r.std() * np.sqrt(252)
    sharpe = (daily_r.mean() * 252 - 0.02) / vol if vol > 0 else 0
    dd = nav / nav.cummax() - 1
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd < 0 else 0
    return {
        "策略": label,
        "累计": ret_total,
        "CAGR": cagr,
        "年化波动": vol,
        "MDD": mdd,
        "Calmar": calmar,
        "Sharpe": sharpe,
        "换手": total_turnover,
        "nav": nav,
    }


configs = [
    ("HS300 (基准)",            1.0, 0.0, "NONE", "HS300"),
    ("DIV100 (不再平衡)",        1.0, 0.0, "NONE", "DIV"),
    ("GEM100 (不再平衡)",        0.0, 1.0, "NONE", "GEM"),
    ("DIV70/GEM30 不再平衡",     0.7, 0.3, "NONE", None),
    ("DIV70/GEM30 月度再平衡",   0.7, 0.3, "M",    None),
    ("DIV70/GEM30 季度再平衡",   0.7, 0.3, "Q",    None),
    ("DIV70/GEM30 年度再平衡",   0.7, 0.3, "Y",    None),
    ("DIV60/GEM40 季度再平衡",   0.6, 0.4, "Q",    None),
    ("DIV50/GEM50 季度再平衡",   0.5, 0.5, "Q",    None),
    ("DIV80/GEM20 季度再平衡",   0.8, 0.2, "Q",    None),
]

results = []
print(f"\n{'策略':<28s} {'累计':>9s} {'CAGR':>7s} {'波动':>6s} {'MDD':>7s} {'Calmar':>7s} {'Sharpe':>7s} {'换手':>6s}")
print("-" * 95)

for name, wd, wg, rb, single in configs:
    if single == "HS300":
        nav = df["HS300"].copy()
        nav.index = df.index
        res = metrics(nav, name, 0)
    elif single == "DIV":
        nav = df["DIV"].copy()
        nav.index = df.index
        res = metrics(nav, name, 0)
    elif single == "GEM":
        nav = df["GEM"].copy()
        nav.index = df.index
        res = metrics(nav, name, 0)
    else:
        nav, turn = simulate(wd, wg, rb)
        res = metrics(nav, name, turn)
    results.append(res)
    print(f"  {name:<26s} {res['累计']:>+8.1%} {res['CAGR']:>+6.2%} {res['年化波动']:>5.1%} "
          f"{res['MDD']:>+6.1%} {res['Calmar']:>6.2f} {res['Sharpe']:>6.2f} {res['换手']:>5.1f}")

# 保存
out = pd.DataFrame([{k:v for k,v in r.items() if k != "nav"} for r in results])
out.to_csv(os.path.join(OUT_DIR, "long_backtest.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 long_backtest.csv")


# ===== 分段 CAGR/MDD (2年滚动) =====
print("\n" + "=" * 80)
print("两年分段检查 (DIV70/GEM30 季度再平衡 vs HS300)")
print("=" * 80)
target = next(r for r in results if r["策略"] == "DIV70/GEM30 季度再平衡")
nav_t = target["nav"]
nav_hs = df["HS300"]

df_dt = df[["date"]].copy()
df_dt["year"] = df_dt["date"].dt.year

blocks = [(2010,2011),(2012,2013),(2014,2015),(2016,2017),(2018,2019),
          (2020,2021),(2022,2023),(2024,2025),(2026,2026)]

print(f"\n{'区间':<13s} {'DIV70/GEM30 CAGR':>18s} {'MDD':>8s} {'HS300 CAGR':>12s} {'MDD':>8s} {'超额':>8s}")
print("-" * 82)
seg_rows = []
for y0, y1 in blocks:
    m = (df_dt["year"] >= y0) & (df_dt["year"] <= y1)
    if m.sum() < 50:
        continue
    sub = nav_t[m].copy()
    sub_hs = nav_hs[m].copy()
    if len(sub) < 50: continue
    n0, n1 = sub.iloc[0], sub.iloc[-1]
    h0, h1 = sub_hs.iloc[0], sub_hs.iloc[-1]
    yrs = (df_dt.loc[sub.index[-1],"date"] - df_dt.loc[sub.index[0],"date"]).days / 365.25
    if yrs <= 0: continue
    cagr_t = (n1/n0)**(1/yrs) - 1
    cagr_h = (h1/h0)**(1/yrs) - 1
    mdd_t = (sub/sub.cummax() - 1).min()
    mdd_h = (sub_hs/sub_hs.cummax() - 1).min()
    alpha = cagr_t - cagr_h
    seg_rows.append({
        "区间": f"{y0}-{y1}",
        "DIV_CAGR": cagr_t,
        "DIV_MDD": mdd_t,
        "HS_CAGR": cagr_h,
        "HS_MDD": mdd_h,
        "alpha": alpha,
    })
    print(f"  {y0}-{y1:<6d} {cagr_t:>+17.2%} {mdd_t:>+7.1%} {cagr_h:>+11.2%} {mdd_h:>+7.1%} {alpha:>+7.2%}")

pd.DataFrame(seg_rows).to_csv(os.path.join(OUT_DIR, "long_backtest_segments.csv"),
                              index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 long_backtest_segments.csv")
