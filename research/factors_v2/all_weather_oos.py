"""
全天候策略 OOS 2-split 验证
===================================
目的: T2 是不是真稳? T6 是不是真过拟合?
  让 train/test 独立评估, 每半段独立算指标.

切分:
  Train 2010-06-01 → 2018-06-30  (含 2015 股灾, 2018 贸易战上半年)
  Test  2018-07-01 → 2026-04-20  (含 2018 底, 2020 疫情, 2022-23 熊)

合格判据:
  T2 合格    = Test Calmar ≥ Train Calmar × 0.7
  T6 过拟合  = Test Calmar 比 Train 掉 > 30%

跑 6 个配置:
  1. 基线 30/30/40 Q
  2. T2 SMA200/12M  (生产配置)
  3. T2 SMA150/12M  (参数扰动 1)
  4. T2 SMA250/12M  (参数扰动 2)
  5. T2 SMA200/6M   (参数扰动 3 — 短 MOM)
  6. T6 dd_cut=1.0  (过拟合反面教材)
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

# 读数据
df = pd.read_csv(os.path.join(OUT_DIR, "long_history_4asset.csv"), encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

for c in ["DIV","GEM","BOND","GOLD"]:
    df[f"r_{c}"] = df[c].pct_change().fillna(0.0)
df["STK"] = 0.7*df["DIV"] + 0.3*df["GEM"]
df["r_STK"] = 0.7*df["r_DIV"] + 0.3*df["r_GEM"]

W = {"STK":0.30, "BOND":0.30, "GOLD":0.40}


def simulate(strategy: str, **kw):
    """
    strategy 选项:
      baseline       - 静态 30/30/40 季度再平衡
      t2             - T2 双动量 (SMA+12M), kw: sma_p, mom_lb
      t6_ddcut1      - T6 dd_cut=1.0 急刹变体
    """
    sma_p = kw.get("sma_p", 200)
    mom_lb = kw.get("mom_lb", 252)
    dd_thr = kw.get("dd_thr", -0.10)
    dd_cut = kw.get("dd_cut", 1.0)

    df["STK_sma"] = df["STK"].rolling(sma_p).mean()
    df["STK_ret12m"] = df["STK"].pct_change(mom_lb)
    df["GOLD_ret12m"] = df["GOLD"].pct_change(mom_lb)
    df["STK_dd20"] = df["STK"] / df["STK"].rolling(20, min_periods=1).max() - 1

    dt = df["date"]
    mask_q = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()
    mask_m = dt.dt.to_period("M") != dt.dt.to_period("M").shift()
    mask_w = dt.dt.to_period("W") != dt.dt.to_period("W").shift()

    vals = {"DIV": W["STK"]*0.7, "GEM": W["STK"]*0.3, "BOND": W["BOND"], "GOLD": W["GOLD"]}
    series = np.zeros(len(df))
    b_active = False

    for i in range(len(df)):
        if i > 0:
            for k in vals: vals[k] *= (1 + df[f"r_{k}"].iloc[i])

        do_rebal = False
        w = dict(W)

        if strategy == "baseline":
            if mask_q.iloc[i] and i > 0:
                do_rebal = True

        elif strategy == "t2":
            if mask_q.iloc[i] and i >= max(252, sma_p):
                rm = df["STK_ret12m"].iloc[i]
                above = df["STK"].iloc[i] > df["STK_sma"].iloc[i]
                if pd.isna(rm) or rm < 0 or not above:
                    w["BOND"] += w["STK"]; w["STK"] = 0.0
                rg = df["GOLD_ret12m"].iloc[i]
                if pd.isna(rg) or rg < 0:
                    w["BOND"] += w["GOLD"]; w["GOLD"] = 0.0
                do_rebal = True

        elif strategy == "t6_ddcut1":
            # T2 monthly + DD20 emergency brake (dd_cut=1.0)
            if mask_m.iloc[i] and i >= 252:
                rm = df["STK_ret12m"].iloc[i]
                above = df["STK"].iloc[i] > df["STK_sma"].iloc[i]
                if pd.isna(rm) or rm < 0 or not above:
                    w["BOND"] += w["STK"]; w["STK"] = 0.0
                rg = df["GOLD_ret12m"].iloc[i]
                if pd.isna(rg) or rg < 0:
                    w["BOND"] += w["GOLD"]; w["GOLD"] = 0.0
                do_rebal = True
            if mask_w.iloc[i] and i >= 20:
                dd = df["STK_dd20"].iloc[i]
                if not b_active and not pd.isna(dd) and dd < dd_thr:
                    b_active = True
                    w["BOND"] += w["STK"] * dd_cut
                    w["STK"] *= (1 - dd_cut)
                    do_rebal = True
                elif b_active and not pd.isna(dd) and dd > dd_thr / 2:
                    b_active = False

        if do_rebal and i > 0:
            tot = sum(vals.values())
            tgt = {"DIV": tot*w["STK"]*0.7, "GEM": tot*w["STK"]*0.3,
                   "BOND": tot*w["BOND"], "GOLD": tot*w["GOLD"]}
            tov = sum(abs(tgt[k]-vals[k]) for k in tgt) / tot
            cost = tot * tov * COST * 0.5
            vals = dict(tgt)
            scale = 1 - cost/tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())

    return pd.Series(series, index=df.index)


def metrics(nav, mask):
    sub = nav[mask.values]
    dates = df.loc[mask, "date"]
    if len(sub) < 100 or sub.iloc[0] <= 0:
        return None
    # 归一化到这一段起始 = 1 (方便比较独立 CAGR)
    sub = sub / sub.iloc[0]
    ret = sub.iloc[-1] / sub.iloc[0] - 1
    yrs = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    cagr = (1 + ret)**(1/yrs) - 1 if yrs > 0 else 0
    dr = sub.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sh = (dr.mean()*252 - 0.02) / vol if vol > 0 else 0
    mdd = (sub / sub.cummax() - 1).min()
    cal = cagr / abs(mdd) if mdd < 0 else 0
    return {"CAGR":cagr, "Vol":vol, "MDD":mdd, "Calmar":cal, "Sharpe":sh, "years":yrs}


# 时间切分
split = pd.Timestamp("2018-06-30")
mask_train = df["date"] <= split
mask_test  = df["date"] >  split
mask_full  = pd.Series(True, index=df.index)

print(f"Train: {df.loc[mask_train,'date'].min().date()} → {df.loc[mask_train,'date'].max().date()}  "
      f"({mask_train.sum()} 天)")
print(f"Test:  {df.loc[mask_test,'date'].min().date()} → {df.loc[mask_test,'date'].max().date()}  "
      f"({mask_test.sum()} 天)")
print()

configs = [
    ("基线 30/30/40 Q",      "baseline", {}),
    ("T2 SMA200/12M (生产)",  "t2",       {"sma_p":200, "mom_lb":252}),
    ("T2 SMA150/12M (扰动)",  "t2",       {"sma_p":150, "mom_lb":252}),
    ("T2 SMA250/12M (扰动)",  "t2",       {"sma_p":250, "mom_lb":252}),
    ("T2 SMA200/6M  (扰动)",  "t2",       {"sma_p":200, "mom_lb":126}),
    ("T6 dd_cut=1.0 (反面)",  "t6_ddcut1",{"sma_p":200, "mom_lb":252}),
]

rows = []
print(f"{'策略':<24s} | {'Full':^36s} | {'Train':^36s} | {'Test':^36s}")
print(f"{'':24s} | {'CAGR':>7s} {'MDD':>7s} {'Cal':>6s} {'Shp':>6s} | "
      f"{'CAGR':>7s} {'MDD':>7s} {'Cal':>6s} {'Shp':>6s} | "
      f"{'CAGR':>7s} {'MDD':>7s} {'Cal':>6s} {'Shp':>6s}")
print("-" * 140)

for name, strat, kw in configs:
    nav = simulate(strat, **kw)
    mf = metrics(nav, mask_full)
    mt = metrics(nav, mask_train)
    mx = metrics(nav, mask_test)
    rows.append({
        "name": name, "strategy": strat, **{f"kw_{k}":v for k,v in kw.items()},
        "full_cagr": mf["CAGR"], "full_mdd": mf["MDD"], "full_cal": mf["Calmar"], "full_shp": mf["Sharpe"],
        "train_cagr": mt["CAGR"], "train_mdd": mt["MDD"], "train_cal": mt["Calmar"], "train_shp": mt["Sharpe"],
        "test_cagr": mx["CAGR"], "test_mdd": mx["MDD"], "test_cal": mx["Calmar"], "test_shp": mx["Sharpe"],
        "cal_retention": mx["Calmar"] / mt["Calmar"] if mt["Calmar"] > 0 else np.nan,
    })
    def fmt(m):
        return f"{m['CAGR']:>+6.2%} {m['MDD']:>+6.1%} {m['Calmar']:>5.2f} {m['Sharpe']:>5.2f}"
    print(f"  {name:<22s} | {fmt(mf)} | {fmt(mt)} | {fmt(mx)}")

print()
print("="*100)
print("  OOS 判定")
print("="*100)
print(f"{'策略':<24s}  {'Train Calmar':>12s}  {'Test Calmar':>11s}  {'保留率':>7s}  {'判定':>12s}")
print("-" * 80)
for r in rows:
    ret = r["cal_retention"]
    if r["strategy"] == "baseline":
        verdict = "基准 (对照)"
    elif r["strategy"] == "t2":
        verdict = "✓ 通过" if ret >= 0.7 else ("⚠ 勉强" if ret >= 0.5 else "✗ 不稳")
    elif r["strategy"] == "t6_ddcut1":
        verdict = "✓ 意外好" if ret >= 0.7 else ("⚠ 中等" if ret >= 0.5 else "✗ 过拟合确认")
    else:
        verdict = ""
    ret_s = f"{ret*100:.1f}%" if not pd.isna(ret) else "N/A"
    print(f"  {r['name']:<22s}  {r['train_cal']:>12.2f}  {r['test_cal']:>11.2f}  {ret_s:>7s}  {verdict:>12s}")

out = pd.DataFrame(rows)
out.to_csv(os.path.join(OUT_DIR, "all_weather_oos.csv"), index=False, encoding="utf-8-sig")
print(f"\n[+] 写入 {os.path.join(OUT_DIR, 'all_weather_oos.csv')}")
