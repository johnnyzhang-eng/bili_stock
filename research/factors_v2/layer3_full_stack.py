"""
3 层复合策略回测（基本面 + 雪球反向情绪 + 低波防御）
======================================================
Layer 1: ROE>=10, np_yoy>=0, rev_yoy>=-5, 毛利率>=15, 主板非ST
Layer 2: -factor_z (反向雪球共识，基于 rebalancing_history count 模式)
Layer 3: -vol60 (低波偏好)

复合分: 0.4 * z(fund_score) + 0.3 * z(-sent) + 0.3 * z(-vol60)
Top K 等权，20 交易日调仓，56bp 往返成本。

严格 point-in-time：
  - 基本面按 announce_date <= T
  - 情绪按 factor 的 date <= T (有 14 天 lag)
  - 低波按 T 之前 60 日收益波动
"""

import glob
import os
import sqlite3
import sys
import warnings

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT       = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path: sys.path.insert(0, ROOT)

from research.factors.factor_rebalance_momentum import build_rebalance_momentum_factor

PANEL      = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR  = os.path.join(ROOT, "data", "stock_data")
HS300_CSV  = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
ETF_CSV    = os.path.join(ROOT, "data", "market_cache", "etf_512890.csv")
CUBES_DB   = os.path.join(ROOT, "data", "cubes.db")
OUT_DIR    = os.path.join(ROOT, "research", "factors_v2", "output")

START      = "2016-01-01"
HOLD_STEP  = 20
TOP_K      = 20             # 3层收紧到 20 只（从基本面 300 → 情绪 top 50% → 低波 Top 20）
BUY_BP     = 13
SELL_BP    = 43
MIN_AMOUNT = 200e6
MIN_ROE    = 10.0
MIN_NP_YOY = 0.0
MIN_REV    = -5.0
MIN_GROSS  = 15.0
W_FUND     = 0.40
W_SENT     = 0.30
W_VOL      = 0.30


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
        df = df[df["date"] >= pd.Timestamp(START) - pd.Timedelta(days=120)]
        if len(df) < 40: continue
        df["code"] = code
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_sentiment() -> pd.DataFrame:
    """雪球 cubes factor_z: (date, stock_symbol (SHxxxxxx/SZxxxxxx), factor_z)"""
    con = sqlite3.connect(CUBES_DB)
    rb = pd.read_sql(
        "SELECT cube_symbol, stock_symbol, target_weight, prev_weight_adjusted, created_at "
        "FROM rebalancing_history WHERE status='success'", con)
    con.close()
    # 只保留 A 股 SHxxxxxx / SZxxxxxx
    rb = rb[rb["stock_symbol"].astype(str).str.match(r"^S[HZ]\d{6}$", na=False)].copy()
    if len(rb) == 0:
        print("  警告: 无 A 股雪球数据"); return pd.DataFrame()
    fac = build_rebalance_momentum_factor(
        rb, start_date=START, end_date="2026-04-30",
        lag_days=14, smoothing_days=3,
        factor_mode="rate", signal_mode="count")
    # factor_z 是当天横截面 z-score
    fac["code"] = fac["stock_symbol"].str[2:]
    return fac[["date","code","factor_z"]].dropna()


def load_benchmark(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date")[["date","close"]]


def get_fund_snapshot(fund: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    valid = fund[fund["announce_date"] <= as_of]
    if len(valid) == 0: return pd.DataFrame()
    latest = valid.groupby("code").tail(1)
    cutoff = as_of - pd.Timedelta(days=270)
    return latest[latest["announce_date"] >= cutoff]


def zscore(s: pd.Series) -> pd.Series:
    std = s.std()
    if std == 0 or np.isnan(std): return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def pick_topk(snap: pd.DataFrame, avg_amt: pd.Series, vol60: pd.Series,
              sent_z: pd.Series, k: int) -> list[str]:
    df = snap.copy()
    df = df[df["roe"] >= MIN_ROE]
    df = df[df["np_yoy"] >= MIN_NP_YOY]
    df = df[df["rev_yoy"] >= MIN_REV]
    df = df[df["gross_margin"] >= MIN_GROSS]
    df["amt"] = df["code"].map(avg_amt)
    df = df[df["amt"] >= MIN_AMOUNT]
    df["vol60"] = df["code"].map(vol60)
    df = df.dropna(subset=["vol60"])
    df["sent_z"] = df["code"].map(sent_z).fillna(0.0)   # 无覆盖 = 中性
    if len(df) < k: return df["code"].tolist()
    # 基本面分
    df["fund_raw"] = 0.7*df["roe"] + 0.3*df["np_yoy"]
    df["fund_z"]   = zscore(df["fund_raw"])
    df["vol_z"]    = zscore(df["vol60"])
    df["score"]    = W_FUND * df["fund_z"] - W_SENT * df["sent_z"] - W_VOL * df["vol_z"]
    return df.nlargest(k, "score")["code"].tolist()


def backtest(prices, fund, sent):
    prices = prices.sort_values(["code","date"])
    wide_close = prices.pivot(index="date", columns="code", values="close")
    wide_amt   = prices.pivot(index="date", columns="code", values="amount")
    # 60 日波动（对数收益）
    log_ret = np.log(wide_close / wide_close.shift(1))
    wide_vol = log_ret.rolling(60, min_periods=40).std()

    # 情绪 pivot: date × code -> factor_z
    wide_sent = sent.pivot_table(index="date", columns="code",
                                 values="factor_z", aggfunc="last") if len(sent) > 0 else pd.DataFrame()

    dates = wide_close.index
    dates = dates[dates >= pd.Timestamp(START)]
    rebal_dates = [dates[i] for i in range(0, len(dates), HOLD_STEP)]

    rows = []
    prev_hold = None
    for i, t in enumerate(rebal_dates):
        if i + 1 >= len(rebal_dates): break
        t_next = rebal_dates[i+1]
        avg_amt = wide_amt.loc[:t].tail(20).mean()
        vol60   = wide_vol.loc[t] if t in wide_vol.index else pd.Series(dtype=float)
        if len(wide_sent) > 0 and t in wide_sent.index:
            sent_row = wide_sent.loc[:t].ffill().iloc[-1]
        elif len(wide_sent) > 0:
            sent_row = wide_sent.loc[:t].ffill().iloc[-1] if len(wide_sent.loc[:t]) > 0 else pd.Series(dtype=float)
        else:
            sent_row = pd.Series(dtype=float)

        snap = get_fund_snapshot(fund, t)
        if len(snap) == 0: continue
        holdings = pick_topk(snap, avg_amt, vol60, sent_row, TOP_K)
        if len(holdings) < 5: continue

        p_t    = wide_close.loc[t,  holdings]
        p_next = wide_close.loc[t_next, holdings]
        ret = (p_next / p_t - 1).replace([np.inf,-np.inf], np.nan).dropna()
        if len(ret) == 0: continue
        period_ret = float(ret.mean())

        if prev_hold is None: turnover = 1.0
        else:
            new_in = set(holdings) - prev_hold
            turnover = len(new_in) / len(holdings)
        cost = turnover * (BUY_BP + SELL_BP) / 10000
        rows.append({
            "date": t, "next_date": t_next, "n_holdings": len(holdings),
            "period_ret": period_ret, "turnover": turnover, "cost": cost,
            "period_ret_net": period_ret - cost,
            "sent_cov": int(sum(c in sent_row.index and not pd.isna(sent_row.get(c)) for c in holdings)),
        })
        prev_hold = set(holdings)

    return pd.DataFrame(rows)


def metrics(eq, name, periods_per_year=252/HOLD_STEP):
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


def bench_equity(bench, dates):
    b = bench.set_index("date")["close"]
    return b.reindex(dates, method="ffill")


def main():
    print("[1/5] 基本面面板...", flush=True)
    fund = load_fundamentals()
    print(f"  {len(fund):,} 行 × {fund['code'].nunique()} 只股")

    print("[2/5] 股价...", flush=True)
    prices = load_prices()
    print(f"  {len(prices):,} 行 × {prices['code'].nunique()} 只股")

    print("[3/5] 雪球 cubes 情绪因子...", flush=True)
    sent = load_sentiment()
    if len(sent) > 0:
        print(f"  {len(sent):,} 行 × {sent['code'].nunique()} 只股 × {sent['date'].nunique()} 天")
    else:
        print("  无情绪数据，退化为 2 层")

    print(f"[4/5] 回测 HOLD={HOLD_STEP} K={TOP_K} 权重=({W_FUND},{W_SENT},{W_VOL})...", flush=True)
    log = backtest(prices, fund, sent)
    if len(log) == 0: print("空"); return
    print(f"  {len(log)} 期   平均情绪覆盖: {log['sent_cov'].mean():.1f}/{TOP_K}")

    log["equity_gross"] = (1 + log["period_ret"].clip(-0.99, None)).cumprod()
    log["equity_net"]   = (1 + log["period_ret_net"].clip(-0.99, None)).cumprod()
    log.to_csv(os.path.join(OUT_DIR, "layer3_periods.csv"),
               index=False, encoding="utf-8-sig")

    # 基准
    hs300 = load_benchmark(HS300_CSV)
    etf   = load_benchmark(ETF_CSV)
    dates = pd.DatetimeIndex(log["next_date"])
    strat_gross = pd.Series(log["equity_gross"].values, index=dates)
    strat_net   = pd.Series(log["equity_net"].values, index=dates)
    hs300_eq    = bench_equity(hs300, dates)
    etf_eq      = bench_equity(etf, dates)

    common = max(strat_net.index[0], hs300_eq.dropna().index[0], etf_eq.dropna().index[0])
    strat_net   = strat_net.loc[common:]; strat_net = strat_net / strat_net.iloc[0]
    strat_gross = strat_gross.loc[common:]; strat_gross = strat_gross / strat_gross.iloc[0]
    hs300_eq    = hs300_eq.loc[common:].dropna(); hs300_eq = hs300_eq / hs300_eq.iloc[0]
    etf_eq      = etf_eq.loc[common:].dropna(); etf_eq = etf_eq / etf_eq.iloc[0]

    # Layer 1 对比（如已有）
    l1_path = os.path.join(OUT_DIR, "layer1_periods.csv")
    l1_net = None
    if os.path.exists(l1_path):
        l1 = pd.read_csv(l1_path, encoding="utf-8-sig")
        l1["next_date"] = pd.to_datetime(l1["next_date"])
        l1_net = pd.Series(l1["equity_net"].values, index=pd.DatetimeIndex(l1["next_date"]))
        l1_net = l1_net.loc[common:]; l1_net = l1_net / l1_net.iloc[0]

    print("\n[5/5] 汇总")
    print("="*82)
    rows_m = [
        metrics(strat_gross, "Layer3 毛"),
        metrics(strat_net,   "Layer3 净 (56bp)"),
    ]
    if l1_net is not None:
        rows_m.append(metrics(l1_net, "Layer1 净（参考）"))
    rows_m += [
        metrics(hs300_eq, "沪深 300"),
        metrics(etf_eq,   "512890 红利低波"),
    ]
    print(f"\n  {'标的':<22s} {'年数':>5s} {'CAGR':>8s} {'MDD':>8s} "
          f"{'Calmar':>7s} {'Vol':>7s} {'Sharpe':>7s} {'Total':>9s}")
    print(f"  {'-'*76}")
    for m in rows_m:
        print(f"  {m['name']:<22s} {m['years']:>4.1f}y {m['cagr']:>+8.2%} "
              f"{m['mdd']:>+8.2%} {m['calmar']:>7.2f} {m['vol']:>6.1%} "
              f"{m['sharpe']:>7.2f} {m['total']:>+9.2%}")

    print(f"\n  平均换手: {log['turnover'].mean()*100:.0f}%   年化成本: {log['cost'].mean()*(252/HOLD_STEP)*100:.2f}%")

    log["year"] = log["date"].dt.year
    print(f"\n  年度净收益:")
    for y, g in log.groupby("year"):
        r = np.clip(g["period_ret_net"].values, -0.99, None)
        ytd = np.exp(np.log1p(r).sum()) - 1
        ann = (1+ytd)**(252/HOLD_STEP/len(g))-1 if len(g)>0 else np.nan
        print(f"    {int(y)}  期数 {len(g):>2d}   累计 {ytd:>+7.2%}   年化 {ann:>+7.2%}")


if __name__ == "__main__":
    main()
