"""
高赔率小盘选股器 — 2 万实验仓用
================================================================
筛选逻辑 (可调):
  ROE     > 15%                — 赚钱能力强
  PE      < 20                 — 不太贵
  市值    < 50 亿               — 小盘才有弹性 (大盘成长空间小)
  3月涨跌  > 0                  — 市场资金流入的粗代理
  PB      > 0                  — 剔除 net asset 为负的
  ret60   > -20%                — 剔除近期暴跌 (避免接刀)

数据:
  data/fundamentals/panel_quarterly.csv  — ROE/EPS/BPS/净利润 (季度)
  data/stock_data/{SH/SZ}{code}.csv      — 本地 OHLCV

输出:
  research/factors_v2/output/high_odds_picks_latest.csv  — 全量
  research/factors_v2/output/high_odds_picks_top.csv     — Top 15 候选

用法:
  python research/factors_v2/high_odds_stock_picker.py
  python research/factors_v2/high_odds_stock_picker.py --top 20 --max_mcap 80
"""
import argparse
import glob
import os
import sys
import warnings

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
pd.set_option("display.width", 200)
pd.options.display.float_format = "{:.2f}".format

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")


def load_fundamentals():
    df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str})
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    # 取每只股最新季度
    latest = df.sort_values("report_date").groupby("code").tail(1).reset_index(drop=True)
    # 近 2 年内的数据才算"近期",超过 2 年 = 退市或停更
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=730)
    latest = latest[latest["report_date"] >= cutoff].copy()
    return latest


def annualize_eps(row):
    """YTD eps → 年化. 基于季度位置."""
    q = row["report_date"].quarter
    factor = {1: 4.0, 2: 2.0, 3: 4/3, 4: 1.0}[q]
    return row["eps"] * factor


def load_price_and_flow(code: str):
    """
    返回 (last_close, ret_3m, ret_12m, vol_3m_ratio, turnover_flag).
    vol_3m_ratio: 近 3 月成交额相对 1 年均值的倍数 (>1 = 放量)
    turnover_flag: 近 20 日换手率均值 (保证流动性, 2万规模够用但避免极冷门)
    """
    prefix = "SH" if code.startswith(("6", "9")) else "SZ" if code.startswith(("0","3")) else None
    if prefix is None: return None
    fp = os.path.join(STOCK_DIR, f"{prefix}{code}.csv")
    if not os.path.exists(fp): return None
    try:
        df = pd.read_csv(fp, encoding="utf-8-sig")
        # 兼容两种列名 (中文/英文)
        date_col = next((c for c in ["日期","date"] if c in df.columns), None)
        close_col = next((c for c in ["收盘","close"] if c in df.columns), None)
        amt_col = next((c for c in ["成交额","amount"] if c in df.columns), None)
        turn_col = next((c for c in ["换手率","turnover"] if c in df.columns), None)
        if date_col is None or close_col is None: return None
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col, close_col]).sort_values(date_col)
        if len(df) < 63: return None
        last = df.iloc[-1]
        # 如果最新日期距今 > 20 日, 已停牌/退市
        if (pd.Timestamp.today() - last[date_col]).days > 30: return None
        last_close = float(last[close_col])
        # 3 月 / 12 月收益
        if len(df) >= 63:
            ret_3m = last_close / df.iloc[-63][close_col] - 1
        else:
            ret_3m = np.nan
        if len(df) >= 252:
            ret_12m = last_close / df.iloc[-252][close_col] - 1
        else:
            ret_12m = np.nan
        # 近 60 日成交额 / 全期成交额
        vol_3m_ratio = np.nan
        if amt_col and len(df) >= 252:
            amt3 = df.tail(63)[amt_col].mean()
            amt12 = df.tail(252)[amt_col].mean()
            if amt12 > 0: vol_3m_ratio = amt3 / amt12
        # 换手
        turn20 = np.nan
        if turn_col and len(df) >= 20:
            turn20 = df.tail(20)[turn_col].mean()
        return dict(last_close=last_close, ret_3m=ret_3m, ret_12m=ret_12m,
                    vol_3m_ratio=vol_3m_ratio, turn20=turn20, last_date=last[date_col].date())
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    # 默认: 现实化 (严格条件 A 股几乎无货)
    # "ROE>15% + 市值<50亿 + PE<20" 全 A 只 7 只, 叠加动量 = 0 只.
    # 放宽到 ROE>10 + 市值<150亿 更匹配 A 股结构.
    ap.add_argument("--roe_min", type=float, default=10.0)
    ap.add_argument("--pe_max", type=float, default=25.0)
    ap.add_argument("--pe_min", type=float, default=5.0, help="防过低 PE (通常亏损 + 一次性大收益)")
    ap.add_argument("--max_mcap", type=float, default=150.0, help="市值上限 (亿元)")
    ap.add_argument("--min_mcap", type=float, default=15.0, help="市值下限 (避免微盘流动性)")
    ap.add_argument("--min_turn20", type=float, default=0.3, help="近 20 日日均换手率 pct")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    print(f"[+] 加载基本面面板...")
    fund = load_fundamentals()
    print(f"    {len(fund)} 只股 (近 2 年内有财报)")
    print(f"    最新季度分布: {fund['report_date'].max().date()}, "
          f"众数 {fund['report_date'].mode().iloc[0].date()}")

    # 剔除 NaN 基础字段
    fund = fund.dropna(subset=["eps","net_profit","bps","roe"])
    fund = fund[fund["eps"].abs() > 0.01]  # 剔除 eps 极小的 (除以会爆)

    # 年化 EPS
    fund["eps_ann"] = fund.apply(annualize_eps, axis=1)
    # 总股本 (亿股) = 净利润 / eps, 两者同期 (累计), 比值即股本
    fund["shares_out_yi"] = (fund["net_profit"] / fund["eps"]).abs() / 1e8

    # 抓价格
    print(f"[+] 抓本地价格 + 3月/12月收益...")
    rows = []
    for code in fund["code"]:
        p = load_price_and_flow(code)
        if p is None:
            rows.append({"code": code})
        else:
            rows.append({"code": code, **p})
    price_df = pd.DataFrame(rows)
    print(f"    {price_df['last_close'].notna().sum()}/{len(price_df)} 只股抓到价格")

    df = fund.merge(price_df, on="code", how="left").dropna(subset=["last_close"])

    # 市值 + PE
    df["market_cap_yi"] = df["last_close"] * df["shares_out_yi"]
    df["pe_ann"] = df["last_close"] / df["eps_ann"]
    df["pb"] = df["last_close"] / df["bps"]

    print(f"[+] 过滤筛选...")
    before = len(df)
    pre = df.copy()
    df = df[(df["roe"] > args.roe_min) &
            (df["pe_ann"] > args.pe_min) & (df["pe_ann"] < args.pe_max) &
            (df["market_cap_yi"] > args.min_mcap) & (df["market_cap_yi"] < args.max_mcap) &
            (df["pb"] > 0) & (df["pb"] < 10) &
            (df["ret_3m"] > 0) &
            (df["ret_12m"] > -0.20) &  # 剔除接刀
            (df["turn20"].fillna(0) > args.min_turn20)]
    print(f"    筛前 {before} → 筛后 {len(df)}")

    if len(df) == 0:
        print("    [!] 无标的通过, 放松条件后重试 (试用 --pe_max 30 --max_mcap 80)")
        return

    # 评分: 越小越好 PE, 越大越好 ROE, 近期动量适中 (不要过热)
    # 综合得分 = z(ROE) + z(-PE) + z(-市值) + z(ret_3m) — 都往 "好" 方向对齐
    for c, sign in [("roe", 1), ("pe_ann", -1), ("market_cap_yi", -1), ("ret_3m", 1)]:
        z = (df[c] - df[c].mean()) / df[c].std(ddof=0)
        df[f"z_{c}"] = z * sign
    df["score"] = df[["z_roe","z_pe_ann","z_market_cap_yi","z_ret_3m"]].sum(axis=1)

    # 输出
    cols_out = ["code","name","industry","report_date","roe","pe_ann","pb",
                "market_cap_yi","eps_ann","last_close","ret_3m","ret_12m",
                "turn20","vol_3m_ratio","score"]
    out_all = df.sort_values("score", ascending=False)[cols_out]
    out_top = out_all.head(args.top)

    path_all = os.path.join(OUT_DIR, "high_odds_picks_latest.csv")
    path_top = os.path.join(OUT_DIR, "high_odds_picks_top.csv")
    out_all.to_csv(path_all, index=False, encoding="utf-8-sig")
    out_top.to_csv(path_top, index=False, encoding="utf-8-sig")

    print(f"\n=== Top {args.top} 高赔率候选 ===")
    show = out_top.copy()
    show["roe"] = show["roe"].map("{:.1f}%".format)
    show["pe_ann"] = show["pe_ann"].map("{:.1f}".format)
    show["pb"] = show["pb"].map("{:.1f}".format)
    show["market_cap_yi"] = show["market_cap_yi"].map("{:.1f}亿".format)
    show["ret_3m"] = (show["ret_3m"]*100).map("{:+.1f}%".format)
    show["ret_12m"] = (show["ret_12m"]*100).map("{:+.1f}%".format)
    show["turn20"] = show["turn20"].map("{:.2f}%".format)
    print(show[["code","name","industry","roe","pe_ann","pb","market_cap_yi",
                "ret_3m","ret_12m","turn20","score"]].to_string(index=False))

    print(f"\n[+] 写入 {path_all} (全量 {len(out_all)})")
    print(f"[+] 写入 {path_top} (Top {args.top})")
    # 简易分布
    print(f"\n候选群特征中位数: ROE={out_all['roe'].median():.1f}%  "
          f"PE={out_all['pe_ann'].median():.1f}  "
          f"市值={out_all['market_cap_yi'].median():.1f}亿  "
          f"3M收益={out_all['ret_3m'].median()*100:+.1f}%")


if __name__ == "__main__":
    main()
