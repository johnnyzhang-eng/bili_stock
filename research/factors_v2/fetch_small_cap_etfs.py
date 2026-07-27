"""拉 CSI500 (510500) 和 CSI1000 (512100) ETF 作为小盘基准。"""
import os
import sys

for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import akshare as ak
import pandas as pd

ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE = os.path.join(ROOT, "data", "market_cache")

for code, name in [("510500","中证500"), ("512100","中证1000"), ("159915","创业板")]:
    fp = os.path.join(CACHE, f"etf_{code}.csv")
    if os.path.exists(fp):
        print(f"  {code} 已缓存")
        continue
    print(f"拉取 {code} {name}...", flush=True)
    try:
        raw = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="hfq")
        date_col = next((c for c in raw.columns if "日期" in c), raw.columns[0])
        close_col = next((c for c in raw.columns if "收盘" in c), None)
        df = pd.DataFrame({
            "date": pd.to_datetime(raw[date_col]),
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
        }).dropna().sort_values("date")
        df.to_csv(fp, index=False, encoding="utf-8-sig")
        print(f"  {len(df)} 天  {df['date'].min().date()} - {df['date'].max().date()}")
    except Exception as e:
        print(f"  失败: {e}")
