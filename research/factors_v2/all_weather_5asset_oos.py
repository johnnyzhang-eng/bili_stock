"""
全天候 5 资产 OOS 验证 — 加入 SP500
=====================================
动因 (用户关心): 雪球 211 个"干净赢家"中 31% 重仓苹果 → A 股赢家靠出境.
       Step 2 OOS 证明 T2 在 benign 期跑不赢基线 → 需要新 alpha 源.

守住纪律 (不 grid sweep):
  配置 A (温和): 25% A股 / 20% SP500 / 25% 债 / 30% 金
  配置 B (加强): 20% A股 / 25% SP500 / 25% 债 / 30% 金
  对照:          30% A股 / 30% 债 / 40% 金  (原 T2)
全部加 T2 overlay (A 股/金 各自 12M+SMA200, SP500 同规则 — 回应"担心美股崩盘")

判定 (预先定, 不事后挪):
  - OOS Test CAGR ≥ 原 T2 Test CAGR: 有增量
  - OOS Test MDD ≤ 原 T2 Test MDD: 风险不增
  - OOS Test Calmar ≥ 原 T2 Test Calmar × 1.1: 显著改善
  任何一项未达: 不采纳, 保持 4 资产 T2.
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

df = pd.read_csv(os.path.join(OUT_DIR, "long_history_5asset.csv"), encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

for c in ["DIV","GEM","BOND","GOLD","SP500"]:
    df[f"r_{c}"] = df[c].pct_change().fillna(0.0)
df["STK"] = 0.7*df["DIV"] + 0.3*df["GEM"]
df["r_STK"] = 0.7*df["r_DIV"] + 0.3*df["r_GEM"]

# 预计算 T2 信号
for c in ["STK","SP500","GOLD"]:
    df[f"{c}_sma200"] = df[c].rolling(200).mean()
    df[f"{c}_ret12m"] = df[c].pct_change(252)


def simulate(w_base: dict, use_t2=True):
    """
    w_base: {"STK": 0.25, "SP500": 0.20, "BOND": 0.25, "GOLD": 0.30} 形式 (和 = 1)
    use_t2: 每腿股 12M+SMA200 overlay, 失效转 BOND
    """
    dt = df["date"]
    mask_q = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()

    # 初始化 — DIV/GEM/SP500/BOND/GOLD 5 个
    vals = {
        "DIV":   w_base.get("STK", 0) * 0.7,
        "GEM":   w_base.get("STK", 0) * 0.3,
        "SP500": w_base.get("SP500", 0),
        "BOND":  w_base.get("BOND", 0),
        "GOLD":  w_base.get("GOLD", 0),
    }
    series = np.zeros(len(df))

    for i in range(len(df)):
        if i > 0:
            for k in vals: vals[k] *= (1 + df[f"r_{k}"].iloc[i])

        if mask_q.iloc[i] and i >= 252:
            w = dict(w_base)
            if use_t2:
                # A 股
                rm = df["STK_ret12m"].iloc[i]
                above = df["STK"].iloc[i] > df["STK_sma200"].iloc[i]
                if pd.isna(rm) or rm < 0 or not above:
                    w["BOND"] += w.get("STK", 0); w["STK"] = 0
                # SP500
                if "SP500" in w_base:
                    rs = df["SP500_ret12m"].iloc[i]
                    abs_sp = df["SP500"].iloc[i] > df["SP500_sma200"].iloc[i]
                    if pd.isna(rs) or rs < 0 or not abs_sp:
                        w["BOND"] += w.get("SP500", 0); w["SP500"] = 0
                # GOLD
                rg = df["GOLD_ret12m"].iloc[i]
                if pd.isna(rg) or rg < 0:
                    w["BOND"] += w.get("GOLD", 0); w["GOLD"] = 0

            tot = sum(vals.values())
            tgt = {
                "DIV": tot*w.get("STK",0)*0.7, "GEM": tot*w.get("STK",0)*0.3,
                "SP500": tot*w.get("SP500",0),
                "BOND": tot*w.get("BOND",0), "GOLD": tot*w.get("GOLD",0),
            }
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
    if len(sub) < 100 or sub.iloc[0] <= 0: return None
    sub = sub / sub.iloc[0]
    ret = sub.iloc[-1]/sub.iloc[0] - 1
    yrs = (dates.iloc[-1]-dates.iloc[0]).days / 365.25
    cagr = (1+ret)**(1/yrs) - 1 if yrs > 0 else 0
    dr = sub.pct_change().dropna()
    vol = dr.std()*np.sqrt(252)
    sh = (dr.mean()*252 - 0.02) / vol if vol > 0 else 0
    mdd = (sub/sub.cummax() - 1).min()
    cal = cagr/abs(mdd) if mdd < 0 else 0
    return {"CAGR":cagr,"Vol":vol,"MDD":mdd,"Calmar":cal,"Sharpe":sh,"years":yrs}


split = pd.Timestamp("2018-06-30")
mask_train = df["date"] <= split
mask_test  = df["date"] >  split
mask_full  = pd.Series(True, index=df.index)

configs = [
    ("原 T2 30/30/40 (无美股)",     {"STK":0.30, "BOND":0.30, "GOLD":0.40}),
    ("配置 A 温和 25/20/25/30",     {"STK":0.25, "SP500":0.20, "BOND":0.25, "GOLD":0.30}),
    ("配置 B 加强 20/25/25/30",     {"STK":0.20, "SP500":0.25, "BOND":0.25, "GOLD":0.30}),
    # 为了对比, 也跑无 overlay 的静态版
    ("静态 A 25/20/25/30 无T2",     {"STK":0.25, "SP500":0.20, "BOND":0.25, "GOLD":0.30}),
    ("静态 B 20/25/25/30 无T2",     {"STK":0.20, "SP500":0.25, "BOND":0.25, "GOLD":0.30}),
]

print(f"Train: {df.loc[mask_train,'date'].min().date()} → {df.loc[mask_train,'date'].max().date()}")
print(f"Test:  {df.loc[mask_test,'date'].min().date()} → {df.loc[mask_test,'date'].max().date()}")
print()

rows = []
print(f"{'策略':<28s} | {'Full':^29s} | {'Train':^29s} | {'Test':^29s}")
print(f"{'':28s} | {'CAGR':>7s} {'MDD':>7s} {'Cal':>5s} {'Shp':>5s} | "
      f"{'CAGR':>7s} {'MDD':>7s} {'Cal':>5s} {'Shp':>5s} | "
      f"{'CAGR':>7s} {'MDD':>7s} {'Cal':>5s} {'Shp':>5s}")
print("-" * 128)

for i, (name, w) in enumerate(configs):
    use_t2 = ("静态" not in name)
    nav = simulate(w, use_t2=use_t2)
    mf = metrics(nav, mask_full); mt = metrics(nav, mask_train); mx = metrics(nav, mask_test)
    rows.append({
        "name":name, "use_t2":use_t2, **{f"w_{k}":v for k,v in w.items()},
        "full_cagr":mf["CAGR"],"full_mdd":mf["MDD"],"full_cal":mf["Calmar"],"full_shp":mf["Sharpe"],
        "train_cagr":mt["CAGR"],"train_mdd":mt["MDD"],"train_cal":mt["Calmar"],"train_shp":mt["Sharpe"],
        "test_cagr":mx["CAGR"],"test_mdd":mx["MDD"],"test_cal":mx["Calmar"],"test_shp":mx["Sharpe"],
    })
    def f(m): return f"{m['CAGR']:>+6.2%} {m['MDD']:>+6.1%} {m['Calmar']:>4.2f} {m['Sharpe']:>4.2f}"
    print(f"  {name:<26s} | {f(mf)} | {f(mt)} | {f(mx)}")

# 2020 COVID + 2022 bear 美股应激
print("\n" + "="*100)
print("  美股崩盘场景应激 (用户担忧验证)")
print("="*100)
stress = [
    ("2020-02 COVID   ", (df["date"]>="2020-02-19") & (df["date"]<="2020-03-23")),
    ("2020 COVID 全年 ", (df["date"]>="2020-01-01") & (df["date"]<="2020-12-31")),
    ("2022 美股熊市   ", (df["date"]>="2022-01-01") & (df["date"]<="2022-10-31")),
    ("2022-23 全程    ", (df["date"]>="2022-01-01") & (df["date"]<="2023-12-31")),
]
# 重跑得 nav 做 stress
cfg_navs = {}
for name, w in configs:
    use_t2 = ("静态" not in name)
    cfg_navs[name] = simulate(w, use_t2=use_t2)

print(f"{'场景':<20s}  " + "  ".join(f"{c[0]:>18s}" for c in configs))
for sn, smask in stress:
    if smask.sum() < 5: continue
    line = f"  {sn:<18s}  "
    for name, _ in configs:
        sub = cfg_navs[name][smask.values]
        tot = sub.iloc[-1]/sub.iloc[0] - 1
        mdd = (sub/sub.cummax() - 1).min()
        line += f"  {tot*100:>+6.1f}% MDD {mdd*100:>+5.1f}%"
    print(line)

# 判定
print("\n" + "="*100)
print("  最终判定 (相对 '原 T2 30/30/40' Test 段)")
print("="*100)
base = rows[0]
print(f"{'策略':<28s}  {'ΔCAGR':>8s}  {'ΔMDD':>8s}  {'ΔCalmar%':>10s}  {'判定':>12s}")
print("-" * 85)
for r in rows:
    if r["name"] == base["name"]:
        print(f"  {r['name']:<26s}  {'':>8s}  {'':>8s}  {'':>10s}  {'(基准)':>12s}"); continue
    dcagr = r["test_cagr"] - base["test_cagr"]
    dmdd = r["test_mdd"] - base["test_mdd"]
    dcal = (r["test_cal"] - base["test_cal"]) / base["test_cal"] * 100 if base["test_cal"] > 0 else 0
    # 三项全通过
    ok_cagr = dcagr >= 0
    ok_mdd = dmdd >= 0  # MDD 是负的, >= 基准 means not worse
    ok_cal = dcal >= 10
    verdict = "✓ 采纳" if (ok_cagr and ok_mdd and ok_cal) else "✗ 不采纳"
    print(f"  {r['name']:<26s}  {dcagr*100:>+7.2f}pp  {dmdd*100:>+7.1f}pp  {dcal:>+9.1f}%  {verdict:>12s}")

out = pd.DataFrame(rows)
out.to_csv(os.path.join(OUT_DIR, "all_weather_5asset_oos.csv"), index=False, encoding="utf-8-sig")
print(f"\n[+] 写入 {os.path.join(OUT_DIR, 'all_weather_5asset_oos.csv')}")
