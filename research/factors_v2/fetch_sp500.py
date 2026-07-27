"""
抓 SP500 长历史 + 拼到 long_history_4asset.csv → _5asset.csv
================================================================
注: A 股投资者实际买美股 QDII ETF 513500 (始于 2013-12),
但长周期验证用 SP500 指数本身 (更干净, 不受 QDII 溢价影响).
生产信号切到 513500 时可直接拼接.
"""
import os, sys
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

for _k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

import pandas as pd
import akshare as ak

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
IN_CSV  = os.path.join(OUT_DIR, "long_history_4asset.csv")
OUT_CSV = os.path.join(OUT_DIR, "long_history_5asset.csv")

# 1. 拉 SP500
print("[+] 抓 SP500 via sina...")
sp = ak.index_us_stock_sina(symbol=".INX")
sp["date"] = pd.to_datetime(sp["date"])
sp = sp.sort_values("date").reset_index(drop=True)
sp["SP500"] = pd.to_numeric(sp["close"], errors="coerce")
sp = sp[["date","SP500"]].dropna()
print(f"    SP500: {len(sp)} 天, {sp.date.min().date()} → {sp.date.max().date()}")

# 2. 读原 4 asset
df = pd.read_csv(IN_CSV, encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])
print(f"[+] 原 4asset: {len(df)} 天, {df.date.min().date()} → {df.date.max().date()}")

# 3. 日历对齐: SP500 在美东周六/周日/美股休市时没数据,
#    A 股日历有时 SP500 缺 (前日值用), SP500 有时 A 股缺 (忽略 SP500 该日).
#    用 A 股日历为准, SP500 forward-fill.
merged = df.merge(sp, on="date", how="left")
missing_before = merged["SP500"].isna().sum()
merged["SP500"] = merged["SP500"].ffill()
# 若最早几天 SP500 尚未有数据, 反向填 (只影响初期前几天)
merged["SP500"] = merged["SP500"].bfill()
print(f"    缺失 SP500 填补: {missing_before} 天 ffill + bfill")

# 4. 归一化: 所有资产从 2010-06-01 起 =1 (保留原 DIV/GEM/HS300/BOND/GOLD 不变, 新 SP500 也从该日归一)
start = merged["date"].iloc[0]
sp0 = merged["SP500"].iloc[0]
merged["SP500"] = merged["SP500"] / sp0
print(f"    SP500 归一到 {start.date()} = 1.0, 最新 {merged['SP500'].iloc[-1]:.4f}")

# 5. 检查无 NaN
assert not merged.isna().any().any(), "合并后有 NaN!"

merged.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
print(f"[+] 写入 {OUT_CSV} ({len(merged)} 行)")

# 6. 买持有对比
print("\n=== 各资产 16 年 CAGR 对比 ===")
yrs = (merged.date.iloc[-1] - merged.date.iloc[0]).days / 365.25
for c in ["DIV","GEM","HS300","BOND","GOLD","SP500"]:
    if c not in merged.columns: continue
    ret = merged[c].iloc[-1] / merged[c].iloc[0] - 1
    cagr = (1+ret)**(1/yrs) - 1
    nav = merged[c] / merged[c].iloc[0]
    mdd = (nav / nav.cummax() - 1).min()
    print(f"  {c:6s}  CAGR {cagr*100:>6.2f}%   MDD {mdd*100:>6.1f}%   total {ret*100:>+7.1f}%")
