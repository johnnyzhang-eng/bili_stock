"""
All-Weather + 时序动量 overlay
===================================
基线: AW 30/30/40 (股/债/金) 季度再平衡, CAGR 8.13%, MDD -19.4%, Calmar 0.42

4 个变体:
  T1 TSM 滤波         — 资产 12M 收益<0 → 权重转 BOND
  T2 双动量           — T1 + 股市 >SMA200 才开股仓
  T3 波动率缩放       — 月频用 60 日波动倒数配权 (目标波动 6%, 不加杠杆)
  T4 防守急救         — 股 20日回撤 <-10% 紧急切防守组合 (15/45/40)

每个都 16 年回测 + 3 年滚动比例稳定性 + 2015/2022/2020 应激.

TSM 经典参考: Hurst, Ooi, Pedersen (AQR 2017) "A Century of Evidence on TSMOM"
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

ASSETS = ["DIV","GEM","BOND","GOLD"]
for c in ASSETS:
    df[f"r_{c}"] = df[c].pct_change().fillna(0.0)

# 合成股腿 (DIV70/GEM30)
df["STK"] = 0.7 * df["DIV"] + 0.3 * df["GEM"]
df["r_STK"] = 0.7 * df["r_DIV"] + 0.3 * df["r_GEM"]

# 预计算:
# - 12 个月收益 = 过去 252 日
# - SMA200, 20日DD
for c in ["STK","BOND","GOLD"]:
    df[f"ret12m_{c}"] = df[c].pct_change(252)
df["STK_sma200"] = df["STK"].rolling(200).mean()
df["STK_dd20"] = df["STK"] / df["STK"].rolling(20, min_periods=1).max() - 1
# 60 日波动
for c in ["STK","BOND","GOLD"]:
    df[f"vol60_{c}"] = df[f"r_{c}"].rolling(60).std() * np.sqrt(252)


def simulate(weight_fn, rebal="Q", label=""):
    """weight_fn(i) 返回 {'STK':w_s,'BOND':w_b,'GOLD':w_g} (和 = 1), 内部自动分解 DIV/GEM"""
    dt = df["date"]
    if rebal == "Q":
        mask = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    elif rebal == "M":
        mask = dt.dt.to_period("M") != dt.dt.to_period("M").shift()
    else:
        raise ValueError(rebal)

    # 初始
    w0 = weight_fn(0)
    vals = {"DIV": w0["STK"]*0.7, "GEM": w0["STK"]*0.3,
            "BOND": w0["BOND"], "GOLD": w0["GOLD"]}
    turnover_cum = 0.0
    series = np.zeros(len(df))

    for i in range(len(df)):
        if i > 0:
            for k in vals:
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])
        if mask.iloc[i] and i > 0:
            tot = sum(vals.values())
            w = weight_fn(i)
            tgt = {"DIV": tot*w["STK"]*0.7, "GEM": tot*w["STK"]*0.3,
                   "BOND": tot*w["BOND"], "GOLD": tot*w["GOLD"]}
            tov = sum(abs(tgt[k]-vals[k]) for k in tgt) / tot
            cost = tot * tov * COST * 0.5
            turnover_cum += tov
            vals = dict(tgt)
            scale = 1 - cost/tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())

    return pd.Series(series, index=df.index), turnover_cum


def metrics(nav, label):
    ret = nav.iloc[-1] / nav.iloc[0] - 1
    yrs = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25
    cagr = (1 + ret)**(1/yrs) - 1
    dr = nav.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sh = (dr.mean()*252 - 0.02) / vol if vol > 0 else 0
    dd = nav / nav.cummax() - 1
    mdd = dd.min()
    cal = cagr / abs(mdd) if mdd < 0 else 0
    return {"策略":label, "CAGR":cagr, "波动":vol, "MDD":mdd, "Calmar":cal, "Sharpe":sh, "nav":nav}


# ===== 权重函数 =====
W_STATIC = {"STK": 0.30, "BOND": 0.30, "GOLD": 0.40}

def w_static(i):
    return dict(W_STATIC)


def w_T1_tsm(i):
    """12M 动量: 负动量资产的权重 → 转 BOND"""
    if i < 252:
        return dict(W_STATIC)
    w = dict(W_STATIC)
    for c in ["STK","GOLD"]:
        ret = df[f"ret12m_{c}"].iloc[i]
        if pd.isna(ret) or ret < 0:
            w["BOND"] += w[c]
            w[c] = 0.0
    return w


def w_T2_dual(i):
    """T1 + 股市必须 > SMA200"""
    if i < 252:
        return dict(W_STATIC)
    w = dict(W_STATIC)
    # 股双重滤: 12M 正 AND 在 SMA200 上方
    stk_ret = df["ret12m_STK"].iloc[i]
    stk_above = df["STK"].iloc[i] > df["STK_sma200"].iloc[i]
    if pd.isna(stk_ret) or stk_ret < 0 or not stk_above:
        w["BOND"] += w["STK"]
        w["STK"] = 0.0
    # 金 12M 滤
    gold_ret = df["ret12m_GOLD"].iloc[i]
    if pd.isna(gold_ret) or gold_ret < 0:
        w["BOND"] += w["GOLD"]
        w["GOLD"] = 0.0
    return w


def w_T3_volscale(i):
    """60 日波动倒数配权, 目标波动 6% / 年. 不加杠杆."""
    if i < 60:
        return dict(W_STATIC)
    vols = {
        "STK": df["vol60_STK"].iloc[i],
        "BOND": df["vol60_BOND"].iloc[i],
        "GOLD": df["vol60_GOLD"].iloc[i],
    }
    if any(pd.isna(v) or v <= 0 for v in vols.values()):
        return dict(W_STATIC)
    # 每个资产给 2% 波动目标 (合并 ≈ 3~6% 组合波动)
    raw = {k: 0.02 / v for k, v in vols.items()}
    total = sum(raw.values())
    # 归一到 1 (即不加杠杆)
    if total > 1:
        raw = {k: v/total for k, v in raw.items()}
    else:
        # 剩余现金给 BOND (保守)
        raw["BOND"] += 1 - total
    return raw


def w_T4_defense(i):
    """股近 20 日回撤 < -10% → 切防守 15/45/40, 否则基线 30/30/40"""
    if i < 20:
        return dict(W_STATIC)
    dd20 = df["STK_dd20"].iloc[i]
    if pd.isna(dd20):
        return dict(W_STATIC)
    if dd20 < -0.10:
        return {"STK": 0.15, "BOND": 0.45, "GOLD": 0.40}
    return dict(W_STATIC)


# ===== 执行 =====
configs = [
    ("基线 30/30/40 季度", w_static, "Q"),
    ("T1 TSM 12M 滤波 季度", w_T1_tsm, "Q"),
    ("T2 双动量 (TSM + SMA200) 季度", w_T2_dual, "Q"),
    ("T3 波动率缩放 月度", w_T3_volscale, "M"),
    ("T4 防守急救 (-10% DD 切) 月度", w_T4_defense, "M"),
]

results = []
print(f"{'策略':<34s} {'CAGR':>7s} {'波动':>6s} {'MDD':>7s} {'Calmar':>7s} {'Sharpe':>7s} {'换手':>6s}")
print("-" * 90)
for name, wf, rb in configs:
    nav, tov = simulate(wf, rebal=rb, label=name)
    r = metrics(nav, name)
    r["换手"] = tov
    results.append(r)
    print(f"  {name:<32s} {r['CAGR']:>+6.2%} {r['波动']:>5.1%} {r['MDD']:>+6.1%} "
          f"{r['Calmar']:>6.2f} {r['Sharpe']:>6.2f} {tov:>5.1f}")

# 应激
print("\n" + "=" * 85)
print("关键应激测试")
print("=" * 85)
for name_event, mask in [
    ("2015 股灾    (15-06 → 16-01)", (df["date"] >= "2015-06-12") & (df["date"] <= "2016-01-31")),
    ("2018 贸易战  (18-01 → 19-01)", (df["date"] >= "2018-01-26") & (df["date"] <= "2019-01-03")),
    ("2020 疫情雪崩(20-01 → 20-03)", (df["date"] >= "2020-01-20") & (df["date"] <= "2020-03-23")),
    ("2022-2023 熊 (22-01 → 23-12)", (df["date"] >= "2022-01-01") & (df["date"] <= "2023-12-31")),
]:
    print(f"\n{name_event}:")
    for r in results:
        sub = r["nav"][mask.values]
        if len(sub) < 5: continue
        total = sub.iloc[-1]/sub.iloc[0] - 1
        dd = (sub / sub.cummax() - 1).min()
        print(f"  {r['策略']:<34s} 涨跌 {total:>+7.1%}   内部 MDD {dd:>+7.1%}")

# 3 年滚动简要
print("\n" + "=" * 85)
print("3 年滚动 CAGR 统计 (756 日)")
print("=" * 85)
WIN = 756
print(f"  {'策略':<34s} {'平均':>7s} {'中位':>7s} {'最坏':>7s} {'最好':>7s} {'3年不亏率':>10s}")
rolling_stats = []
for r in results:
    nav = r["nav"]
    cagrs = []
    for i in range(WIN, len(df)):
        yrs = (df["date"].iloc[i] - df["date"].iloc[i-WIN]).days / 365.25
        cagrs.append((nav.iloc[i] / nav.iloc[i-WIN])**(1/yrs) - 1)
    s = pd.Series(cagrs)
    print(f"  {r['策略']:<34s} {s.mean():>+6.2%} {s.median():>+6.2%} "
          f"{s.min():>+6.2%} {s.max():>+6.2%} {(s>0).mean():>9.1%}")
    rolling_stats.append({
        "策略": r["策略"],
        "mean_3y": s.mean(), "median_3y": s.median(),
        "worst_3y": s.min(), "best_3y": s.max(),
        "pos_rate_3y": (s>0).mean(),
    })

# 保存
out = pd.DataFrame([{**{k:v for k,v in r.items() if k != "nav"}, **next((x for x in rolling_stats if x["策略"]==r["策略"]), {})} for r in results])
out.to_csv(os.path.join(OUT_DIR, "all_weather_momentum.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 all_weather_momentum.csv")

# NAV 保存
nav_out = df[["date"]].copy()
for r in results:
    nav_out[r["策略"]] = r["nav"].values
nav_out.to_csv(os.path.join(OUT_DIR, "all_weather_momentum_nav.csv"), index=False, encoding="utf-8-sig")
