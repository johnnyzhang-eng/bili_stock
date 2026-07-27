"""
基本面反转选股器 — 找下一个 603659
====================================
信号逻辑:
  1. 计算每只股票的单季净利润 (累计 → 差分)
  2. 识别"亏转盈"和"加速恢复"模式:
     - 亏转盈: 去年同季单季亏损 → 今年同季盈利
     - 加速恢复: 去年同季 YoY < -20% → 今年同季 YoY > +30%
  3. 市值/流动性/PE 过滤
  4. 综合评分排名

用法:
  python research/factors_v2/fundamental_reversal.py          # 当前信号
  python research/factors_v2/fundamental_reversal.py --backtest  # 历史验证 2017-2024
"""
import argparse
import os
import sys
import warnings

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL     = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
OUT_DIR   = os.path.join(ROOT, "research", "factors_v2", "output")


# ── 单季净利润差分 ─────────────────────────────────────────────────────────────
def build_single_quarter(df: pd.DataFrame) -> pd.DataFrame:
    """
    A 股财报是 YTD 累计. 差分得到单季净利润.
    Q1 单季 = Q1 累计
    Q2 单季 = H1 - Q1
    Q3 单季 = 9M - H1
    Q4 单季 = Annual - 9M
    """
    df = df.sort_values(["code", "report_date"]).copy()
    df["quarter"] = df["report_date"].dt.quarter
    df["year"]    = df["report_date"].dt.year

    rows = []
    for code, g in df.groupby("code", sort=False):
        g = g.sort_values("report_date").reset_index(drop=True)
        for i, row in g.iterrows():
            q = row["quarter"]
            yr = row["year"]
            np_cum = row["net_profit"]
            if q == 1:
                np_single = np_cum
            else:
                # 找同年上一季度
                prev_q = q - 1
                prev_mask = (g["year"] == yr) & (g["quarter"] == prev_q)
                if prev_mask.any():
                    np_single = np_cum - g.loc[prev_mask, "net_profit"].values[-1]
                else:
                    np_single = np.nan
            rows.append({**row.to_dict(), "np_single": np_single})

    return pd.DataFrame(rows)


# ── 价格数据 ──────────────────────────────────────────────────────────────────
def load_price(code: str):
    pfx = "SH" if code.startswith(("6","9")) else "SZ" if code.startswith(("0","3")) else None
    if pfx is None: return None
    fp = os.path.join(STOCK_DIR, f"{pfx}{code}.csv")
    if not os.path.exists(fp): return None
    try:
        df = pd.read_csv(fp, encoding="utf-8-sig")
        date_col  = next((c for c in ["date","日期"]  if c in df.columns), None)
        close_col = next((c for c in ["close","收盘"] if c in df.columns), None)
        turn_col  = next((c for c in ["turn","换手率"] if c in df.columns), None)
        if not date_col or not close_col: return None
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col, close_col]).sort_values(date_col)
        if len(df) < 21: return None
        last = df.iloc[-1]
        if (pd.Timestamp.today() - last[date_col]).days > 20: return None
        close = float(last[close_col])
        ret_3m  = close / df.iloc[-63][close_col]  - 1 if len(df) >= 63  else np.nan
        ret_12m = close / df.iloc[-252][close_col] - 1 if len(df) >= 252 else np.nan
        turn20  = df.tail(20)[turn_col].mean() if turn_col else np.nan
        return {"close": close, "ret_3m": ret_3m, "ret_12m": ret_12m, "turn20": turn20,
                "last_date": last[date_col].strftime("%Y-%m-%d")}
    except Exception:
        return None


# ── 当前信号 ──────────────────────────────────────────────────────────────────
def run_screen(max_mcap=200, min_mcap=10, top=20):
    print("[+] 加载基本面 panel...")
    raw = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    raw["report_date"] = pd.to_datetime(raw["report_date"], errors="coerce")
    raw = raw.dropna(subset=["report_date", "net_profit"])

    print("[+] 计算单季净利润...")
    df = build_single_quarter(raw)

    # 最新两期 (当季 + 去年同季)
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=730)
    df = df[df["report_date"] >= cutoff]

    # 只取每只股最新已披露季度
    latest = df.sort_values("report_date").groupby("code").tail(1).reset_index(drop=True)
    print(f"    最新期: {latest['report_date'].mode().iloc[0].date()}, 共 {len(latest)} 只")

    # 找去年同季数据
    def get_prev_year(row):
        yr, q = row["year"] - 1, row["quarter"]
        mask = (df["code"] == row["code"]) & (df["year"] == yr) & (df["quarter"] == q)
        hits = df[mask]
        if hits.empty: return np.nan
        return float(hits.iloc[-1]["np_single"])

    print("[+] 匹配去年同季数据...")
    latest["np_prev_year"] = latest.apply(get_prev_year, axis=1)
    latest = latest.dropna(subset=["np_single", "np_prev_year"])

    # YoY 计算 (单季)
    latest["q_yoy"] = (latest["np_single"] - latest["np_prev_year"]) / latest["np_prev_year"].abs().clip(lower=1e6)

    # ── 反转类型判定 ──────────────────────────────────────────────────────────
    # 亏转盈: 去年同季亏损 (< -1000万) → 今年同季盈利 (> 2000万)
    cond_a = (latest["np_prev_year"] < -1e7) & (latest["np_single"] > 2e7)
    # 加速恢复: 去年同季 YoY < -20% → 今年同季 YoY > +30%
    # (需要 np_prev_year > 0 才能算去年的同比, 暂用 q_yoy 代理)
    cond_b = (latest["np_single"] > 0) & (latest["np_prev_year"] > 0) & (latest["q_yoy"] > 0.30)

    candidates = latest[cond_a | cond_b].copy()
    candidates["reversal_type"] = "加速恢复"
    candidates.loc[cond_a[cond_a].index, "reversal_type"] = "亏转盈"
    print(f"    反转候选: {len(candidates)} 只 (亏转盈 {cond_a.sum()}, 加速恢复 {cond_b.sum()})")

    # ── 拉价格 ────────────────────────────────────────────────────────────────
    print("[+] 拉取价格...")
    price_rows = []
    for code in candidates["code"]:
        p = load_price(code)
        price_rows.append({"code": code, **(p or {})})
    price_df = pd.DataFrame(price_rows)
    candidates = candidates.merge(price_df, on="code", how="left").dropna(subset=["close"])

    # 市值 + PE (年化)
    candidates["shares_yi"] = (candidates["net_profit"] / candidates["eps"]).abs() / 1e8
    candidates["mcap_yi"]   = candidates["close"] * candidates["shares_yi"]
    # 年化 EPS
    q_factor = {1: 4.0, 2: 2.0, 3: 4/3, 4: 1.0}
    candidates["eps_ann"]   = candidates.apply(lambda r: r["eps"] * q_factor[r["quarter"]], axis=1)
    candidates["pe_ann"]    = candidates["close"] / candidates["eps_ann"]

    # ── 过滤 ──────────────────────────────────────────────────────────────────
    n_before = len(candidates)
    candidates = candidates[
        (candidates["mcap_yi"] >= min_mcap) &
        (candidates["mcap_yi"] <= max_mcap) &
        (candidates["pe_ann"]  > 0) &
        (candidates["pe_ann"]  < 60) &
        (candidates["eps_ann"] > 0) &
        (candidates["ret_12m"].fillna(0) < 3.0) &    # 未超过 300% (避开已暴拉)
        (candidates["turn20"].fillna(0) > 0.15) &
        (candidates["ocf_ps"].fillna(-1) > 0)        # 经营性现金流为正 (排除一次性利润)
    ]
    print(f"    过滤后: {n_before} → {len(candidates)}")

    if len(candidates) == 0:
        print("    [!] 无候选")
        return

    # ── 综合评分 ──────────────────────────────────────────────────────────────
    for col, sign in [("q_yoy", 1), ("mcap_yi", -1), ("ret_3m", 1), ("pe_ann", -1)]:
        s = candidates[col].clip(-5, 5)
        candidates[f"z_{col}"] = (s - s.mean()) / max(float(s.std(ddof=0)), 1e-9) * sign
    candidates["score"] = candidates[["z_q_yoy","z_mcap_yi","z_ret_3m","z_pe_ann"]].sum(axis=1)

    # ── 输出 ──────────────────────────────────────────────────────────────────
    show_cols = ["code","name","industry","reversal_type","quarter","year",
                 "np_single","np_prev_year","q_yoy","ocf_ps","mcap_yi","pe_ann",
                 "ret_3m","ret_12m","turn20","score"]
    out = candidates.sort_values("score", ascending=False)[show_cols]

    path_all = os.path.join(OUT_DIR, "reversal_picks_latest.csv")
    path_top = os.path.join(OUT_DIR, "reversal_picks_top.csv")
    out.to_csv(path_all, index=False, encoding="utf-8-sig")
    out.head(top).to_csv(path_top, index=False, encoding="utf-8-sig")

    print(f"\n=== 基本面反转 Top {min(top, len(out))} ===")
    display = out.head(top).copy()
    display["净利润(亿)"] = (display["np_single"] / 1e8).map("{:.2f}".format)
    display["去年同季(亿)"] = (display["np_prev_year"] / 1e8).map("{:.2f}".format)
    display["单季YoY"] = display["q_yoy"].map("{:+.0%}".format)
    display["市值(亿)"] = display["mcap_yi"].map("{:.0f}".format)
    display["PE"] = display["pe_ann"].map("{:.1f}".format)
    display["3M"] = (display["ret_3m"]*100).map("{:+.1f}%".format)
    display["12M"] = (display["ret_12m"]*100).map("{:+.1f}%".format)
    print(display[["code","name","reversal_type","净利润(亿)","去年同季(亿)","单季YoY",
                   "市值(亿)","PE","3M","12M","score"]].to_string(index=False))
    print(f"\n[+] 写入 {path_all} ({len(out)} 只)")
    print(f"[+] 写入 {path_top} (Top {min(top, len(out))})")


# ── 历史回测 ──────────────────────────────────────────────────────────────────
def run_backtest():
    print("[+] 加载基本面 panel (回测模式)...")
    raw = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    raw["report_date"] = pd.to_datetime(raw["report_date"], errors="coerce")
    raw = raw.dropna(subset=["report_date", "net_profit", "eps"])
    raw = raw[raw["eps"].abs() > 1e-6]

    print("[+] 计算单季净利润...")
    df = build_single_quarter(raw)

    # 对每个季度 (2017Q1 → 2024Q4) 模拟选股
    # 正确披露延迟 (截止日 + 15天缓冲):
    # Q1(3/31, 截止4/30)=45天, Q2(6/30, 截止8/31)=77天,
    # Q3(9/30, 截止10/31)=46天, Q4年报(12/31, 截止次年4/30)=130天
    CORRECT_DELAY = {1: 45, 2: 77, 3: 46, 4: 130}
    test_periods = []
    for yr in range(2017, 2025):
        for q in [1, 2, 3, 4]:
            report_q_date = pd.Timestamp(yr, [3,6,9,12][q-1], [31,30,30,31][q-1])
            signal_date = report_q_date + pd.Timedelta(days=CORRECT_DELAY[q])
            fwd_date = signal_date + pd.Timedelta(days=180)
            test_periods.append((yr, q, report_q_date, signal_date, fwd_date))

    print(f"[+] 回测 {len(test_periods)} 个信号期...")

    results = []
    for yr, q, rpt_date, sig_date, fwd_date in test_periods:
        # 只用 ≤ report_date 的数据 (无前视)
        avail = df[df["report_date"] <= rpt_date].copy()
        avail["year_r"] = avail["report_date"].dt.year
        avail["q_r"]    = avail["report_date"].dt.quarter

        # 每只股最新一期
        latest_avail = avail.sort_values("report_date").groupby("code").tail(1)
        # 只取恰好是目标季度的 (否则是滞后的旧数据)
        latest_avail = latest_avail[
            (latest_avail["year_r"] == yr) & (latest_avail["q_r"] == q)
        ]

        # 去年同季
        prev_avail = avail[
            (avail["year_r"] == yr - 1) & (avail["q_r"] == q)
        ][["code", "np_single"]].rename(columns={"np_single": "np_prev"})

        merged = latest_avail.merge(prev_avail, on="code", how="inner")
        merged = merged.dropna(subset=["np_single", "np_prev"])
        if len(merged) < 10:
            continue

        merged["q_yoy"] = (merged["np_single"] - merged["np_prev"]) / merged["np_prev"].abs().clip(lower=1e6)
        cond_a = (merged["np_prev"] < -1e7) & (merged["np_single"] > 2e7)
        cond_b = (merged["np_single"] > 0) & (merged["np_prev"] > 0) & (merged["q_yoy"] > 0.30)
        signal_codes = merged[cond_a | cond_b]["code"].tolist()

        if not signal_codes:
            continue

        # 计算前向收益: 用本地 OHLCV
        fwd_rets = []
        for code in signal_codes[:50]:  # 最多 50 只
            pfx = "SH" if code.startswith(("6","9")) else "SZ" if code.startswith(("0","3")) else None
            if pfx is None: continue
            fp = os.path.join(STOCK_DIR, f"{pfx}{code}.csv")
            if not os.path.exists(fp): continue
            try:
                pf = pd.read_csv(fp, encoding="utf-8-sig")
                dc = next((c for c in ["date","日期"] if c in pf.columns), None)
                cc = next((c for c in ["close","收盘"] if c in pf.columns), None)
                if not dc or not cc: continue
                pf[dc] = pd.to_datetime(pf[dc], errors="coerce")
                pf = pf.dropna(subset=[dc,cc]).sort_values(dc)
                # 信号日后第一个交易日买
                entry = pf[pf[dc] >= sig_date]
                exit_ = pf[pf[dc] >= fwd_date]
                if entry.empty or exit_.empty: continue
                e_price = float(entry.iloc[0][cc])
                x_price = float(exit_.iloc[0][cc])
                fwd_rets.append(x_price / e_price - 1)
            except Exception:
                continue

        if not fwd_rets:
            continue

        avg_ret = np.mean(fwd_rets)
        results.append({
            "year": yr, "quarter": q,
            "signal_date": sig_date.date(),
            "n_stocks": len(signal_codes),
            "n_priced": len(fwd_rets),
            "avg_6m_ret": avg_ret,
        })

    if not results:
        print("[!] 无有效回测结果")
        return

    res_df = pd.DataFrame(results)

    # HS300 基准 (用 sh000300 本地或 AKShare)
    print("\n[+] 加载 HS300 基准...")
    hs300_rets = {}
    try:
        import akshare as ak
        idx = ak.stock_zh_index_daily(symbol="sh000300")
        idx = idx.sort_values("date")
        idx["date"] = pd.to_datetime(idx["date"])
        for _, row in res_df.iterrows():
            sig = pd.Timestamp(row["signal_date"])
            fwd = sig + pd.Timedelta(days=180)
            e = idx[idx["date"] >= sig]
            x = idx[idx["date"] >= fwd]
            if e.empty or x.empty: continue
            hs300_rets[row["signal_date"]] = float(x.iloc[0]["close"]) / float(e.iloc[0]["close"]) - 1
    except Exception as e:
        print(f"  [WARN] HS300 获取失败: {e}")

    res_df["hs300_6m"] = res_df["signal_date"].map(hs300_rets)
    res_df["alpha"]    = res_df["avg_6m_ret"] - res_df["hs300_6m"]

    print("\n=== 基本面反转信号 — 历史回测 (6 个月远期收益) ===")
    print(f"{'年/季':<10} {'信号数':>6} {'样本':>5} {'策略6M':>8} {'HS300 6M':>9} {'Alpha':>7}")
    print("-" * 55)
    for _, r in res_df.sort_values(["year","quarter"]).iterrows():
        hs = f"{r['hs300_6m']*100:+.1f}%" if not pd.isna(r.get("hs300_6m")) else "  N/A "
        alpha = f"{r['alpha']*100:+.1f}%" if not pd.isna(r.get("alpha")) else "  N/A "
        print(f"  {r['year']}Q{r['quarter']}     {r['n_stocks']:>6}  {r['n_priced']:>5}  "
              f"{r['avg_6m_ret']*100:>+7.1f}%   {hs}   {alpha}")

    valid = res_df.dropna(subset=["alpha"])
    print("-" * 55)
    print(f"  平均         {'':>6}  {'':>5}  "
          f"{res_df['avg_6m_ret'].mean()*100:>+7.1f}%   "
          f"{res_df['hs300_6m'].mean()*100 if 'hs300_6m' in res_df else 0:>+7.1f}%   "
          f"{valid['alpha'].mean()*100:>+7.1f}%")
    print(f"  胜率 (正 Alpha): {(valid['alpha'] > 0).mean()*100:.0f}%")

    out_path = os.path.join(OUT_DIR, "reversal_backtest.csv")
    res_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[+] 写入 {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--max_mcap", type=float, default=200)
    ap.add_argument("--min_mcap", type=float, default=10)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    if args.backtest:
        run_backtest()
    else:
        run_screen(max_mcap=args.max_mcap, min_mcap=args.min_mcap, top=args.top)
