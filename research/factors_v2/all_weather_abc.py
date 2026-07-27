"""
全天候组合 ABC 方案回测 — 2010-2026 (16 年)
===============================================
股腿 = 70% DIV (512890 / sh000922) + 30% GEM (159915 / sz399006)
债腿 = sh000012 上证国债指数
金腿 = AU0 沪金主力连续

方案:
  A 60/40:       60% 股 + 40% 债
  B 40/40/20:    40% 股 + 40% 债 + 20% 金 (Permanent Portfolio 简化)
  C 风险平价:    按 60 日波动倒数配权, 月度调整
  D 25/25/25/25: 原版 Permanent Portfolio (用 HS300 替代全股)
  E (参考)基准: DIV70/GEM30 季度

所有方案季度再平衡, 成本 56bp 往返.
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

ASSETS = ["DIV","GEM","HS300","BOND","GOLD"]
for c in ASSETS:
    df[f"r_{c}"] = df[c].pct_change().fillna(0.0)

# 股腿 = DIV70/GEM30 合成日收益
df["r_STK"] = 0.7 * df["r_DIV"] + 0.3 * df["r_GEM"]


def simulate(weight_fn, rebal="Q", name=""):
    """weight_fn: i -> dict of weights (assets 必须是 r_* 列存在的 suffix)
    rebal: 'Q' 季度, 'M' 月度, 'Y' 年度"""
    dt = df["date"]
    if rebal == "Q":
        rebal_mask = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    elif rebal == "M":
        rebal_mask = dt.dt.to_period("M") != dt.dt.to_period("M").shift()
    elif rebal == "Y":
        rebal_mask = dt.dt.to_period("Y") != dt.dt.to_period("Y").shift()

    # 初始化权重
    w0 = weight_fn(0)
    vals = {k: v for k, v in w0.items()}  # 每个资产的价值
    total_turnover = 0.0
    series = np.zeros(len(df))

    for i in range(len(df)):
        if i > 0:
            for k in list(vals.keys()):
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])
        if rebal_mask.iloc[i] and i > 0:
            tot = sum(vals.values())
            w_new = weight_fn(i)
            tgt = {k: tot * w_new[k] for k in w_new}
            turnover = sum(abs(tgt.get(k,0) - vals.get(k,0)) for k in set(tgt) | set(vals)) / tot
            cost = tot * turnover * COST * 0.5
            total_turnover += turnover
            vals = dict(tgt)
            scale = 1 - cost / tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())

    nav = pd.Series(series, index=df.index)
    return nav, total_turnover


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


# ===== 方案定义 =====
def w_baseline_divgem(i):
    return {"DIV": 0.7, "GEM": 0.3}

def w_A_6040(i):
    # 60% 股 (股内部 7:3), 40% 债
    return {"DIV": 0.6*0.7, "GEM": 0.6*0.3, "BOND": 0.4}

def w_B_404020(i):
    return {"DIV": 0.4*0.7, "GEM": 0.4*0.3, "BOND": 0.4, "GOLD": 0.2}

def w_D_permanent(i):
    # 经典 Permanent: 25% 股 + 25% 长债 + 25% 金 + 25% 现金  (现金 = BOND 代替)
    return {"DIV": 0.25*0.7, "GEM": 0.25*0.3, "BOND": 0.50, "GOLD": 0.25}

# 风险平价
def make_rp_fn(lookback=60):
    def w_rp(i):
        if i < lookback:
            return {"DIV": 0.5*0.7, "GEM": 0.5*0.3, "BOND": 0.4, "GOLD": 0.1}
        win = df.iloc[max(0, i-lookback):i+1]
        vols = {
            "STK_combined": (0.7*win["r_DIV"] + 0.3*win["r_GEM"]).std() * np.sqrt(252),
            "BOND": win["r_BOND"].std() * np.sqrt(252),
            "GOLD": win["r_GOLD"].std() * np.sqrt(252),
        }
        inv = {k: 1/max(v, 1e-4) for k,v in vols.items()}
        s = sum(inv.values())
        w_stk = inv["STK_combined"] / s
        w_bond = inv["BOND"] / s
        w_gold = inv["GOLD"] / s
        return {"DIV": w_stk*0.7, "GEM": w_stk*0.3, "BOND": w_bond, "GOLD": w_gold}
    return w_rp

w_C_rp = make_rp_fn(60)

plans = [
    ("E 基准: DIV70/GEM30 季度",      w_baseline_divgem, "Q"),
    ("A 60/40 股债 季度",              w_A_6040,          "Q"),
    ("B 40/40/20 股债金 季度",         w_B_404020,        "Q"),
    ("C 风险平价 60日波动 月度",       w_C_rp,            "M"),
    ("D 25/25/50 股金债 季度",         w_D_permanent,     "Q"),
]

results = []
print(f"{'策略':<32s} {'CAGR':>7s} {'波动':>6s} {'MDD':>7s} {'Calmar':>7s} {'Sharpe':>7s} {'换手':>6s}")
print("-" * 85)
for name, wf, rb in plans:
    nav, turn = simulate(wf, rebal=rb, name=name)
    r = metrics(nav, name)
    r["换手"] = turn
    results.append(r)
    print(f"  {name:<30s} {r['CAGR']:>+6.2%} {r['波动']:>5.1%} {r['MDD']:>+6.1%} "
          f"{r['Calmar']:>6.2f} {r['Sharpe']:>6.2f} {turn:>5.1f}")

# 2015 股灾应对检查 (2015-06-12 ~ 2016-01-31 半年)
print("\n" + "=" * 80)
print("关键应激测试 — 2015 股灾 (2015-06-12 ~ 2016-01-31)")
print("=" * 80)
crash_start = pd.Timestamp("2015-06-12")
crash_end   = pd.Timestamp("2016-01-31")
m = (df["date"] >= crash_start) & (df["date"] <= crash_end)
for r in results:
    nav = r["nav"]
    if m.sum() < 10: continue
    sub = nav[m.values]
    n_start = sub.iloc[0]
    n_end = sub.iloc[-1]
    loss_total = n_end / n_start - 1
    dd_inner = (sub / sub.cummax() - 1).min()
    print(f"  {r['策略']:<32s} 区间涨跌 {loss_total:>+7.1%}  区间MDD {dd_inner:>+7.1%}")

# 2022-2023 熊市 (2022-01-01 ~ 2023-12-31)
print("\n应激测试 — 2022-2023 熊市 (HS300 -20%)")
print("-" * 82)
m2 = (df["date"] >= "2022-01-01") & (df["date"] <= "2023-12-31")
for r in results:
    nav = r["nav"]
    sub = nav[m2.values]
    n0, n1 = sub.iloc[0], sub.iloc[-1]
    dd = (sub / sub.cummax() - 1).min()
    print(f"  {r['策略']:<32s} 区间涨跌 {n1/n0 - 1:>+7.1%}  区间MDD {dd:>+7.1%}")

# 2020 疫情 (2020-01-20 ~ 2020-03-23)
print("\n应激测试 — 2020 疫情 (2020-01-20 ~ 2020-03-23, 海外雪崩)")
print("-" * 82)
m3 = (df["date"] >= "2020-01-20") & (df["date"] <= "2020-03-23")
for r in results:
    nav = r["nav"]
    if m3.sum() < 5: continue
    sub = nav[m3.values]
    n0, n1 = sub.iloc[0], sub.iloc[-1]
    dd = (sub / sub.cummax() - 1).min()
    print(f"  {r['策略']:<32s} 区间涨跌 {n1/n0 - 1:>+7.1%}  区间MDD {dd:>+7.1%}")

# 保存
out = pd.DataFrame([{k:v for k,v in r.items() if k != "nav"} for r in results])
out.to_csv(os.path.join(OUT_DIR, "all_weather_abc.csv"), index=False, encoding="utf-8-sig")
print(f"\n  ← 已写 all_weather_abc.csv")

# 保存 nav 时序, 用于滚动分析
nav_out = df[["date"]].copy()
for r in results:
    nav_out[r["策略"]] = r["nav"].values
nav_out.to_csv(os.path.join(OUT_DIR, "all_weather_nav.csv"), index=False, encoding="utf-8-sig")
print(f"  ← 已写 all_weather_nav.csv")
