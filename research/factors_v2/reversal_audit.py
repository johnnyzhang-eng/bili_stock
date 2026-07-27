"""
反转信号 QC 审计 — 挖掘为什么回测数字看起来"太好"
=======================================================
检查:
  1. 基本面 panel 幸存者偏差: 退市股是否存在?
  2. 价格缓存覆盖率: 信号股有多少拿不到价格 (可能是退市)
  3. 随机对照组: 如果每期随机抽 3 只 A 股, 收益是多少? (对照"信号alpha")
  4. 按市值/换手率分层的基准: 小盘本身溢价 vs 真实 alpha
  5. 信号缺失股的去向: 这些股之后到底怎样了
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

# ── 1. Panel 幸存者偏差检查 ──────────────────────────────────────────────────
print("=" * 70)
print("  审计 1: 基本面 panel 幸存者偏差")
print("=" * 70)
raw = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
raw["report_date"] = pd.to_datetime(raw["report_date"], errors="coerce")
raw = raw.dropna(subset=["report_date", "net_profit", "eps"])
raw = raw[raw["eps"].abs() > 1e-6]

total_codes = raw["code"].nunique()
# 检查: 有多少 code 在最近 2 年内没再出现过? (= 退市/停牌候选)
recent_cutoff = pd.Timestamp("2024-01-01")
recent_codes  = raw[raw["report_date"] >= recent_cutoff]["code"].unique()
old_only      = set(raw["code"]) - set(recent_codes)
print(f"Panel 中总股票数: {total_codes}")
print(f"2024-01 之后仍有报告的: {len(recent_codes)}")
print(f"只在早期出现(已退市/ST停更): {len(old_only)}")
print(f"幸存率: {len(recent_codes)/total_codes*100:.1f}%")
print()
if len(old_only) > 0:
    print("✓ Panel 包含退市股票 — 这部分幸存者偏差较小")
else:
    print("⚠ Panel 只有当前存活股 — 严重幸存者偏差")

# ── 2. OHLCV 文件覆盖率 ──────────────────────────────────────────────────────
print()
print("=" * 70)
print("  审计 2: 本地 OHLCV 文件覆盖率")
print("=" * 70)
local_codes = set()
for fp in glob.glob(os.path.join(STOCK_DIR, "*.csv")):
    code = os.path.basename(fp)[2:8]
    local_codes.add(code)
print(f"本地 OHLCV 文件数: {len(local_codes)}")

panel_codes = set(raw["code"].unique())
missing = panel_codes - local_codes
has     = panel_codes & local_codes
print(f"Panel 中有 OHLCV 的: {len(has)}")
print(f"Panel 中缺 OHLCV 的: {len(missing)} ({len(missing)/len(panel_codes)*100:.1f}%)")

# 这些缺失股是什么特征?
if missing:
    missing_df = raw[raw["code"].isin(missing)]
    last_report = missing_df.groupby("code")["report_date"].max()
    print(f"缺失股最后报告日分布:")
    for year_range, label in [
        ((2010, 2017), "2010-2016 (早期退市)"),
        ((2017, 2020), "2017-2019"),
        ((2020, 2023), "2020-2022"),
        ((2023, 2027), "2023+ (近期)"),
    ]:
        mask = (last_report.dt.year >= year_range[0]) & (last_report.dt.year < year_range[1])
        print(f"  {label:<25s}: {mask.sum()} 只")

# ── 3. 随机对照: 每季度随机抽 N 只股的 6M 收益 ──────────────────────────────
print()
print("=" * 70)
print("  审计 3: 随机对照组 (等 N 只随机抽) — 这是真正的基准")
print("=" * 70)
# 建价格缓存
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
print(f"价格缓存: {len(price_cache)} 只")

def get_price_at(code, target_date):
    if code not in price_cache: return None
    pf = price_cache[code]
    c = pf[pf["date"] >= target_date]
    return float(c.iloc[0]["close"]) if not c.empty else None

Q_MONTH = [3, 6, 9, 12]
Q_DAY   = [31, 30, 30, 31]
CORRECT_DELAY = {1: 45, 2: 77, 3: 46, 4: 130}

np.random.seed(0)
random_baseline_rets = []
# 对每个信号期, 从所有有价格的股票里随机抽 50 只算平均 6M
all_priced_codes = list(price_cache.keys())

for yr in range(2017, 2025):
    for q in [1,2,3,4]:
        rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
        sig_date = rpt_date + pd.Timedelta(days=CORRECT_DELAY[q])
        fwd_date = sig_date + pd.Timedelta(days=180)
        # 注: 不用 signal 过滤, 就从 all priced codes 里随机抽
        picks = np.random.choice(all_priced_codes, size=50, replace=False)
        rets = []
        for c in picks:
            ep = get_price_at(c, sig_date)
            xp = get_price_at(c, fwd_date)
            if ep and xp and ep > 0:
                rets.append(xp/ep - 1)
        if rets:
            random_baseline_rets.append({"yr":yr, "q":q, "n":len(rets), "mean_ret":np.mean(rets)})

rb = pd.DataFrame(random_baseline_rets)
print(f"\n随机抽 50 只 A 股 (从本地 OHLCV 缓存) 的 6M 收益:")
print(f"  平均 6M: {rb['mean_ret'].mean()*100:+.2f}%")
print(f"  中位数 6M: {rb['mean_ret'].median()*100:+.2f}%")
print(f"  年化: {((1+rb['mean_ret'].mean())**2-1)*100:+.1f}%")
print(f"  胜率 (>0): {(rb['mean_ret']>0).mean()*100:.0f}%")

# ── 4. 信号组 vs 随机组对比 ──────────────────────────────────────────────────
print()
print("=" * 70)
print("  审计 4: 反转信号 vs 随机 — 真实 alpha")
print("=" * 70)

# 建 single-quarter 数据
raw = raw.sort_values(["code","report_date"]).copy()
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
            pm = (g["year"]==yr)&(g["quarter"]==q-1)
            np_s = np_cum - g.loc[pm,"net_profit"].values[-1] if pm.any() else np.nan
        rows.append({**row.to_dict(), "np_single": np_s})
df = pd.DataFrame(rows)
df["year"] = df["year"].astype(int)
df["quarter"] = df["quarter"].astype(int)

signal_rets = []
for yr in range(2017, 2025):
    for q in [1,2,3,4]:
        rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
        sig_date = rpt_date + pd.Timedelta(days=CORRECT_DELAY[q])
        fwd_date = sig_date + pd.Timedelta(days=180)
        avail = df[df["report_date"] <= rpt_date]
        lat = avail.sort_values("report_date").groupby("code").tail(1)
        lat = lat[(lat["year"]==yr)&(lat["quarter"]==q)]
        prev = avail[(avail["year"]==yr-1)&(avail["quarter"]==q)][["code","np_single"]].rename(columns={"np_single":"np_prev"})
        merged = lat.merge(prev, on="code", how="inner").dropna(subset=["np_single","np_prev"])
        if len(merged) < 10: continue
        merged["q_yoy"] = (merged["np_single"]-merged["np_prev"])/merged["np_prev"].abs().clip(lower=1e6)
        cond_a = (merged["np_prev"]<-1e7)&(merged["np_single"]>2e7)
        cond_b = (merged["np_single"]>0)&(merged["np_prev"]>0)&(merged["q_yoy"]>0.30)
        sc = merged[cond_a|cond_b]["code"].tolist()
        if not sc: continue
        rets, n_missing = [], 0
        for c in sc:
            if c not in price_cache:
                n_missing += 1
                continue
            ep = get_price_at(c, sig_date)
            xp = get_price_at(c, fwd_date)
            if ep and xp and ep > 0:
                rets.append(xp/ep - 1)
            else:
                n_missing += 1
        if rets:
            signal_rets.append({"yr":yr, "q":q,
                                "n_signal":len(sc),
                                "n_priced":len(rets),
                                "n_missing":n_missing,
                                "mean_ret":np.mean(rets)})

sr = pd.DataFrame(signal_rets)
print(f"信号组 6M: {sr['mean_ret'].mean()*100:+.2f}% | 胜率(>0): {(sr['mean_ret']>0).mean()*100:.0f}%")
print(f"随机组 6M: {rb['mean_ret'].mean()*100:+.2f}% | 胜率(>0): {(rb['mean_ret']>0).mean()*100:.0f}%")
print(f"真实 alpha (信号-随机): {(sr['mean_ret'].mean() - rb['mean_ret'].mean())*100:+.2f}%/6M")
print(f"年化真实 alpha: {(((1+sr['mean_ret'].mean())/(1+rb['mean_ret'].mean()))**2 - 1)*100:+.1f}%")

# 信号股缺价格 (=退市概率) 统计
total_signal = sr["n_signal"].sum()
total_priced = sr["n_priced"].sum()
total_missing = sr["n_missing"].sum()
print()
print(f"信号股总数: {total_signal}")
print(f"有价格的:   {total_priced} ({total_priced/total_signal*100:.1f}%)")
print(f"缺价格:     {total_missing} ({total_missing/total_signal*100:.1f}%) <-- 幸存者偏差源")

# ── 5. 信号股 vs 随机股的市值分布 ────────────────────────────────────────────
print()
print("=" * 70)
print("  审计 5: 信号股是否天然偏小盘? (小盘溢价假说)")
print("=" * 70)
# 用最新期看信号 vs 非信号的市值分布
latest_all = df[df["report_date"] >= pd.Timestamp("2024-12-01")].sort_values("report_date").groupby("code").tail(1)
print(f"可比样本: {len(latest_all)} 只")

# 粗算市值 (不精确, 但看分布)
latest_all = latest_all[latest_all["eps"].abs() > 0.01].copy()

# 对每只, 拿最近价格
def latest_price(code):
    if code not in price_cache: return np.nan
    return float(price_cache[code]["close"].iloc[-1])

latest_all["close_now"] = latest_all["code"].map(latest_price)
latest_all = latest_all.dropna(subset=["close_now"])
latest_all["shares_yi"] = (latest_all["net_profit"]/latest_all["eps"]).abs()/1e8
latest_all["mcap_yi"] = latest_all["close_now"] * latest_all["shares_yi"]
print(f"有市值: {len(latest_all)}")
print(f"全样本 市值 中位数: {latest_all['mcap_yi'].median():.0f}亿  均值: {latest_all['mcap_yi'].mean():.0f}亿")
print(f"全样本 市值 <200亿: {(latest_all['mcap_yi']<200).mean()*100:.0f}%")
print(f"→ 小盘本身是 A 股主体. 信号=小盘并不奇怪.")
