"""
抓取基本面面板 — 东财 yjbb_em (业绩报表，批量)
================================================
每季度一次调用返回全A股的:
  ROE, 净利润同比增长, 营业总收入同比增长, 销售毛利率, 每股收益, 每股净资产, 每股经营现金流

覆盖: 2015Q1 — 最新季度 (约 40 个季度)
缓存: data/fundamentals/raw_yjbb/YYYYMMDD.parquet  (每季一份)
合并: data/fundamentals/panel_quarterly.parquet    (长表)
"""

import os
import sys
import time

for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import akshare as ak
import pandas as pd

ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW_DIR  = os.path.join(ROOT, "data", "fundamentals", "raw_yjbb")
PANEL    = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
os.makedirs(RAW_DIR, exist_ok=True)

START_YEAR = 2015


def quarter_ends(start_year: int) -> list[str]:
    """所有历史季末日期 (YYYYMMDD)，截至当前可披露的最后一季。"""
    today = pd.Timestamp.today()
    out = []
    for y in range(start_year, today.year + 1):
        for mmdd in ("0331","0630","0930","1231"):
            d = pd.Timestamp(f"{y}-{mmdd[:2]}-{mmdd[2:]}")
            if d > today: break
            out.append(d.strftime("%Y%m%d"))
    return out


def fetch_one(date: str, retries: int = 3) -> pd.DataFrame | None:
    fp = os.path.join(RAW_DIR, f"{date}.csv")
    if os.path.exists(fp):
        return pd.read_csv(fp, encoding="utf-8-sig", dtype={"股票代码": str})
    for k in range(retries):
        try:
            df = ak.stock_yjbb_em(date=date)
            if df is not None and len(df) > 100:
                df["report_date"] = pd.Timestamp(date)
                df.to_csv(fp, index=False, encoding="utf-8-sig")
                return df
        except Exception as e:
            print(f"  {date} 第{k+1}次失败: {type(e).__name__}: {str(e)[:80]}")
            time.sleep(2 + k*2)
    return None


def build_panel():
    dates = quarter_ends(START_YEAR)
    print(f"共 {len(dates)} 个季度 ({dates[0]} — {dates[-1]})\n")

    frames = []
    for i, d in enumerate(dates, 1):
        print(f"[{i}/{len(dates)}] {d}...", end=" ", flush=True)
        t0 = time.time()
        df = fetch_one(d)
        dt = time.time() - t0
        if df is None:
            print("失败，跳过")
            continue
        print(f"{len(df)} 行 ({dt:.1f}s)")
        frames.append(df)

    if not frames:
        print("未取到任何数据"); return

    panel = pd.concat(frames, ignore_index=True)
    # 标准化列名
    rename = {
        "股票代码": "code", "股票简称": "name",
        "每股收益": "eps",
        "营业总收入-营业总收入": "revenue", "营业总收入-同比增长": "rev_yoy",
        "营业总收入-季度环比增长": "rev_qoq",
        "净利润-净利润": "net_profit", "净利润-同比增长": "np_yoy",
        "净利润-季度环比增长": "np_qoq",
        "每股净资产": "bps", "净资产收益率": "roe",
        "每股经营现金流量": "ocf_ps", "销售毛利率": "gross_margin",
        "所处行业": "industry", "最新公告日期": "announce_date",
    }
    panel = panel.rename(columns={k:v for k,v in rename.items() if k in panel.columns})
    keep = ["code","name","report_date","eps","revenue","rev_yoy","rev_qoq",
            "net_profit","np_yoy","np_qoq","bps","roe","ocf_ps","gross_margin",
            "industry","announce_date"]
    panel = panel[[c for c in keep if c in panel.columns]]
    panel["announce_date"] = pd.to_datetime(panel["announce_date"], errors="coerce")

    # D1 fix (2026-05-24 audit): akshare yjbb_em returns full A-share + 北交所 +
    # B-shares + ETF residuals (~11,757 codes). baostock OHLCV only covers SH/SZ
    # main + ChiNext + STAR (~5,500). Previously the panel was saved unfiltered,
    # making DataBundle.load()'s OHLCV-coverage audit fail at 6.9% < 30% threshold.
    # Filter at source so downstream self_test + Backtest see only the codes for
    # which OHLCV data is reachable.
    A_SHARE_PREFIXES = ("000", "001", "002", "003", "300", "600", "601", "603", "605", "688")
    panel["code"] = panel["code"].astype(str).str.zfill(6)
    panel_full = panel.copy()
    panel = panel[panel["code"].str.startswith(A_SHARE_PREFIXES)].copy()
    n_dropped = len(panel_full) - len(panel)
    if n_dropped > 0:
        print(f"\nD1 filter: dropped {n_dropped:,} rows of non-A-share codes "
              f"(北交所/B股/ETF residuals); panel now {len(panel):,} rows, "
              f"{panel['code'].nunique()} codes.")
        # Save the unfiltered version as backup for audit
        backup_path = PANEL.replace(".csv", "_full.csv")
        panel_full.to_csv(backup_path, index=False, encoding="utf-8-sig")
        print(f"  unfiltered backup → {backup_path}")

    # 去重 (同一code+report_date取最新announce_date)
    panel = panel.sort_values(["code","report_date","announce_date"]).drop_duplicates(
        subset=["code","report_date"], keep="last")

    panel.to_csv(PANEL, index=False, encoding="utf-8-sig")
    print(f"\n面板 -> {PANEL}")
    print(f"  {len(panel):,} 行 | {panel['code'].nunique()} 只股 | "
          f"{panel['report_date'].min().date()} — {panel['report_date'].max().date()}")
    print(f"\n字段覆盖率 (非空占比):")
    for col in ["roe","np_yoy","rev_yoy","gross_margin","ocf_ps","bps"]:
        if col in panel.columns:
            cov = panel[col].notna().mean()
            print(f"  {col:<15s}  {cov*100:>5.1f}%")


if __name__ == "__main__":
    build_panel()
