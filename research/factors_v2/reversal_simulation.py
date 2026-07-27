"""临时脚本: 2万 在基本面反转策略下的蒙特卡洛模拟"""
import os, sys, warnings, glob
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

# ── 1. 基本面 panel ────────────────────────────────────────────────────────────
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
        if q == 1:
            np_s = np_cum
        else:
            pm = (g["year"] == yr) & (g["quarter"] == q - 1)
            np_s = np_cum - g.loc[pm, "net_profit"].values[-1] if pm.any() else np.nan
        rows.append({**row.to_dict(), "np_single": np_s})
df = pd.DataFrame(rows)
df["year"] = df["year"].astype(int)
df["quarter"] = df["quarter"].astype(int)

# ── 2. 价格缓存 ────────────────────────────────────────────────────────────────
price_cache = {}
for fp in glob.glob(os.path.join(STOCK_DIR, "*.csv")):
    code = os.path.basename(fp)[2:8]
    try:
        pf = pd.read_csv(fp, encoding="utf-8-sig")
        dc = next((c for c in ["date","日期"] if c in pf.columns), None)
        cc = next((c for c in ["close","收盘"] if c in pf.columns), None)
        if not dc or not cc: continue
        pf[dc] = pd.to_datetime(pf[dc], errors="coerce")
        pf = pf.dropna(subset=[dc, cc]).sort_values(dc).reset_index(drop=True)
        price_cache[code] = pf[[dc, cc]].rename(columns={dc: "date", cc: "close"})
    except:
        pass
print(f"Price cache: {len(price_cache)} stocks")

def get_price_at(code, target_date):
    if code not in price_cache: return None
    pf = price_cache[code]
    c = pf[pf["date"] >= target_date]
    return float(c.iloc[0]["close"]) if not c.empty else None

Q_MONTH = [3, 6, 9, 12]
Q_DAY   = [31, 30, 30, 31]

# ── 3. 逐期回测，收集每期个股收益分布 ─────────────────────────────────────────
period_data = []
for yr in range(2017, 2025):
    for q in [1, 2, 3, 4]:
        rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
        sig_date = rpt_date + pd.Timedelta(days=45)
        fwd_date = sig_date + pd.Timedelta(days=180)
        avail = df[df["report_date"] <= rpt_date]
        lat = avail.sort_values("report_date").groupby("code").tail(1)
        lat = lat[(lat["year"] == yr) & (lat["quarter"] == q)].copy()
        prev = (avail[(avail["year"] == yr-1) & (avail["quarter"] == q)]
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
        stock_rets = []
        for c in sc:
            ep = get_price_at(c, sig_date)
            xp = get_price_at(c, fwd_date)
            if ep and xp and ep > 0:
                stock_rets.append(xp / ep - 1)
        if len(stock_rets) < 5: continue
        period_data.append({
            "period": f"{yr}Q{q}",
            "yr": yr, "q": q,
            "n": len(stock_rets),
            "mean_ret": np.mean(stock_rets),
            "median_ret": np.median(stock_rets),
            "std_ret": np.std(stock_rets),
            "p10": np.percentile(stock_rets, 10),
            "p25": np.percentile(stock_rets, 25),
            "p75": np.percentile(stock_rets, 75),
            "p90": np.percentile(stock_rets, 90),
            "stock_rets": stock_rets,
        })

print(f"有效回测期: {len(period_data)} 个季度")

# ── 4. 逐期均值路径 (分散版: 买全部信号股) ────────────────────────────────────
nav_mean = 20000.0
nav_path = [nav_mean]
for p in period_data:
    nav_mean *= (1 + p["mean_ret"] - 0.0056)   # 56bp 单边成本
    nav_path.append(nav_mean)

years = len(period_data) / 4
print(f"\n=== 分散版 (买全部信号股 ~700只等权, 2017Q1→2024Q4) ===")
print(f"起始: 2万   终值: {nav_mean/10000:.1f} 万   ({years:.0f} 年)")
print(f"年化 CAGR: {((nav_mean/20000)**(1/years)-1)*100:.1f}%")

# ── 5. Monte Carlo: 集中 N 只 ─────────────────────────────────────────────────
all_rets = [p["stock_rets"] for p in period_data if len(p["stock_rets"]) >= 5]
COST = 0.0112   # 买 + 卖 round-trip 56bp × 2 = 1.12%
INITIAL = 20000
N_SIM = 20000
np.random.seed(42)

print(f"\n=== Monte Carlo ({N_SIM} 次, 2017-2024 实际分布, 含 1.12% 成本) ===")
print(f"{'持仓':>6} | {'p10':>7} | {'p25':>7} | {'中位':>7} | {'p75':>7} | {'p90':>7} | {'亏损率':>6} | {'翻倍':>5} | {'5倍':>5}")
print("-" * 72)

for n_stocks in [1, 3, 5, 10]:
    finals = []
    for _ in range(N_SIM):
        nav = INITIAL
        for period_rets in all_rets:
            picks = np.random.choice(period_rets, size=min(n_stocks, len(period_rets)), replace=False)
            nav *= (1 + picks.mean() - COST)
        finals.append(nav)
    finals = np.array(finals)
    print(f"  {n_stocks} 只   | "
          f"{np.percentile(finals,10)/10000:>5.1f}万 | "
          f"{np.percentile(finals,25)/10000:>5.1f}万 | "
          f"{np.median(finals)/10000:>5.1f}万 | "
          f"{np.percentile(finals,75)/10000:>5.1f}万 | "
          f"{np.percentile(finals,90)/10000:>5.1f}万 | "
          f"{(finals<INITIAL).mean()*100:>5.0f}%  | "
          f"{(finals>INITIAL*2).mean()*100:>4.0f}%  | "
          f"{(finals>INITIAL*5).mean()*100:>4.0f}%")

# ── 6. 每期收益分布汇总 ────────────────────────────────────────────────────────
all_mean_rets = [p["mean_ret"] for p in period_data]
print(f"\n每季度均值收益: 均值 {np.mean(all_mean_rets)*100:+.1f}%  "
      f"std {np.std(all_mean_rets)*100:.1f}%  "
      f"最差 {min(all_mean_rets)*100:.1f}%  最好 {max(all_mean_rets)*100:.1f}%")
print(f"注: 这是全部信号股平均. 单只股票 std 约 {np.mean([p['std_ret'] for p in period_data])*100:.0f}%/期")
