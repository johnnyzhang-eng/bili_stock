"""
低波因子小资金版 — 只选Top 15，2015-2026 YTD完整回测 + 当前选股
==================================================================
和 run_low_vol_regime.py 的区别：
  - 固定 K=15（而不是 bottom 20% ≈ 67只）
  - 等权持有，每12交易日调仓
  - 换手率按实际计算（不再假设35%）
  - 含真实交易费（13bp买 + 43bp卖）
"""

import glob
import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
HS300_CSV = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
OUT_DIR   = os.path.join(ROOT, "research", "factors_v2", "output")

K          = 15
WINDOW     = 60
HOLD_STEP  = 12
BDAYS      = 252
BUY_BP     = 13
SELL_BP    = 43
MIN_AMOUNT = 200e6   # 日成交 > 2亿
START      = "2015-01-01"


def load_prices() -> pd.DataFrame:
    """加载所有主板股票，长表(date, sym, close, amount, log_ret, vol60)."""
    files = glob.glob(os.path.join(STOCK_DIR, "S[HZ]*.csv"))
    frames = []
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        code = sym[2:]
        if sym.startswith("SH") and code[:3] in {"510","511","512","513","514",
                                                  "515","516","517","518","519","588","688","689"}: continue
        if sym.startswith("SH") and code[:2] == "56": continue
        if sym.startswith("SZ") and code[:3] in {"159","300","301","302"}: continue
        if code[:1] in {"8","4"}: continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig", usecols=["日期","收盘","成交额"])
        except Exception:
            continue
        df.columns = ["date","close","amount"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        df = df.dropna(subset=["date","close"]).sort_values("date")
        df = df[df["date"] >= pd.Timestamp(START)]
        if len(df) < 100: continue
        df["stock_symbol"] = sym
        frames.append(df)
    p = pd.concat(frames, ignore_index=True)
    p["log_ret"] = p.groupby("stock_symbol")["close"].transform(
        lambda s: np.log(s / s.shift(1)))
    p["vol60"] = p.groupby("stock_symbol")["log_ret"].transform(
        lambda s: s.rolling(WINDOW, min_periods=40).std())
    p["hold_ret"] = p.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-HOLD_STEP) / s - 1.0)
    return p


def load_regime() -> pd.DataFrame:
    df = pd.read_csv(HS300_CSV, encoding="utf-8-sig")
    date_col = next((c for c in df.columns if "日期" in c or "date" in c.lower()), df.columns[0])
    close_col = next((c for c in df.columns if "收盘" in c or "close" in c.lower()), df.columns[-1])
    df = df.rename(columns={date_col: "date", close_col: "close"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna().sort_values("date")
    df["ret20"] = df["close"].pct_change(20)
    df["regime"] = np.where(df["ret20"] > 0.03, "上涨",
                    np.where(df["ret20"] < -0.03, "下跌", "震荡"))
    return df[["date","regime"]]


def backtest(prices: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """对所有再平衡日做等权Top-K回测，返回 per-period log。"""
    prices = prices.merge(regime, on="date", how="left")
    # 流动性过滤：日成交额 >= 2亿
    prices = prices[prices["amount"] >= MIN_AMOUNT]
    sub = prices.dropna(subset=["vol60","hold_ret"]).copy()
    dates = sorted(sub["date"].unique())

    rows = []
    prev_hold: set | None = None
    for i, d in enumerate(dates):
        if i % HOLD_STEP != 0:
            continue
        g = sub[sub["date"] == d]
        if len(g) < 50: continue

        # Top K 低波
        holdings = set(g.nsmallest(K, "vol60")["stock_symbol"].tolist())
        hold_df = g[g["stock_symbol"].isin(holdings)]
        period_ret = float(hold_df["hold_ret"].mean())

        # 换手率
        if prev_hold is not None:
            new_in  = holdings - prev_hold
            turnover = len(new_in) / K
        else:
            turnover = 1.0

        cost = turnover * (BUY_BP + SELL_BP) / 10000
        period_ret_net = period_ret - cost

        regime_val = hold_df["regime"].mode().iloc[0] if not hold_df["regime"].mode().empty else "震荡"

        rows.append({
            "date": d, "regime": regime_val,
            "period_ret": period_ret,
            "turnover": turnover,
            "cost": cost,
            "period_ret_net": period_ret_net,
        })
        prev_hold = holdings

    return pd.DataFrame(rows)


def summarize(log: pd.DataFrame):
    log = log.copy()
    log["year"] = log["date"].dt.year
    periods_per_year = BDAYS / HOLD_STEP

    print(f"\n{'='*65}")
    print(f"  小资金版（K=15，主板+流动性>2亿，实际换手率）")
    print(f"{'='*65}")

    print(f"\n  {'年份':<6s} {'期数':>4s} {'换手':>6s} {'毛年化':>8s} {'净年化':>8s}  主导")
    print(f"  {'-'*52}")
    for yr, g in log.groupby("year"):
        r_g = np.clip(g["period_ret"].to_numpy(float), -0.99, None)
        r_n = np.clip(g["period_ret_net"].to_numpy(float), -0.99, None)
        yrs_eq = len(g) / periods_per_year
        cum_g = float(np.exp(np.log1p(r_g).sum()))
        cum_n = float(np.exp(np.log1p(r_n).sum()))
        cagr_g = cum_g ** (1/yrs_eq) - 1 if yrs_eq > 0 else np.nan
        cagr_n = cum_n ** (1/yrs_eq) - 1 if yrs_eq > 0 else np.nan
        avg_turn = g["turnover"].mean()
        dom = g["regime"].mode().iloc[0] if not g["regime"].mode().empty else ""
        print(f"  {int(yr):<6d} {len(g):>4d} {avg_turn*100:>5.0f}% "
              f"{cagr_g:>+8.2%} {cagr_n:>+8.2%}  {dom}")

    # 全周期
    r_all_g = np.clip(log["period_ret"].to_numpy(float), -0.99, None)
    r_all_n = np.clip(log["period_ret_net"].to_numpy(float), -0.99, None)
    yrs_total = len(log) / periods_per_year
    cum_g_all = float(np.exp(np.log1p(r_all_g).sum()))
    cum_n_all = float(np.exp(np.log1p(r_all_n).sum()))
    cagr_g_all = cum_g_all ** (1/yrs_total) - 1
    cagr_n_all = cum_n_all ** (1/yrs_total) - 1

    eq  = np.exp(np.log1p(r_all_n).cumsum())
    dd  = (eq / np.maximum.accumulate(eq)) - 1
    mdd = dd.min()
    calmar = cagr_n_all / abs(mdd) if mdd < 0 else np.nan
    win_period = (log["period_ret_net"] > 0).mean()

    print(f"  {'-'*52}")
    print(f"\n  全周期 ({yrs_total:.1f}年 / {len(log)}期):")
    print(f"    毛年化: {cagr_g_all:+.2%}   毛累计: {cum_g_all-1:+.2%}")
    print(f"    净年化: {cagr_n_all:+.2%}   净累计: {cum_n_all-1:+.2%}")
    print(f"    最大回撤(净): {mdd:.2%}   Calmar: {calmar:.2f}")
    print(f"    单期胜率: {win_period:.0%}   平均换手: {log['turnover'].mean()*100:.0f}%")
    print(f"    年化成本: {log['cost'].mean() * periods_per_year * 100:.2f}%")

    # 保存带净值曲线的日志
    log["equity_net"] = eq
    log.to_csv(os.path.join(OUT_DIR, "low_vol_k15_periods.csv"),
               index=False, encoding="utf-8-sig")


def current_picks(prices: pd.DataFrame):
    """最新日期的 Top 15 选股。"""
    from research.factors_v2.stock_names import get_name_map, is_st
    try: name_map = get_name_map()
    except Exception: name_map = {}

    # 流动性过滤（基于最近20天均值，更稳）
    latest_date = prices["date"].max()
    recent = prices[prices["date"] >= latest_date - pd.Timedelta(days=40)]
    avg_amt = recent.groupby("stock_symbol")["amount"].mean()
    liquid_syms = set(avg_amt[avg_amt >= MIN_AMOUNT].index)

    latest = prices[prices["date"] == latest_date].copy()
    latest = latest[latest["stock_symbol"].isin(liquid_syms)]
    latest = latest.dropna(subset=["vol60"])
    latest["name"] = latest["stock_symbol"].apply(lambda s: name_map.get(s[2:], s))
    latest = latest[~latest["name"].apply(is_st)]
    latest["vol_ann"] = latest["vol60"] * np.sqrt(252)
    latest = latest.sort_values("vol60").head(K)

    print(f"\n{'='*65}")
    print(f"  今天（{latest_date.date()}）小资金版 Top 15 选股")
    print(f"{'='*65}\n")
    print(f"  {'排名':<4s} {'代码':<10s} {'名称':<12s} {'现价':>7s} "
          f"{'年化波动':>8s} {'日成交(亿)':>10s}")
    print(f"  {'-'*60}")
    for i, (_, r) in enumerate(latest.iterrows(), 1):
        print(f"  {i:<4d} {r['stock_symbol']:<10s} {r['name']:<12s} "
              f"{r['close']:>7.2f} {r['vol_ann']*100:>7.1f}% "
              f"{r['amount']/1e8:>9.1f}亿")

    out = os.path.join(OUT_DIR, "live", f"low_vol_k15_picks_{latest_date.date()}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    latest[["stock_symbol","name","close","vol_ann","amount"]].to_csv(
        out, index=False, encoding="utf-8-sig")
    print(f"\n  清单 -> {out}")

    # 预估资金门槛：按最高单价估算一手需要多少钱
    max_price = latest["close"].max()
    total_one_hand = latest["close"].sum() * 100
    print(f"\n  资金门槛估算（每只1手/100股）: {total_one_hand:,.0f} 元")
    print(f"  按5万本金可覆盖约: {int(50000 / (total_one_hand/K))} 只（需拆单或减持）")


def main():
    print("[1/3] 加载主板股价 + 计算 vol60 + hold_ret...", flush=True)
    prices = load_prices()
    print(f"  {len(prices):,} 行, {prices['stock_symbol'].nunique()} 只股")

    print("[2/3] 加载HS300 regime...", flush=True)
    regime = load_regime()

    print("[3/3] 回测（每12bday调仓，K=15）...", flush=True)
    log = backtest(prices, regime)
    print(f"  共 {len(log)} 期")

    summarize(log)
    current_picks(prices)


if __name__ == "__main__":
    main()
