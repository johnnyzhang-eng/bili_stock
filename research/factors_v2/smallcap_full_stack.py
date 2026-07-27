"""
小盘 3 层策略 — 基本面+情绪反向+低波（新宇宙: 主板+创业板+科创板, 剔除大盘蓝筹）
==================================================================================
宇宙界定:
  - 包含: 60x 主板 + 00x 深主板 + 300x 创业板 + 688x 科创板
  - 剔除: 北交所, B股, ETF, 近20天成交额前 15% (大盘蓝筹, 512890/HS300 占领的地盘)
        以及 成交额 < 5000 万 (微盘, 无法交易)
因子权重:
  W_FUND=0.40, W_SENT=0.10, W_VOL=0.50 (从 Layer 3 sweep 出的最优)

基准: 沪深300, 创业板 ETF (159915), 中证1000 ETF (512100)
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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path: sys.path.insert(0, ROOT)

from research.factors.factor_rebalance_momentum import build_rebalance_momentum_factor

PANEL     = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
HS300_CSV = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
ETF_1000  = os.path.join(ROOT, "data", "market_cache", "etf_512100.csv")
ETF_GEM   = os.path.join(ROOT, "data", "market_cache", "etf_159915.csv")
ETF_DIV   = os.path.join(ROOT, "data", "market_cache", "etf_512890.csv")
CUBES_DB  = os.path.join(ROOT, "data", "cubes.db")
OUT_DIR   = os.path.join(ROOT, "research", "factors_v2", "output")

START     = "2017-01-01"   # 512100 从 2016-11 开始，留 2 个月给 vol60 暖启
HOLD_STEP = 20
TOP_K     = 20
BUY_BP, SELL_BP = 13, 43
MIN_AMT   = 50e6      # 5000 万下限
TOP_AMT_PCT = 0.85    # 成交额前 15% 剔除（大盘）
MIN_ROE   = 10.0
MIN_NP_YOY = 0.0
MIN_REV    = -5.0
MIN_GROSS  = 15.0
W_FUND, W_SENT, W_VOL = 0.4, 0.1, 0.5


def is_small_cap_code(code: str) -> bool:
    """接受范围: 60x 沪主板 + 00x/001/002/003 深主板 + 300x 创业板 + 688 科创板"""
    c = str(code).zfill(6)
    if c.startswith(("43","83","87","88","92","4","8","9")): return False        # 北交所
    if c.startswith(("159","510","511","512","513","514","515","516","517","518","519","520","588","18","200","201","900")): return False
    return c.startswith(("60","000","001","002","003","30","301","302","688"))


def load_fundamentals() -> pd.DataFrame:
    df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    df["report_date"]   = pd.to_datetime(df["report_date"])
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce")
    df["announce_date"] = df["announce_date"].fillna(df["report_date"] + pd.Timedelta(days=45))
    for c in ["roe","np_yoy","rev_yoy","gross_margin"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["code"].apply(is_small_cap_code)].copy()
    df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
    return df.sort_values(["code","announce_date"])


def load_prices() -> pd.DataFrame:
    files = glob.glob(os.path.join(STOCK_DIR, "S[HZ]*.csv"))
    frames = []
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        code = sym[2:]
        if not is_small_cap_code(code): continue
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
    con = sqlite3.connect(CUBES_DB)
    rb = pd.read_sql(
        "SELECT cube_symbol, stock_symbol, target_weight, prev_weight_adjusted, created_at "
        "FROM rebalancing_history WHERE status='success'", con)
    con.close()
    rb = rb[rb["stock_symbol"].astype(str).str.match(r"^S[HZ]\d{6}$", na=False)].copy()
    if len(rb) == 0: return pd.DataFrame()
    fac = build_rebalance_momentum_factor(
        rb, start_date=START, end_date="2026-04-30",
        lag_days=14, smoothing_days=3,
        factor_mode="rate", signal_mode="count")
    fac["code"] = fac["stock_symbol"].str[2:]
    return fac[["date","code","factor_z"]].dropna()


def load_benchmark(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date")[["date","close"]]


def get_fund_snapshot(fund, as_of):
    valid = fund[fund["announce_date"] <= as_of]
    if len(valid) == 0: return pd.DataFrame()
    latest = valid.groupby("code").tail(1)
    return latest[latest["announce_date"] >= as_of - pd.Timedelta(days=270)]


def zscore(s):
    std = s.std()
    if std == 0 or np.isnan(std): return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def pick_topk(snap, avg_amt, amt_thresh_high, vol60, sent_z, k):
    df = snap.copy()
    df = df[df["roe"] >= MIN_ROE]
    df = df[df["np_yoy"] >= MIN_NP_YOY]
    df = df[df["rev_yoy"] >= MIN_REV]
    df = df[df["gross_margin"] >= MIN_GROSS]
    df["amt"] = df["code"].map(avg_amt)
    df = df[(df["amt"] >= MIN_AMT) & (df["amt"] <= amt_thresh_high)]
    df["vol60"] = df["code"].map(vol60)
    df = df.dropna(subset=["vol60"])
    df["sent_z"] = df["code"].map(sent_z).fillna(0.0)
    if len(df) < k: return df["code"].tolist()
    df["fund_raw"] = 0.7*df["roe"] + 0.3*df["np_yoy"]
    df["fund_z"]   = zscore(df["fund_raw"])
    df["vol_z"]    = zscore(df["vol60"])
    df["score"] = W_FUND*df["fund_z"] - W_SENT*df["sent_z"] - W_VOL*df["vol_z"]
    return df.nlargest(k, "score")["code"].tolist()


def backtest(prices, fund, sent):
    prices = prices.sort_values(["code","date"])
    wide_close = prices.pivot(index="date", columns="code", values="close")
    wide_amt   = prices.pivot(index="date", columns="code", values="amount")
    log_ret = np.log(wide_close / wide_close.shift(1))
    wide_vol = log_ret.rolling(60, min_periods=40).std()
    wide_sent = sent.pivot_table(index="date", columns="code",
                                 values="factor_z", aggfunc="last") if len(sent)>0 else pd.DataFrame()

    dates = wide_close.index[wide_close.index >= pd.Timestamp(START)]
    rebal_dates = [dates[i] for i in range(0, len(dates), HOLD_STEP)]

    rows = []
    prev = None
    for i, t in enumerate(rebal_dates):
        if i+1 >= len(rebal_dates): break
        t_next = rebal_dates[i+1]
        recent_amt = wide_amt.loc[:t].tail(20).mean()
        # 每日动态上限: 该再平衡日截面的 85 分位
        amt_high = recent_amt.quantile(TOP_AMT_PCT) if len(recent_amt.dropna()) > 0 else np.inf
        vol60 = wide_vol.loc[t] if t in wide_vol.index else pd.Series(dtype=float)
        sent_row = wide_sent.loc[:t].ffill().iloc[-1] if len(wide_sent.loc[:t])>0 else pd.Series(dtype=float)
        snap = get_fund_snapshot(fund, t)
        if len(snap) == 0: continue
        hold = pick_topk(snap, recent_amt, amt_high, vol60, sent_row, TOP_K)
        if len(hold) < 5: continue
        p_t, p_next = wide_close.loc[t, hold], wide_close.loc[t_next, hold]
        r = (p_next/p_t - 1).replace([np.inf,-np.inf], np.nan).dropna()
        if len(r) == 0: continue
        pr = float(r.mean())
        turn = 1.0 if prev is None else len(set(hold)-prev)/len(hold)
        cost = turn*(BUY_BP+SELL_BP)/10000
        rows.append({
            "date":t,"next_date":t_next,"n_holdings":len(hold),
            "period_ret":pr,"turnover":turn,"cost":cost,
            "period_ret_net":pr-cost,
            "amt_high_thresh": float(amt_high),
        })
        prev = set(hold)

    return pd.DataFrame(rows)


def metrics(eq, name, periods_per_year=252/HOLD_STEP):
    ret = eq.pct_change().dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (1+total)**(1/years) - 1 if years > 0 else np.nan
    dd = eq / eq.cummax() - 1
    mdd = dd.min()
    vol = ret.std() * np.sqrt(periods_per_year)
    sharpe = (cagr - 0.02) / vol if vol > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {"name":name,"years":years,"cagr":cagr,"mdd":mdd,"calmar":calmar,
            "vol":vol,"sharpe":sharpe,"total":total}


def bench_equity(bench, dates):
    b = bench.set_index("date")["close"]
    return b.reindex(dates, method="ffill")


def main():
    print("[1/5] 基本面（小盘宇宙）...", flush=True)
    fund = load_fundamentals()
    print(f"  {len(fund):,} 行 × {fund['code'].nunique()} 只股")

    print("[2/5] 股价...", flush=True)
    prices = load_prices()
    print(f"  {len(prices):,} 行 × {prices['code'].nunique()} 只股")

    print("[3/5] 雪球情绪...", flush=True)
    sent = load_sentiment()
    if len(sent) > 0:
        print(f"  {len(sent):,} 行 × {sent['code'].nunique()} 只股")

    print(f"[4/5] 小盘 3 层回测 HOLD={HOLD_STEP} K={TOP_K} W=({W_FUND},{W_SENT},{W_VOL})...", flush=True)
    log = backtest(prices, fund, sent)
    if len(log) == 0: print("空"); return
    print(f"  {len(log)} 期   平均持仓: {log['n_holdings'].mean():.1f}   "
          f"平均成交额上限: {log['amt_high_thresh'].mean()/1e8:.1f}亿")

    log["equity_gross"] = (1 + log["period_ret"].clip(-0.99, None)).cumprod()
    log["equity_net"]   = (1 + log["period_ret_net"].clip(-0.99, None)).cumprod()
    log.to_csv(os.path.join(OUT_DIR, "smallcap_periods.csv"),
               index=False, encoding="utf-8-sig")

    # 基准
    hs300 = load_benchmark(HS300_CSV)
    etf1000 = load_benchmark(ETF_1000)
    gem   = load_benchmark(ETF_GEM)
    div   = load_benchmark(ETF_DIV)

    dates = pd.DatetimeIndex(log["next_date"])
    strat_net = pd.Series(log["equity_net"].values, index=dates)
    strat_gross = pd.Series(log["equity_gross"].values, index=dates)
    hs300_eq = bench_equity(hs300, dates)
    e1000_eq = bench_equity(etf1000, dates)
    gem_eq   = bench_equity(gem, dates)
    div_eq   = bench_equity(div, dates)

    common = max(strat_net.index[0], e1000_eq.dropna().index[0], gem_eq.dropna().index[0])
    def norm(s): s = s.loc[common:].dropna(); return s / s.iloc[0]
    strat_net   = norm(strat_net)
    strat_gross = norm(strat_gross)
    hs300_eq    = norm(hs300_eq)
    e1000_eq    = norm(e1000_eq)
    gem_eq      = norm(gem_eq)
    div_eq      = norm(div_eq)

    print("\n[5/5] 汇总")
    print("="*86)
    rows_m = [
        metrics(strat_gross, "小盘 3 层 毛"),
        metrics(strat_net,   "小盘 3 层 净"),
        metrics(hs300_eq,    "沪深 300"),
        metrics(e1000_eq,    "中证 1000 ETF"),
        metrics(gem_eq,      "创业板 ETF"),
        metrics(div_eq,      "红利低波 ETF"),
    ]
    print(f"\n  {'标的':<20s} {'年数':>5s} {'CAGR':>8s} {'MDD':>8s} "
          f"{'Calmar':>7s} {'Vol':>7s} {'Sharpe':>7s} {'Total':>9s}")
    print(f"  {'-'*76}")
    for m in rows_m:
        print(f"  {m['name']:<20s} {m['years']:>4.1f}y {m['cagr']:>+8.2%} "
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
