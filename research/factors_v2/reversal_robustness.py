"""
反转信号鲁棒性验证
==================
测试两个维度:
  1. 披露延迟 (delay): 45 / 75 / 120 天 — 检验未来函数
     正确延迟: Q1/Q3=45天, H1=75天, Q4=130天 (各对应截止日后+15天)
  2. 持仓期 (hold): 3M / 6M / 9M — 检验6个月是否被拟合
如果结果在两个维度都稳定 → 信号是真实的.
如果只有特定 delay + hold 组合好 → 过拟合.
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

import numpy as np
import pandas as pd

ROOT      = os.path.abspath(".")
PANEL     = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")

# ── 1. Panel ──────────────────────────────────────────────────────────────────
raw = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
raw["report_date"] = pd.to_datetime(raw["report_date"], errors="coerce")
raw = raw.dropna(subset=["report_date", "net_profit", "eps"])
raw = raw[raw["eps"].abs() > 1e-6]
raw["quarter"] = raw["report_date"].dt.quarter.astype(int)
raw["year"]    = raw["report_date"].dt.year.astype(int)

rows = []
for code, g in raw.groupby("code", sort=False):
    g = g.sort_values("report_date").reset_index(drop=True)
    for i, row in g.iterrows():
        q, yr, np_cum = int(row["quarter"]), int(row["year"]), row["net_profit"]
        np_s = np_cum if q == 1 else (
            np_cum - g.loc[(g["year"]==yr)&(g["quarter"]==q-1), "net_profit"].values[-1]
            if ((g["year"]==yr)&(g["quarter"]==q-1)).any() else np.nan
        )
        rows.append({**row.to_dict(), "np_single": np_s})
df = pd.DataFrame(rows)
df["year"]    = df["year"].astype(int)
df["quarter"] = df["quarter"].astype(int)

# ── 2. 价格缓存 ───────────────────────────────────────────────────────────────
price_cache = {}
for fp in glob.glob(os.path.join(STOCK_DIR, "*.csv")):
    code = os.path.basename(fp)[2:8]
    try:
        pf = pd.read_csv(fp, encoding="utf-8-sig")
        dc = next((c for c in ["date","日期"] if c in pf.columns), None)
        cc = next((c for c in ["close","收盘"] if c in pf.columns), None)
        if not dc or not cc: continue
        pf[dc] = pd.to_datetime(pf[dc], errors="coerce")
        pf = pf.dropna(subset=[dc,cc]).sort_values(dc).reset_index(drop=True)
        price_cache[code] = pf[[dc,cc]].rename(columns={dc:"date",cc:"close"})
    except: pass
print(f"Price cache: {len(price_cache)} stocks\n")

def get_price_at(code, target_date):
    if code not in price_cache: return None
    pf = price_cache[code]
    c = pf[pf["date"] >= target_date]
    return float(c.iloc[0]["close"]) if not c.empty else None

Q_MONTH = [3, 6, 9, 12]
Q_DAY   = [31, 30, 30, 31]

# 正确披露延迟: 各季度截止日 + 15天缓冲
# Q1(4/30截止)→45天, Q2(8/31截止)→77天, Q3(10/31截止)→46天, Q4(4/30截止)→120天
CORRECT_DELAY = {1: 45, 2: 77, 3: 46, 4: 130}

def run_backtest(delay_mode: str, hold_days: int):
    """
    delay_mode: 'fast'(全用45天), 'correct'(按季度正确延迟), 'conservative'(全用130天)
    hold_days:  持仓天数
    """
    results = []
    for yr in range(2017, 2025):
        for q in [1, 2, 3, 4]:
            rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
            if delay_mode == "fast":
                delay = 45
            elif delay_mode == "correct":
                delay = CORRECT_DELAY[q]
            else:  # conservative
                delay = 130
            sig_date = rpt_date + pd.Timedelta(days=delay)
            fwd_date = sig_date + pd.Timedelta(days=hold_days)

            avail = df[df["report_date"] <= rpt_date]
            lat   = avail.sort_values("report_date").groupby("code").tail(1)
            lat   = lat[(lat["year"]==yr) & (lat["quarter"]==q)].copy()
            prev  = (avail[(avail["year"]==yr-1) & (avail["quarter"]==q)]
                     [["code","np_single"]]
                     .rename(columns={"np_single":"np_prev"}))
            merged = lat.merge(prev, on="code", how="inner").dropna(subset=["np_single","np_prev"])
            if len(merged) < 10: continue

            merged["q_yoy"] = ((merged["np_single"] - merged["np_prev"])
                               / merged["np_prev"].abs().clip(lower=1e6))
            cond_a = (merged["np_prev"] < -1e7) & (merged["np_single"] > 2e7)
            cond_b = (merged["np_single"] > 0) & (merged["np_prev"] > 0) & (merged["q_yoy"] > 0.30)
            sc = merged[cond_a | cond_b]["code"].tolist()
            if not sc: continue

            fwd_rets = []
            for c in sc:
                ep = get_price_at(c, sig_date)
                xp = get_price_at(c, fwd_date)
                if ep and xp and ep > 0:
                    fwd_rets.append(xp / ep - 1)
            if len(fwd_rets) < 5: continue
            results.append({"yr": yr, "q": q, "n": len(fwd_rets),
                            "avg_ret": np.mean(fwd_rets)})
    return pd.DataFrame(results)

import akshare as ak
print("Loading HS300...")
idx = ak.stock_zh_index_daily(symbol="sh000300").sort_values("date").reset_index(drop=True)
idx["date"] = pd.to_datetime(idx["date"])

def hs_fwd(sig_date, fwd_date):
    e = idx[idx["date"] >= sig_date]
    x = idx[idx["date"] >= fwd_date]
    return (float(x.iloc[0]["close"]) / float(e.iloc[0]["close"]) - 1
            if not e.empty and not x.empty else np.nan)

def summarize(res, delay_mode, hold_days):
    if res.empty: return None
    alphas = []
    for _, r in res.iterrows():
        sd = pd.Timestamp(int(r["yr"]), Q_MONTH[int(r["q"])-1], Q_DAY[int(r["q"])-1])
        if delay_mode == "fast":        sd += pd.Timedelta(days=45)
        elif delay_mode == "correct":   sd += pd.Timedelta(days=CORRECT_DELAY[int(r["q"])])
        else:                           sd += pd.Timedelta(days=130)
        fd = sd + pd.Timedelta(days=hold_days)
        hs = hs_fwd(sd, fd)
        alphas.append(r["avg_ret"] - hs if not np.isnan(hs) else np.nan)
    valid = [a for a in alphas if not np.isnan(a)]
    win   = sum(a > 0 for a in valid) / len(valid) if valid else 0
    return {
        "periods": len(res),
        "avg_n":   res["n"].mean(),
        "avg_ret": res["avg_ret"].mean(),
        "alpha":   np.nanmean(valid),
        "win":     win,
    }

# ── 3. 网格测试 ───────────────────────────────────────────────────────────────
delays = [("fast (45天, 含前视)", "fast"),
          ("correct (按季度截止日)", "correct"),
          ("conservative (全130天)", "conservative")]
holds  = [("3个月", 90), ("6个月", 180), ("9个月", 270)]

print("=" * 80)
print("  鲁棒性矩阵: 横轴=持仓时长, 纵轴=披露延迟")
print("=" * 80)
header = f"  {'延迟方式':<22s}"
for hname, _ in holds:
    header += f"  {hname:>24s}"
print(header)
print("  " + "-"*74)

subheader = f"  {'':22s}"
for _ in holds:
    subheader += f"  {'均Alpha':>7s} {'胜率':>5s} {'均N':>5s}"
print(subheader)
print("  " + "-"*74)

results_grid = {}
for dname, dmode in delays:
    row_str = f"  {dname:<22s}"
    for hname, hdays in holds:
        key = (dmode, hdays)
        res = run_backtest(dmode, hdays)
        s   = summarize(res, dmode, hdays)
        results_grid[key] = s
        if s:
            row_str += f"  {s['alpha']*100:>+6.1f}%  {s['win']*100:>3.0f}%  {s['avg_n']:>4.0f}"
        else:
            row_str += f"  {'N/A':>6s}  {'':>3s}  {'':>4s}"
    print(row_str)

print()
print("  解读:")
print("  - 如果只有 fast+6M 组合好, 其余差 → 过拟合")
print("  - 如果多数格子 Alpha>0 且胜率>55% → 信号鲁棒")
print()

# ── 4. 最关键对比: fast Q4 vs correct Q4 ────────────────────────────────────
print("=" * 60)
print("  Q4 信号前视偏差检验 (受影响最大的季度)")
print("=" * 60)
for dname, dmode in [("fast 45天", "fast"), ("correct 130天", "correct")]:
    res = run_backtest(dmode, 180)
    q4  = res[res["q"] == 4] if not res.empty else pd.DataFrame()
    if q4.empty:
        print(f"  {dname}: 无Q4数据")
        continue
    alphas_q4 = []
    for _, r in q4.iterrows():
        delay = 45 if dmode == "fast" else 130
        sd = pd.Timestamp(int(r["yr"]), 12, 31) + pd.Timedelta(days=delay)
        fd = sd + pd.Timedelta(days=180)
        hs = hs_fwd(sd, fd)
        alphas_q4.append(r["avg_ret"] - hs if not np.isnan(hs) else np.nan)
    valid = [a for a in alphas_q4 if not np.isnan(a)]
    win   = sum(a > 0 for a in valid) / len(valid) if valid else 0
    print(f"  {dname:<18s}  Q4 Alpha {np.nanmean(valid)*100:>+5.1f}%  胜率 {win*100:.0f}%")

print()
print("  若两者 Alpha 相近 → Q4 前视影响不大")
print("  若 fast Q4 明显高于 correct Q4 → 存在真实前视偏差")
