"""
T6 终极版 — T2 双动量 + T4 防守急救 混合
=============================================
T2 缺点: SMA/动量是 lagging, 2015 等快速崩盘时来不及切
T4 缺点: -10% DD 误触发频繁 (选股 DD 而不是趋势)

混合:
  规则 A (长期动量, 低频): 股 12M<0 或 股 < SMA200 → STK→BOND
  规则 B (短期急刹, 高频): 股 20日DD < -10% → STK 砍半去 BOND
  规则 C: 黄金 12M < 0 → GOLD → BOND

Rebal: 月度 (比 Q 更灵敏, 但月度 1 次换手可控)
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
df["r_STK"] = 0.7*df["r_DIV"] + 0.3*df["r_GEM"]

# 信号
df["STK_sma200"] = df["STK"].rolling(200).mean()
df["STK_ret12m"] = df["STK"].pct_change(252)
df["STK_dd20"] = df["STK"] / df["STK"].rolling(20, min_periods=1).max() - 1
df["GOLD_ret12m"] = df["GOLD"].pct_change(252)
# 黄金 DD20 (对称警报)
df["GOLD_dd20"] = df["GOLD"] / df["GOLD"].rolling(20, min_periods=1).max() - 1

W = {"STK":0.30, "BOND":0.30, "GOLD":0.40}


def simulate(rebal="M", use_A=True, use_B=True, use_C=True, dd_thr=-0.10, dd_cut=0.50):
    """
    use_A: 长期趋势滤 (SMA200 + 12M)
    use_B: 短期 DD 急刹 (切 dd_cut 比例)
    use_C: 黄金 12M 滤
    """
    dt = df["date"]
    if rebal == "Q":
        mask_full = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    elif rebal == "M":
        mask_full = dt.dt.to_period("M") != dt.dt.to_period("M").shift()
    mask_b = dt.dt.to_period("W") != dt.dt.to_period("W").shift()  # B 警报每周 check

    vals = {"DIV": W["STK"]*0.7, "GEM": W["STK"]*0.3, "BOND": W["BOND"], "GOLD": W["GOLD"]}
    series = np.zeros(len(df))
    turnover = 0.0

    # 状态: B 急刹是否已激活 (避免反复切)
    b_active = False

    for i in range(len(df)):
        if i > 0:
            for k in vals:
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])

        # 计算当前权重目标
        do_rebal = False
        w = dict(W)

        # A 长期滤 (月度)
        if use_A and mask_full.iloc[i] and i >= 252:
            sma_ok = df["STK"].iloc[i] > df["STK_sma200"].iloc[i]
            mom_ok = df["STK_ret12m"].iloc[i] > 0
            if not (sma_ok and mom_ok):
                w["BOND"] += w["STK"]; w["STK"] = 0.0
            if use_C:
                g_mom = df["GOLD_ret12m"].iloc[i]
                if pd.isna(g_mom) or g_mom < 0:
                    w["BOND"] += w["GOLD"]; w["GOLD"] = 0.0
            do_rebal = True

        # B 急刹 (周度检查)
        if use_B and mask_b.iloc[i] and i >= 20:
            dd = df["STK_dd20"].iloc[i]
            if not b_active and not pd.isna(dd) and dd < dd_thr:
                # 激活急刹: STK 按 dd_cut 砍到 BOND
                b_active = True
                do_rebal = True
                w["BOND"] += w["STK"] * dd_cut
                w["STK"] *= (1 - dd_cut)
            elif b_active and not pd.isna(dd) and dd > dd_thr / 2:
                # 股市从深 DD 回升到 -5% 以上 → 解除急刹
                b_active = False
                # 不强制回复 (等下一次月度再平衡恢复)

        # 若 B 激活中但是 A 月度触发, 合并效应
        if b_active and mask_full.iloc[i]:
            # 重新计算: 先应用 A, 再砍 dd_cut 给 BOND
            w = dict(W)
            if i >= 252:
                sma_ok = df["STK"].iloc[i] > df["STK_sma200"].iloc[i]
                mom_ok = df["STK_ret12m"].iloc[i] > 0
                if not (sma_ok and mom_ok):
                    w["BOND"] += w["STK"]; w["STK"] = 0.0
                if use_C:
                    g_mom = df["GOLD_ret12m"].iloc[i]
                    if pd.isna(g_mom) or g_mom < 0:
                        w["BOND"] += w["GOLD"]; w["GOLD"] = 0.0
            w["BOND"] += w["STK"] * dd_cut
            w["STK"] *= (1 - dd_cut)
            do_rebal = True

        if do_rebal and i > 0:
            tot = sum(vals.values())
            tgt = {"DIV": tot*w["STK"]*0.7, "GEM": tot*w["STK"]*0.3,
                   "BOND": tot*w["BOND"], "GOLD": tot*w["GOLD"]}
            tov = sum(abs(tgt[k]-vals[k]) for k in tgt) / tot
            cost = tot * tov * COST * 0.5
            turnover += tov
            vals = dict(tgt)
            scale = 1 - cost/tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())
    return pd.Series(series, index=df.index), turnover


def metrics(nav, label):
    ret = nav.iloc[-1]/nav.iloc[0] - 1
    yrs = (df["date"].iloc[-1]-df["date"].iloc[0]).days / 365.25
    cagr = (1+ret)**(1/yrs) - 1
    dr = nav.pct_change().dropna()
    vol = dr.std()*np.sqrt(252)
    sh = (dr.mean()*252 - 0.02)/vol if vol > 0 else 0
    dd = (nav/nav.cummax() - 1).min()
    cal = cagr/abs(dd) if dd < 0 else 0
    # 3Y 滚动
    WIN = 756
    cagrs = []
    for i in range(WIN, len(df)):
        yr = (df["date"].iloc[i]-df["date"].iloc[i-WIN]).days/365.25
        cagrs.append((nav.iloc[i]/nav.iloc[i-WIN])**(1/yr) - 1)
    s = pd.Series(cagrs)
    pos_3y = (s > 0).mean()
    worst_3y = s.min()
    return cagr, vol, dd, cal, sh, pos_3y, worst_3y


configs = [
    ("基线 30/30/40 季度",        dict(rebal="Q", use_A=False, use_B=False, use_C=False)),
    ("T2 双动量 (A+C)",            dict(rebal="M", use_A=True,  use_B=False, use_C=True)),
    ("T4 急刹 (仅 B)",             dict(rebal="M", use_A=False, use_B=True,  use_C=False)),
    ("T6a A+B (动量+急刹)",         dict(rebal="M", use_A=True,  use_B=True,  use_C=False)),
    ("T6 A+B+C (全混合)",           dict(rebal="M", use_A=True,  use_B=True,  use_C=True)),
    ("T6 dd=-7%",                   dict(rebal="M", use_A=True,  use_B=True,  use_C=True, dd_thr=-0.07)),
    ("T6 dd=-15%",                  dict(rebal="M", use_A=True,  use_B=True,  use_C=True, dd_thr=-0.15)),
    ("T6 dd_cut=1.0 (全砍)",        dict(rebal="M", use_A=True,  use_B=True,  use_C=True, dd_cut=1.0)),
    ("T6 dd_cut=0.3 (只砍 3 成)",   dict(rebal="M", use_A=True,  use_B=True,  use_C=True, dd_cut=0.3)),
]

print(f"{'策略':<34s} {'CAGR':>7s} {'波动':>6s} {'MDD':>7s} {'Calmar':>7s} {'Sharpe':>7s} {'3Y不亏':>7s} {'3Y最坏':>8s} {'换手':>6s}")
print("-" * 105)
results = []
for name, kw in configs:
    nav, tov = simulate(**kw)
    cagr, vol, mdd, cal, sh, pos3y, w3y = metrics(nav, name)
    results.append({"策略":name, "CAGR":cagr,"Vol":vol,"MDD":mdd,"Calmar":cal,"Sharpe":sh,
                    "pos_3y":pos3y,"worst_3y":w3y,"turnover":tov, "nav":nav})
    print(f"  {name:<32s} {cagr:>+6.2%} {vol:>5.1%} {mdd:>+6.1%} {cal:>6.2f} {sh:>6.2f} "
          f"{pos3y:>6.1%} {w3y:>+7.2%} {tov:>5.1f}")

# 应激测试
print("\n" + "=" * 90)
print("应激测试")
print("=" * 90)
for name_event, mask in [
    ("2015 股灾 ", (df["date"] >= "2015-06-12") & (df["date"] <= "2016-01-31")),
    ("2018 贸易战 ", (df["date"] >= "2018-01-26") & (df["date"] <= "2019-01-03")),
    ("2022-2023 熊", (df["date"] >= "2022-01-01") & (df["date"] <= "2023-12-31")),
]:
    print(f"\n{name_event}:")
    for r in results:
        sub = r["nav"][mask.values]
        if len(sub) < 5: continue
        tot = sub.iloc[-1]/sub.iloc[0] - 1
        mdd = (sub/sub.cummax() - 1).min()
        print(f"  {r['策略']:<34s} 涨跌 {tot:>+7.1%}  MDD {mdd:>+7.1%}")

out = pd.DataFrame([{k:v for k,v in r.items() if k != "nav"} for r in results])
out.to_csv(os.path.join(OUT_DIR, "all_weather_t6.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 all_weather_t6.csv")
