"""
延长 low_vol 因子的 period log 到 2026 年 YTD。
与 run_low_vol_regime.py 保持一致：w=60, hs=12, enter=0.80, keep=0.70
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
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
HS300_CSV = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
PERIODS_CSV = os.path.join(ROOT, "research", "factors_v2", "output",
                           "low_vol_regime_periods.csv")

WINDOW    = 60
HOLD_STEP = 12
ENTER_Q   = 0.80
KEEP_Q    = 0.70
BDAYS     = 252


def load_prices(start: str) -> pd.DataFrame:
    """加载所有A股日线（close），长表格式。"""
    files = glob.glob(os.path.join(STOCK_DIR, "S[HZ]*.csv"))
    frames = []
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        # 主板过滤：排除 ETF / 创业板 / 科创板 / 北交所
        code = sym[2:]
        if sym.startswith("SH") and code[:3] in {"510","511","512","513","514",
                                                  "515","516","517","518","519","588","688","689"}: continue
        if sym.startswith("SH") and code[:2] == "56": continue
        if sym.startswith("SZ") and code[:3] in {"159","300","301","302"}: continue
        if code[:1] in {"8","4"}: continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig", usecols=["日期","收盘"])
        except Exception:
            continue
        df.columns = ["date","close"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna()
        df = df[df["date"] >= start]
        if len(df) < 30: continue
        df["stock_symbol"] = sym
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_regime() -> pd.DataFrame:
    """HS300 20日收益 -> regime (上涨>3%, 下跌<-3%, else 震荡)."""
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


def main():
    print("[1/4] 加载股价...", flush=True)
    prices = load_prices(start="2024-01-01")   # 保留60d+hold回溯缓冲
    prices = prices.sort_values(["stock_symbol","date"])
    print(f"  {len(prices):,} 行, {prices['stock_symbol'].nunique()} 只")

    print("[2/4] 计算60日波动率...", flush=True)
    prices["log_ret"] = prices.groupby("stock_symbol")["close"].transform(
        lambda s: np.log(s / s.shift(1)))
    prices["vol60"] = prices.groupby("stock_symbol")["log_ret"].transform(
        lambda s: s.rolling(WINDOW, min_periods=40).std())
    prices["factor_raw"] = -prices["vol60"]
    prices["hold_ret"] = prices.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-HOLD_STEP) / s - 1.0)

    print("[3/4] 合并regime...", flush=True)
    regime = load_regime()
    prices = prices.merge(regime, on="date", how="left")

    print("[4/4] 按12bday再平衡滚动...", flush=True)
    # 只保留2025-12-01后的数据
    start_ext = pd.Timestamp("2025-12-10")
    sub = prices[(prices["date"] >= start_ext) &
                 prices["factor_raw"].notna() &
                 prices["hold_ret"].notna()].copy()

    dates = sorted(sub["date"].unique())
    # 从最后一个已记录日之后开始
    existing = pd.read_csv(PERIODS_CSV, encoding="utf-8-sig")
    existing["date"] = pd.to_datetime(existing["date"])
    last_recorded = existing["date"].max()
    print(f"  已记录末日: {last_recorded.date()}")

    # 按12bday步长选日期
    rebal_dates = []
    i = 0
    for d in dates:
        if d <= last_recorded: continue
        if i % HOLD_STEP == 0:
            rebal_dates.append(d)
        i += 1
    print(f"  2026 YTD候选再平衡日: {len(rebal_dates)}")

    # Buffered rebalancing — 需要 prev_hold，用 last_recorded + 向前回溯一个周期恢复
    # 简化：不做buffer，直接用enter_q (保守估计会略偏低)
    rows = []
    prev_hold: set | None = None
    for d in rebal_dates:
        g = sub[sub["date"] == d].copy()
        if len(g) < 50: continue
        g["rank_pct"] = g["factor_raw"].rank(pct=True, method="first")

        entrants_all = g[g["rank_pct"] >= ENTER_Q]
        target_k = len(entrants_all)
        if target_k == 0: continue

        if prev_hold is not None:
            keep_set = set(g[(g["rank_pct"] >= KEEP_Q) &
                             g["stock_symbol"].isin(prev_hold)]["stock_symbol"])
        else:
            keep_set = set()

        entrants = entrants_all[~entrants_all["stock_symbol"].isin(keep_set)]
        entrants = entrants.sort_values("rank_pct", ascending=False)
        need = max(0, target_k - len(keep_set))
        new_set = set(entrants.head(need)["stock_symbol"])
        holdings = keep_set | new_set
        if not holdings: continue

        hold_df = g[g["stock_symbol"].isin(holdings)]
        period_ret = float(hold_df["hold_ret"].mean())
        regime_val = hold_df["regime"].mode().iloc[0] if not hold_df["regime"].mode().empty else "震荡"

        rows.append({
            "date": d.date(), "regime": regime_val,
            "period_ret": period_ret, "n_holdings": len(holdings),
            "year": d.year,
        })
        prev_hold = holdings

    if not rows:
        print("  [!] 没新期间")
        return

    new_df = pd.DataFrame(rows)
    print(f"\n  新增 {len(new_df)} 期:")
    print(new_df.to_string(index=False))

    # 合并写回
    combined = pd.concat([existing, new_df.assign(date=pd.to_datetime(new_df["date"]))],
                          ignore_index=True)
    combined = combined.drop_duplicates("date").sort_values("date")
    combined.to_csv(PERIODS_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  已更新 -> {PERIODS_CSV}")

    # ── 汇总：2026 YTD + 历史年度 ───────────────────────────────── #
    combined["date"] = pd.to_datetime(combined["date"])
    combined["year"] = combined["date"].dt.year
    periods_per_year = BDAYS / HOLD_STEP

    print(f"\n{'='*60}")
    print(f"低波因子年度表现（2015 - 2026 YTD）")
    print(f"{'='*60}")
    print(f"  {'年份':<6s} {'期数':>4s} {'平均':>7s} {'年化':>8s} {'累计':>8s}  主导态势")
    print(f"  {'-'*52}")
    for yr, g in combined.groupby("year"):
        r = np.clip(g["period_ret"].to_numpy(float), -0.99, None)
        mean_per = r.mean()
        cum_mult = float(np.exp(np.log1p(r).sum()))
        years_eq = len(r) / periods_per_year
        cagr = cum_mult ** (1/years_eq) - 1 if years_eq > 0 else np.nan
        cum  = cum_mult - 1
        dom  = g["regime"].mode().iloc[0] if not g["regime"].mode().empty else ""
        print(f"  {int(yr):<6d} {len(g):>4d} {mean_per:>+7.2%} {cagr:>+8.2%} {cum:>+8.2%}  {dom}")


if __name__ == "__main__":
    main()
