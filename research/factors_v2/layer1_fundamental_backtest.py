"""
Layer 1: 纯基本面 10 年回测
===========================
规则（严格 point-in-time，无未来函数）：
  - 每 HOLD_STEP 个交易日再平衡
  - 在再平衡日 T 对每只股取最新已披露季报 (announce_date <= T)
  - 过滤: 主板 + 非 ST + ROE>=10 + 净利润 YoY>=0 + 营收 YoY>=-5% + 毛利率>=15%
          + 近 20 日均成交额 >= 2 亿
  - 打分 = 0.7*z(ROE) + 0.3*z(净利润 YoY)，取 Top K 等权
  - 费率: 买 13bp + 卖 43bp = 56bp 往返
  - 基准: 沪深 300、红利低波 ETF 512890
"""

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

ROOT       = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL      = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR  = os.path.join(ROOT, "data", "stock_data")
HS300_CSV  = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
ETF_CSV    = os.path.join(ROOT, "data", "market_cache", "etf_512890.csv")
OUT_DIR    = os.path.join(ROOT, "research", "factors_v2", "output")
os.makedirs(OUT_DIR, exist_ok=True)

START      = "2016-01-01"           # 基本面面板从 2015 开始，留 1 年缓冲拿到足够的历史披露
HOLD_STEP  = 20                     # 20 个交易日 ~ 月频
TOP_K      = 50                     # Top 50 等权
BUY_BP     = 13
SELL_BP    = 43
MIN_AMOUNT = 200e6
MIN_ROE    = 10.0
MIN_NP_YOY = 0.0
MIN_REV    = -5.0
MIN_GROSS  = 15.0


def is_main(code: str) -> bool:
    c = str(code).zfill(6)
    if c.startswith(("30","301","302","688","689")): return False
    if c.startswith(("43","83","87","88","92","4","8","9")): return False
    if c.startswith(("159","510","511","512","513","514","515","516","517","518","519","520","588","18","200","201","900")): return False
    return c.startswith(("60","000","001","002","003"))


def load_fundamentals() -> pd.DataFrame:
    df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    df["report_date"]   = pd.to_datetime(df["report_date"])
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce")
    # 缺失 announce_date 的用 report_date + 45 天兜底（平均披露时滞）
    df["announce_date"] = df["announce_date"].fillna(df["report_date"] + pd.Timedelta(days=45))
    for c in ["roe","np_yoy","rev_yoy","gross_margin"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["code"].apply(is_main)].copy()
    df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
    return df.sort_values(["code","announce_date"])


def load_prices() -> pd.DataFrame:
    files = glob.glob(os.path.join(STOCK_DIR, "S[HZ]*.csv"))
    frames = []
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        code = sym[2:]
        if not is_main(code): continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig", usecols=["日期","收盘","成交额"])
        except Exception: continue
        df.columns = ["date","close","amount"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        df = df.dropna(subset=["date","close"]).sort_values("date")
        df = df[df["date"] >= pd.Timestamp(START) - pd.Timedelta(days=60)]
        if len(df) < 40: continue
        df["code"] = code
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_benchmark(path: str, start: pd.Timestamp) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date")
    return df[df["date"] >= start][["date","close"]].reset_index(drop=True)


def get_fund_snapshot(fund: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """取截至 as_of 每只股最新已披露季报。"""
    valid = fund[fund["announce_date"] <= as_of]
    if len(valid) == 0: return pd.DataFrame()
    # 每只股取 announce_date 最新
    latest = valid.groupby("code").tail(1)
    # 时效: 超过 9 个月未更新的丢弃（一般最多两季度一个报告）
    cutoff = as_of - pd.Timedelta(days=270)
    latest = latest[latest["announce_date"] >= cutoff]
    return latest


def pick_topk(snap: pd.DataFrame, avg_amt: pd.Series, k: int) -> list[str]:
    df = snap.copy()
    df = df[df["roe"] >= MIN_ROE]
    df = df[df["np_yoy"] >= MIN_NP_YOY]
    df = df[df["rev_yoy"] >= MIN_REV]
    df = df[df["gross_margin"] >= MIN_GROSS]
    # 流动性过滤
    df["amt"] = df["code"].map(avg_amt)
    df = df[df["amt"] >= MIN_AMOUNT]
    if len(df) < k: return df["code"].tolist()
    # 打分
    for col in ["roe","np_yoy"]:
        s = df[col]
        df[f"{col}_z"] = (s - s.mean()) / (s.std() + 1e-9)
    df["score"] = 0.7 * df["roe_z"] + 0.3 * df["np_yoy_z"]
    return df.nlargest(k, "score")["code"].tolist()


def backtest(prices: pd.DataFrame, fund: pd.DataFrame) -> pd.DataFrame:
    # 宽表: 日期 × 代码 -> close, amount
    prices = prices.sort_values(["code","date"])
    wide_close = prices.pivot(index="date", columns="code", values="close")
    wide_amt   = prices.pivot(index="date", columns="code", values="amount")

    dates = wide_close.index
    dates = dates[dates >= pd.Timestamp(START)]
    rebal_dates = [dates[i] for i in range(0, len(dates), HOLD_STEP)]

    rows = []
    prev_hold: set | None = None
    for i, t in enumerate(rebal_dates):
        if i + 1 >= len(rebal_dates): break
        t_next = rebal_dates[i+1]
        # 流动性: 过去 20 交易日均成交额
        lookback = wide_amt.loc[:t].tail(20)
        avg_amt = lookback.mean()

        snap = get_fund_snapshot(fund, t)
        if len(snap) == 0: continue

        holdings = pick_topk(snap, avg_amt, TOP_K)
        if len(holdings) < 5: continue

        # 期间收益: t 收盘买入, t_next 收盘卖出, 等权
        p_t    = wide_close.loc[t,  holdings]
        p_next = wide_close.loc[t_next, holdings]
        ret = (p_next / p_t - 1).replace([np.inf,-np.inf], np.nan).dropna()
        if len(ret) == 0: continue
        period_ret = float(ret.mean())

        # 换手
        if prev_hold is None:
            turnover = 1.0
        else:
            new_in = set(holdings) - prev_hold
            turnover = len(new_in) / len(holdings)
        cost = turnover * (BUY_BP + SELL_BP) / 10000
        period_ret_net = period_ret - cost

        rows.append({
            "date": t, "next_date": t_next, "n_holdings": len(holdings),
            "period_ret": period_ret, "turnover": turnover,
            "cost": cost, "period_ret_net": period_ret_net,
        })
        prev_hold = set(holdings)

    return pd.DataFrame(rows)


def metrics(eq: pd.Series, name: str, periods_per_year: float = 252/HOLD_STEP) -> dict:
    """eq 是按再平衡日采样的等权净值（~月频），按 periods_per_year 年化。"""
    ret = eq.pct_change().dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr  = (1 + total) ** (1/years) - 1 if years > 0 else np.nan
    dd    = eq / eq.cummax() - 1
    mdd   = dd.min()
    vol   = ret.std() * np.sqrt(periods_per_year)
    sharpe = (cagr - 0.02) / vol if vol > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {"name":name,"years":years,"cagr":cagr,"mdd":mdd,"calmar":calmar,
            "vol":vol,"sharpe":sharpe,"total":total}


def bench_equity(bench: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    """把基准 close 对齐到策略日期。"""
    b = bench.set_index("date")["close"]
    aligned = b.reindex(dates, method="ffill")
    return (aligned / aligned.iloc[0])


def main():
    print("[1/5] 加载基本面面板...", flush=True)
    fund = load_fundamentals()
    print(f"  {len(fund):,} 行 × {fund['code'].nunique()} 只股（主板）")

    print("[2/5] 加载股价...", flush=True)
    prices = load_prices()
    print(f"  {len(prices):,} 行 × {prices['code'].nunique()} 只股")

    print(f"[3/5] 回测 HOLD_STEP={HOLD_STEP} TOP_K={TOP_K}...", flush=True)
    log = backtest(prices, fund)
    if len(log) == 0:
        print("  空结果"); return
    print(f"  {len(log)} 期")

    # 策略净值曲线 — 用 next_date 作为 equity_net 的时间戳（正确的锚点）
    log = log.sort_values("date").reset_index(drop=True)
    log["equity_gross"] = (1 + log["period_ret"].clip(-0.99, None)).cumprod()
    log["equity_net"]   = (1 + log["period_ret_net"].clip(-0.99, None)).cumprod()
    log.to_csv(os.path.join(OUT_DIR, "layer1_periods.csv"),
               index=False, encoding="utf-8-sig")

    # 指标
    print("\n[4/5] 基准对齐与指标...", flush=True)
    hs300 = load_benchmark(HS300_CSV, pd.Timestamp(START))
    etf   = load_benchmark(ETF_CSV,   pd.Timestamp(START))

    dates = pd.DatetimeIndex(log["next_date"])
    strat_gross = pd.Series(log["equity_gross"].values, index=dates)
    strat_net   = pd.Series(log["equity_net"].values, index=dates)
    hs300_eq    = bench_equity(hs300, dates)
    etf_eq      = bench_equity(etf.dropna(), dates.intersection(pd.DatetimeIndex(etf["date"])))

    # 公共起点
    common_start = max(strat_net.index[0], hs300_eq.index[0], etf_eq.index[0])
    strat_net    = strat_net.loc[common_start:]
    strat_net    = strat_net / strat_net.iloc[0]
    hs300_eq     = hs300_eq.loc[common_start:] / hs300_eq.loc[common_start]
    etf_eq       = etf_eq.loc[common_start:] / etf_eq.loc[common_start]
    strat_gross  = strat_gross.loc[common_start:] / strat_gross.loc[common_start]

    print("\n[5/5] 汇总")
    print("="*80)
    rows_m = [
        metrics(strat_gross, "Layer1 毛 (无成本)"),
        metrics(strat_net,   "Layer1 净 (56bp 往返)"),
        metrics(hs300_eq,    "沪深 300"),
        metrics(etf_eq,      "512890 红利低波"),
    ]
    print(f"\n  {'标的':<24s} {'年数':>5s} {'CAGR':>8s} {'MDD':>8s} "
          f"{'Calmar':>7s} {'Vol':>7s} {'Sharpe':>7s} {'Total':>9s}")
    print(f"  {'-'*78}")
    for m in rows_m:
        print(f"  {m['name']:<24s} {m['years']:>4.1f}y {m['cagr']:>+8.2%} "
              f"{m['mdd']:>+8.2%} {m['calmar']:>7.2f} {m['vol']:>6.1%} "
              f"{m['sharpe']:>7.2f} {m['total']:>+9.2%}")

    # 红线检查
    net_m = rows_m[1]; etf_m = rows_m[3]
    print(f"\n  ── 红线判断 ──")
    print(f"  Layer1 净 Sharpe: {net_m['sharpe']:.2f}  ({'过线' if net_m['sharpe']>=0.4 else '未过线'}, 门槛 0.4)")
    print(f"  Layer1 净 CAGR vs 512890: {net_m['cagr']:+.2%} vs {etf_m['cagr']:+.2%}  "
          f"({'跑赢' if net_m['cagr']>etf_m['cagr'] else '跑输'})")

    # 每期诊断
    print(f"\n  平均换手: {log['turnover'].mean()*100:.0f}%   平均持仓: {log['n_holdings'].mean():.0f} 只")
    print(f"  年化成本: {log['cost'].mean() * (252/HOLD_STEP) * 100:.2f}%")

    # 按年分解
    log["year"] = log["date"].dt.year
    print(f"\n  年度净收益:")
    for y, g in log.groupby("year"):
        r = np.clip(g["period_ret_net"].values, -0.99, None)
        ann = (np.exp(np.log1p(r).sum()) ** (252/HOLD_STEP/len(g)) - 1) if len(g)>0 else np.nan
        ytd = np.exp(np.log1p(r).sum()) - 1
        print(f"    {int(y)}  期数 {len(g):>2d}   累计 {ytd:>+7.2%}   年化 {ann:>+7.2%}")


if __name__ == "__main__":
    main()
