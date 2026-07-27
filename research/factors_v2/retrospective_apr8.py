"""
4月8日信号回顾 — 如果4月8日收盘后运行信号，4月9日开盘买入，现在结果如何？

逻辑：
  1. 以2026-04-08收盘数据计算cnt28（无出货信号池）
  2. 拉取4月3日-8日涨停记录，识别热点板块
  3. 筛选：热点板块 × 干净 × 4月8日未涨停
  4. 买入价 = 4月9日开盘（T+1）
  5. 当前价 = 最新收盘价（4月17或18日）
  6. 计算持仓收益
"""

import glob, os, sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
SIGNAL_DATE    = pd.Timestamp("2026-04-08")   # 信号日（收盘后）
ENTRY_DATE     = pd.Timestamp("2026-04-09")   # 次日开盘买入
TOP_SECTOR_N   = 5
HISTORY_DAYS   = 10   # 涨停历史天数


# ── 主板过滤 ─────────────────────────────────────────────────────── #
def is_excluded(sym: str) -> bool:
    code = sym[2:]
    if sym.startswith("SH"):
        if code[:3] in {"510","511","512","513","514","515","516","517",
                        "518","519","588","688","689"}: return True
        if code[:2] == "56": return True
    if sym.startswith("SZ"):
        if code[:3] in {"159","300","301","302"}: return True
    if code[:1] in {"8","4"}: return True
    return False


# ── cnt28因子（以SIGNAL_DATE为截止）──────────────────────────────── #
def build_clean_pool_at(signal_date: pd.Timestamp) -> pd.DataFrame:
    files   = glob.glob(os.path.join(STOCK_DATA_DIR, "S[HZ]*.csv"))
    cutoff  = signal_date - pd.Timedelta(days=80)
    rows    = []

    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        if is_excluded(sym):
            continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        except Exception:
            continue

        col_map = {}
        for col in df.columns:
            lc = col.strip()
            if lc == "日期":     col_map[col] = "date"
            elif lc == "开盘":   col_map[col] = "open"
            elif lc == "收盘":   col_map[col] = "close"
            elif lc == "成交量": col_map[col] = "vol"
        df = df.rename(columns=col_map)
        if not all(c in df.columns for c in ["date","open","close","vol"]):
            continue

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for c in ["open","close","vol"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["date","open","close","vol"]).query("close>0").sort_values("date")

        # ★ 只用截止信号日的数据（无未来）
        df = df[(df["date"] >= cutoff) & (df["date"] <= signal_date)]
        if len(df) < 30:
            continue

        df = df.set_index("date")
        o, c, v = df["open"], df["close"], df["vol"]
        prev_c  = c.shift(1)
        hi28_o  = o.rolling(28, min_periods=1).max()
        lo28_o  = o.rolling(28, min_periods=1).min()
        o85     = lo28_o + 0.95 * (hi28_o - lo28_o)
        top15o  = (o >= o85).astype(float)
        fd15    = ((c < prev_c) & (c <= o) & (v >= 1.15 * v.shift(1))).astype(float)
        cnt28   = (top15o * fd15).rolling(28, min_periods=1).sum()

        # 4月8日当天的open（供参考）和close
        signal_row = df[df.index == signal_date]
        if signal_row.empty:
            # 信号日可能是非交易日，取最近一个
            avail = df[df.index <= signal_date]
            if avail.empty: continue
            signal_row = avail.iloc[[-1]]

        cnt_val   = float(cnt28.reindex(signal_row.index).iloc[0]) if not signal_row.empty else np.nan
        close_val = float(signal_row["close"].iloc[0])

        rows.append({
            "stock_symbol": sym,
            "stock_code":   sym[2:],
            "cnt28":        cnt_val,
            "close_apr8":   close_val,
        })

    pool = pd.DataFrame(rows)
    pool["is_clean"] = pool["cnt28"] == 0
    return pool


# ── 涨停历史（4月3日-8日）──────────────────────────────────────── #
def get_zt_history(signal_date: pd.Timestamp, days: int = 10):
    try:
        import akshare as ak
    except ImportError:
        return pd.DataFrame(), set()

    records   = []
    apr8_zt   = set()
    fetched   = 0
    target    = signal_date.date()

    for offset in range(days * 2):
        if fetched >= days:
            break
        d = target - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        date_str = d.strftime("%Y%m%d")
        try:
            df = ak.stock_zt_pool_em(date=date_str)
            if df is None or df.empty:
                continue
            fetched += 1
            sector_col = next((c for c in df.columns if "行业" in c or "板块" in c), None)
            code_col   = next((c for c in df.columns if c in ("代码","股票代码")), None)
            name_col   = next((c for c in df.columns if c in ("名称","股票名称")), None)
            if not code_col: continue
            for _, row in df.iterrows():
                records.append({
                    "date":       d,
                    "stock_code": str(row[code_col]),
                    "stock_name": str(row[name_col]) if name_col else "",
                    "sector":     str(row[sector_col]) if sector_col else "未知",
                })
            if offset == 0:
                apr8_zt = set(df[code_col].astype(str).tolist())
            print(f"  涨停池 {date_str}: {len(df)} 只", flush=True)
        except Exception as e:
            print(f"  {date_str} 失败: {e}")

    return pd.DataFrame(records) if records else pd.DataFrame(), apr8_zt


# ── 读取当前价格 ─────────────────────────────────────────────────── #
def get_current_prices(symbols: list) -> dict:
    """返回 {stock_symbol: (entry_open, latest_close, latest_date)}"""
    result = {}
    for sym in symbols:
        fp = os.path.join(STOCK_DATA_DIR, sym + ".csv")
        if not os.path.exists(fp):
            fp = os.path.join(STOCK_DATA_DIR, sym.upper() + ".csv")
        if not os.path.exists(fp):
            continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        except Exception:
            continue

        col_map = {}
        for col in df.columns:
            lc = col.strip()
            if lc == "日期":   col_map[col] = "date"
            elif lc == "开盘": col_map[col] = "open"
            elif lc == "收盘": col_map[col] = "close"
        df = df.rename(columns=col_map)
        if not all(c in df.columns for c in ["date","open","close"]):
            continue
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for c in ["open","close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna().sort_values("date")

        # 买入价：4月9日开盘（T+1）
        entry_row = df[df["date"] == ENTRY_DATE]
        if entry_row.empty:
            entry_row = df[df["date"] > SIGNAL_DATE].head(1)
        entry_open = float(entry_row["open"].iloc[0]) if not entry_row.empty else np.nan

        # 当前价：最新收盘
        latest = df[df["date"] >= SIGNAL_DATE].tail(1)
        latest_close = float(latest["close"].iloc[0]) if not latest.empty else np.nan
        latest_date  = latest["date"].iloc[0].date() if not latest.empty else None

        result[sym] = (entry_open, latest_close, latest_date)

    return result


# ── 主程序 ──────────────────────────────────────────────────────── #
def main():
    print(f"\n{'='*65}")
    print(f"4月8日信号 -> 4月9日买入 -> 现在结果如何？")
    print(f"{'='*65}\n")

    # Step 1: 干净池（以4月8日收盘为截止）
    print("Step 1: 计算4月8日干净池（cnt28=0，主板）...", flush=True)
    pool      = build_clean_pool_at(SIGNAL_DATE)
    clean     = pool[pool["is_clean"]].copy()
    clean_codes = set(clean["stock_code"].tolist())
    print(f"  全量主板股票: {len(pool)}  |  干净池: {len(clean)}")

    # Step 2: 涨停历史
    print("\nStep 2: 获取4月3日-8日涨停记录...", flush=True)
    zt_all, apr8_zt_codes = get_zt_history(SIGNAL_DATE, days=HISTORY_DAYS)
    if zt_all.empty:
        print("  [!] 无法获取涨停数据")
        return
    print(f"  历史涨停记录: {len(zt_all)} 条  |  4月8日涨停: {len(apr8_zt_codes)} 只")

    # Step 3: 热点板块（4月3-8日集中度）
    recent   = zt_all[zt_all["date"] >= (SIGNAL_DATE.date() - timedelta(days=7))]
    sector_heat = (recent.groupby("sector")
                   .agg(涨停次数=("stock_code","count"),
                        代表股=("stock_name", lambda x: "、".join(x.unique()[:4])))
                   .sort_values("涨停次数", ascending=False)
                   .reset_index())
    hot_sectors = sector_heat.head(TOP_SECTOR_N)["sector"].tolist()

    print(f"\n4月3日-8日热点板块 Top {TOP_SECTOR_N}:")
    for _, r in sector_heat.head(TOP_SECTOR_N).iterrows():
        print(f"  {r['sector']:<16s}  涨停{int(r['涨停次数'])}次  {r['代表股']}")

    # Step 4: 板块→股票映射（10日历史）
    sector_map: dict[str, set] = {}
    for _, row in zt_all.iterrows():
        s = str(row["sector"])
        sector_map.setdefault(s, set()).add(str(row["stock_code"]))

    # Step 5: 筛选候选股
    candidates = []
    for sector in hot_sectors:
        for code in sector_map.get(sector, set()):
            if code not in clean_codes:
                continue
            if code in apr8_zt_codes:
                continue   # 4月8日已涨停，排除
            sym = ("SH" + code) if code.startswith("6") else ("SZ" + code)
            cp  = clean[clean["stock_code"] == code]
            close_apr8 = float(cp["close_apr8"].iloc[0]) if not cp.empty else np.nan
            name_rows  = zt_all[zt_all["stock_code"] == code]
            name       = str(name_rows["stock_name"].iloc[0]) if not name_rows.empty else ""
            candidates.append({
                "stock_symbol": sym,
                "stock_code":   code,
                "stock_name":   name,
                "sector":       sector,
                "close_apr8":   close_apr8,
            })

    df_cand = pd.DataFrame(candidates).drop_duplicates("stock_code") if candidates else pd.DataFrame()
    print(f"\n  候选股: {len(df_cand)} 只（热点板块 × 干净 × 4月8日未涨停）")

    if df_cand.empty:
        print("  [!] 无候选股")
        return

    # Step 6: 查当前价格
    print("\nStep 3: 查询买入价（4月9日开盘）和当前价格...", flush=True)
    prices = get_current_prices(df_cand["stock_symbol"].tolist())

    rows = []
    for _, r in df_cand.iterrows():
        sym = r["stock_symbol"]
        p   = prices.get(sym, (np.nan, np.nan, None))
        entry, latest, latest_dt = p
        ret = (latest / entry - 1) if (entry and not np.isnan(entry)
                                        and latest and not np.isnan(latest)) else np.nan
        rows.append({
            "stock_symbol": sym,
            "stock_name":   r["stock_name"],
            "sector":       r["sector"],
            "close_apr8":   r["close_apr8"],
            "entry_apr9":   entry,
            "latest_close": latest,
            "latest_date":  latest_dt,
            "ret":          ret,
        })

    df_result = pd.DataFrame(rows).dropna(subset=["ret"]).sort_values("ret", ascending=False)

    # ── 输出 ────────────────────────────────────────────────────── #
    print(f"\n{'='*65}")
    print(f"结果：4月9日买入 -> {df_result['latest_date'].iloc[0] if not df_result.empty else '?'} 收盘")
    print(f"{'='*65}")

    win  = (df_result["ret"] > 0).sum()
    lose = (df_result["ret"] <= 0).sum()
    avg  = df_result["ret"].mean()

    print(f"\n  胜率: {win}/{win+lose} = {win/(win+lose):.0%}   平均收益: {avg:+.2%}")
    print()

    # 按板块分组显示
    for sector in hot_sectors:
        sub = df_result[df_result["sector"] == sector]
        if sub.empty:
            continue
        sub_avg = sub["ret"].mean()
        print(f"  【{sector}】平均 {sub_avg:+.1%}")
        print(f"  {'代码':<10s} {'名称':<10s} {'4/8收盘':>8s} {'4/9开盘':>8s} {'现价':>8s} {'收益':>8s}")
        print(f"  {'-'*56}")
        for _, r in sub.iterrows():
            arrow = "^" if r["ret"] > 0 else "v"
            print(f"  {r['stock_symbol']:<10s} {r['stock_name']:<10s} "
                  f"{r['close_apr8']:>8.2f} {r['entry_apr9']:>8.2f} "
                  f"{r['latest_close']:>8.2f} {r['ret']:>+7.1%} {arrow}")
        print()

    # 最佳和最差
    if len(df_result) >= 3:
        print(f"  最佳: {df_result.iloc[0]['stock_name']} {df_result.iloc[0]['ret']:+.1%}")
        print(f"  最差: {df_result.iloc[-1]['stock_name']} {df_result.iloc[-1]['ret']:+.1%}")

    print(f"\n  注意：4月8日是关税暴跌后低点，4月9日美国宣布90天暂停关税 -> 大幅高开")
    print(f"  这个信号受益于外部事件，不代表因子本身能持续产生这种收益\n")


if __name__ == "__main__":
    main()
