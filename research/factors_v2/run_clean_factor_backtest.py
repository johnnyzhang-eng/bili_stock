"""
Clean Factor Backtest — GOOD28 + MAX56_OK "无出货"因子
========================================================
IC研究结论：
  - GOOD28  (10日IC=+0.015, ICIR=0.218): 近28日高位无放量阴线
  - MAX56_OK(10日IC=+0.019, ICIR=0.423): 近56日最大量能不是阴线

本文件把两个条件升级为连续因子并回测：

  Factor A — clean_dist:  -cnt28（分配日计数取负，越少越好）
  Factor B — clean_hvbal: 56日高量阳线数 - 高量阴线数（净积累力度）
  Factor C — clean_combo: zscore(A) + zscore(B)  ← 主测因子

对比：
  · low_vol baseline (已知CAGR~13%)
  · clean_combo standalone
  · low_vol × clean_combo 交叉筛选

回测参数与low_vol一致：
  enter_q=0.80, keep_q=0.70, hold_step=12, 56bp round-trip
  overlay: HS300 20d < -7% → 空仓

Run:
    python research/factors_v2/run_clean_factor_backtest.py
"""

import glob
import os
import sys
import random

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
HS300_CACHE    = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
OUT_DIR        = os.path.join(ROOT, "research", "factors_v2", "output")

START_DATE     = "2015-01-01"
END_DATE       = "2026-04-18"
ROUND_TRIP_BP  = 56
BDAYS_PER_YEAR = 252
ENTER_Q        = 0.80
KEEP_Q         = 0.70
HOLD_STEP      = 12
OVERLAY_THR    = -0.07


# ─── 指标计算 ─────────────────────────────────────────────────────────── #

def _zscore_cross(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _compute_clean_factors(df: pd.DataFrame) -> pd.DataFrame:
    c   = df["close"]
    o   = df["open"]
    h   = df["high"]
    l   = df["low"]
    v   = df["vol"]
    pc  = df["pct_chg"]

    prev_c = c.shift(1)
    real_yang = ((c > o) & ~(c < prev_c)).astype(float)
    real_yin  = ((c < o) & ~(c > prev_c)).astype(float)

    # ── Factor A: clean_dist（-cnt28 分配日计数）──────────────────────────
    lo28 = v.rolling(28, min_periods=1).min()   # not used directly
    hi28_o = o.rolling(28, min_periods=1).max()
    lo28_o = o.rolling(28, min_periods=1).min()
    o85    = lo28_o + 0.95 * (hi28_o - lo28_o)
    top15o = (o >= o85).astype(float)
    fd15   = ((c < prev_c) & (c <= o) & (v >= 1.15 * v.shift(1))).astype(float)
    cnt28  = (top15o * fd15).rolling(28, min_periods=1).sum()
    # 连续因子：0 最好（无分配日），取负
    factor_a = -cnt28

    # ── Factor B: clean_hvbal（净高量积累力度）────────────────────────────
    avg_vol20  = v.rolling(20, min_periods=5).mean()
    high_vol   = (v > 1.5 * avg_vol20).astype(float)
    hv_bull    = (high_vol * real_yang).rolling(56, min_periods=10).sum()
    hv_bear    = (high_vol * real_yin ).rolling(56, min_periods=10).sum()
    factor_b   = hv_bull - hv_bear   # 正 = 积累, 负 = 出货

    out = pd.DataFrame({
        "factor_a": factor_a,
        "factor_b": factor_b,
        "good28_cnt": -factor_a,   # raw count for reference
    }, index=df.index)
    return out


# ─── 面板构建 ─────────────────────────────────────────────────────────── #

def build_panel() -> pd.DataFrame:
    files = glob.glob(os.path.join(STOCK_DATA_DIR, "S[HZ]*.csv"))

    # 窗口前推留够计算空间
    start_dt = pd.Timestamp(START_DATE) - pd.Timedelta(days=120)
    end_dt   = pd.Timestamp(END_DATE)

    rows = []
    skipped = 0
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        if sym.endswith(".HK"):
            continue
        code = sym[2:]
        if (sym.startswith("SH") and (
                code[:3] in {"510","511","512","513","514","515","516","517","518","519","588"}
                or code[:2] == "56")):
            continue
        if sym.startswith("SZ") and code[:3] == "159":
            continue

        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        except Exception:
            skipped += 1
            continue

        col_map = {}
        for col in df.columns:
            lc = col.strip()
            if lc == "日期":      col_map[col] = "date"
            elif lc == "开盘":    col_map[col] = "open"
            elif lc == "收盘":    col_map[col] = "close"
            elif lc == "最高":    col_map[col] = "high"
            elif lc == "最低":    col_map[col] = "low"
            elif lc == "成交量":  col_map[col] = "vol"
            elif lc == "涨跌幅":  col_map[col] = "pct_chg"
        df = df.rename(columns=col_map)

        needed = ["date", "open", "close", "high", "low", "vol"]
        if not all(c in df.columns for c in needed):
            skipped += 1
            continue

        df["date"]  = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for c in needed[1:]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=needed).query("close > 0").sort_values("date")
        if "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
        else:
            df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
            mask = df["pct_chg"].isna()
            df.loc[mask, "pct_chg"] = df["close"].pct_change()[mask] * 100

        df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        if len(df) < 80:
            continue

        df = df.set_index("date")
        factors = _compute_clean_factors(df)
        factors["close"]        = df["close"].values
        factors["pct_chg"]      = df["pct_chg"].values
        factors["stock_symbol"] = sym
        factors["date"]         = df.index
        rows.append(factors.reset_index(drop=True))

    print(f"  Loaded {len(rows)} stocks, skipped {skipped}", flush=True)
    panel = pd.concat(rows, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])

    # 前向收益
    panel = panel.sort_values(["stock_symbol", "date"])
    panel["fwd_ret"] = (
        panel.groupby("stock_symbol")["close"]
        .transform(lambda s: s.shift(-HOLD_STEP) / s - 1.0)
    )

    # 裁剪到研究区间
    panel = panel[panel["date"] >= pd.Timestamp(START_DATE)].copy()

    # 截面z-score
    panel["z_a"] = panel.groupby("date")["factor_a"].transform(_zscore_cross)
    panel["z_b"] = panel.groupby("date")["factor_b"].transform(_zscore_cross)
    panel["clean_combo"] = panel["z_a"] + panel["z_b"]
    panel["clean_combo"] = panel.groupby("date")["clean_combo"].transform(_zscore_cross)

    return panel


# ─── 加载HS300 regime ────────────────────────────────────────────────── #

def load_hs300_regime() -> pd.DataFrame:
    hs = pd.read_csv(HS300_CACHE)
    hs["date"] = pd.to_datetime(hs["date"])
    if "ret20" not in hs.columns:
        hs = hs.sort_values("date")
        hs["ret20"] = hs["close"].pct_change(20)
    return hs[["date", "ret20"]].dropna().set_index("date")


# ─── 回测引擎 ─────────────────────────────────────────────────────────── #

def _cagr(rets, ppy):
    r = np.clip(np.asarray(rets, dtype=float), -0.99, None)
    if len(r) == 0:
        return np.nan
    cum = float(np.prod(1.0 + r))
    return cum ** (ppy / len(r)) - 1.0 if cum > 0 else -1.0


def _mdd(eq: pd.Series) -> float:
    peak = eq.cummax()
    return float(((eq - peak) / peak).min())


def buffered_backtest(panel: pd.DataFrame,
                      factor_col: str,
                      hs300: pd.DataFrame,
                      start_offset: int = 0) -> dict:
    sub = panel.dropna(subset=[factor_col, "fwd_ret"]).copy()
    sub["rank_pct"] = sub.groupby("date")[factor_col].rank(pct=True, method="first")

    dates      = sorted(sub["date"].unique())
    rebal_dates = dates[start_offset::HOLD_STEP]

    records  = []
    prev_hold = None
    ppy       = BDAYS_PER_YEAR / HOLD_STEP

    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:
            continue

        # overlay
        hs_rows = hs300[hs300.index <= d]
        ret20   = float(hs_rows["ret20"].iloc[-1]) if not hs_rows.empty else 0.0
        if ret20 < OVERLAY_THR:
            records.append({"date": d, "year": d.year,
                            "gross_ret": 0.0, "net_ret": 0.0,
                            "churn": 0.0, "overlay": True})
            prev_hold = set()
            continue

        entrants_all = g[g["rank_pct"] >= ENTER_Q]
        target_k     = len(entrants_all)
        if target_k == 0:
            continue

        keep_set = (
            set(g[(g["rank_pct"] >= KEEP_Q) & g["stock_symbol"].isin(prev_hold)]["stock_symbol"])
            if prev_hold else set()
        )
        new_entrants = (entrants_all[~entrants_all["stock_symbol"].isin(keep_set)]
                        .sort_values("rank_pct", ascending=False))
        new_set  = set(new_entrants.head(max(0, target_k - len(keep_set)))["stock_symbol"])
        holdings = keep_set | new_set
        if not holdings:
            continue

        period_ret = float(g[g["stock_symbol"].isin(holdings)]["fwd_ret"].mean())
        churn      = len(holdings - prev_hold) / max(len(holdings), 1) if prev_hold else 0.0
        net_ret    = period_ret - churn * (ROUND_TRIP_BP / 1e4)

        records.append({"date": d, "year": d.year,
                        "gross_ret": period_ret, "net_ret": net_ret,
                        "churn": churn, "overlay": False})
        prev_hold = holdings

    if not records:
        return {}

    df       = pd.DataFrame(records)
    eq       = (1 + df["net_ret"]).cumprod()
    by_year  = df.groupby("year")["gross_ret"].apply(lambda r: _cagr(r.tolist(), ppy))
    ann_net  = _cagr(df["net_ret"].tolist(), ppy)
    mdd_net  = _mdd(eq)
    turnover = float(df["churn"].mean())
    return {
        "ann_net":  ann_net,
        "mdd_net":  mdd_net,
        "calmar":   ann_net / abs(mdd_net) if mdd_net < 0 else np.nan,
        "turnover": turnover,
        "ann_cost": turnover * ppy * ROUND_TRIP_BP / 1e4,
        "by_year":  by_year,
        "n_periods": len(df),
    }


def randomized_start_test(panel, factor_col, hs300, label, n_offsets=12):
    """Pass if CAGR_net > 0 in >= 80% of start offsets."""
    results = []
    for off in range(n_offsets):
        r = buffered_backtest(panel, factor_col, hs300, start_offset=off)
        if r:
            results.append(r["ann_net"])
    if not results:
        return False, 0.0
    pass_rate = sum(1 for x in results if x > 0) / len(results)
    avg_net   = float(np.mean(results))
    print(f"  [{label}] 随机起点测试: {pass_rate:.0%} 正收益 ({sum(1 for x in results if x > 0)}/{len(results)}), "
          f"均值CAGR_net={avg_net:+.2%}", flush=True)
    return pass_rate >= 0.80, pass_rate


# ─── 主程序 ──────────────────────────────────────────────────────────── #

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Building panel …", flush=True)
    panel = build_panel()
    print(f"Panel: {panel['stock_symbol'].nunique()} stocks, "
          f"{panel['date'].nunique()} dates, {len(panel):,} rows", flush=True)

    print("Loading HS300 regime …", flush=True)
    hs300 = load_hs300_regime()

    # ── IC 快速确认 ──────────────────────────────────────────────────── #
    print("\n── IC确认 ──────────────────────────────────────────────────────")
    sub = panel.dropna(subset=["clean_combo", "fwd_ret"])
    ics = sub.groupby("date").apply(
        lambda g: g["clean_combo"].corr(g["fwd_ret"], method="spearman")
        if len(g) >= 30 else np.nan
    ).dropna()
    print(f"  clean_combo IC (fwd_{HOLD_STEP}d): {ics.mean():+.4f}  "
          f"ICIR={ics.mean()/ics.std():.3f}  hit={( ics>0).mean():.1%}  n={len(ics)}")

    # ── 主回测 ──────────────────────────────────────────────────────── #
    configs = [
        ("clean_combo",  "clean_combo (standalone)"),
        ("z_a",          "clean_dist A（-cnt28）"),
        ("z_b",          "clean_hvbal B（净高量积累）"),
    ]

    print("\n── 回测结果 ─────────────────────────────────────────────────────")
    print(f"{'策略':<32s} {'CAGR_net':>9s} {'MDD':>9s} {'Calmar':>7s} "
          f"{'turn/p':>7s} {'ann_cost':>9s}")
    print("-" * 80)

    all_results = {}
    for col, label in configs:
        r = buffered_backtest(panel, col, hs300, start_offset=0)
        all_results[label] = r
        if r:
            print(f"{label:<32s} {r['ann_net']:>+8.2%} {r['mdd_net']:>8.2%} "
                  f"{r['calmar']:>6.3f} {r['turnover']:>6.1%} {r['ann_cost']:>8.2%}")
        else:
            print(f"{label:<32s}  (no result)")

    # ── 逐年 gross ─────────────────────────────────────────────────── #
    best_label = "clean_combo (standalone)"
    if all_results.get(best_label):
        r = all_results[best_label]
        print(f"\n逐年 gross CAGR — {best_label}:")
        for yr, ret in r["by_year"].items():
            bar  = "█" * max(0, int(abs(ret) * 100 / 3))
            sign = "+" if ret >= 0 else ""
            print(f"  {yr}: {sign}{ret:.1%}  {bar}")

    # ── 随机起点QC ──────────────────────────────────────────────────── #
    print("\n── 随机起点稳定性测试 (offset 0~11) ────────────────────────────")
    for col, label in configs:
        passed, rate = randomized_start_test(panel, col, hs300, label)
        verdict = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {verdict} — {label}")

    # ── 与low_vol交叉 ────────────────────────────────────────────────── #
    print("\n── low_vol × clean 交叉筛选 ─────────────────────────────────────")
    print("  (只在clean_combo rank >= 0.50 的股票里跑low_vol)")
    try:
        from research.factors.factor_low_volatility import build_low_volatility_factor
        start_str = panel["date"].min().strftime("%Y-%m-%d")
        end_str   = panel["date"].max().strftime("%Y-%m-%d")
        print("  Building low_vol factor …", flush=True)
        lv = build_low_volatility_factor(STOCK_DATA_DIR,
                                         start_date=start_str, end_date=end_str)
        lv = lv.rename(columns={"factor_z": "lv_z"})[["date","stock_symbol","lv_z"]]
        lv["date"] = pd.to_datetime(lv["date"])

        merged = panel[["date","stock_symbol","clean_combo","fwd_ret"]].merge(
            lv, on=["date","stock_symbol"], how="inner"
        )
        # clean过滤：只保留 clean_combo rank >= 0.50
        merged["clean_rank"] = merged.groupby("date")["clean_combo"].rank(pct=True)
        filtered = merged[merged["clean_rank"] >= 0.50].copy()

        # 在filtered里按lv_z排名
        filtered["rank_pct"] = filtered.groupby("date")["lv_z"].rank(pct=True)
        r_cross = buffered_backtest(filtered, "lv_z", hs300, start_offset=0)
        if r_cross:
            print(f"  low_vol×clean  CAGR_net={r_cross['ann_net']:+.2%}  "
                  f"MDD={r_cross['mdd_net']:.2%}  Calmar={r_cross['calmar']:.3f}")
        passed_cross, _ = randomized_start_test(filtered, "lv_z", hs300, "low_vol×clean")
        print(f"  {'✓ PASS' if passed_cross else '✗ FAIL'} — low_vol×clean 随机起点")
    except Exception as e:
        print(f"  low_vol交叉 skipped: {e}")

    print(f"\n结果已保存 → {OUT_DIR}/zt_ic_study.csv (IC部分)")
    print("Done.")


if __name__ == "__main__":
    main()
