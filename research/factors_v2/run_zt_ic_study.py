"""
涨停 IC Study — 涨停惯性 + B1组件分解
========================================
两个研究合一：
  1. 涨停惯性：昨日涨停 → 今日/5日/10日超额收益是否显著？
  2. B1组件IC：把B1公式拆成原子条件，单独测每个条件的IC，
     找出哪些有真实预测力，哪些是噪音。

B1条件（v2.52f基础）：
  - J_OK       : KDJ J值 ≤ 13（极度超卖）
  - YANGYIN_OK1: 57日阳量 > 1.25倍阴量
  - YANGYIN_OK2: 14日阳量 > 2.05倍阴量
  - GOOD28     : 近28日高位无放量阴线
  - MAX56_OK   : 近56日最大量能不是阴线
  - GJF_RISE   : 关键防线震荡器刚从下降转上升（CC信号）

Run:
    python research/factors_v2/run_zt_ic_study.py
"""

import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
START_DATE = "2017-01-01"   # 留足滚动窗口（前57日+初始化）
END_DATE   = "2026-04-18"
ZT_THRESH  = 9.5            # 涨跌幅 >= 9.5% 视为涨停（含ST的5%涨停）


# ── TDX指标 ────────────────────────────────────────────────────────────── #

def _sma_tdx(s: pd.Series, n: int, m: int) -> pd.Series:
    """TDX SMA(X, N, M) = EMA with alpha = M/N."""
    return s.ewm(alpha=m / n, adjust=False).mean()


def _llv(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).min()


def _hhv(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).max()


def _compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all signals on a single stock's time series."""
    c = df["close"]
    o = df["open"]
    h = df["high"]
    l = df["low"]
    v = df["vol"]
    pc = df["pct_chg"]

    out = pd.DataFrame(index=df.index)

    # ── 涨停 ──────────────────────────────────────────────────────────────
    out["zt_today"]  = (pc >= ZT_THRESH).astype(float)
    # 封板近似：收盘贴近最高价（说明全天封住）
    out["zt_fengban"] = ((pc >= ZT_THRESH) & (c / h >= 0.999)).astype(float)
    # 昨日涨停（作为选股因子）
    out["zt_lag1"]   = out["zt_today"].shift(1)

    # ── KDJ / J_OK ────────────────────────────────────────────────────────
    ll9 = _llv(l, 9)
    hh9 = _hhv(h, 9)
    denom = (hh9 - ll9).replace(0, np.nan)
    rsv = (c - ll9) / denom * 100
    K = _sma_tdx(rsv, 3, 1)
    D = _sma_tdx(K, 3, 1)
    J = 3 * K - 2 * D
    out["J_val"]  = J
    out["J_OK"]   = (J <= 13).astype(float)
    out["J_OK33"] = ((J <= 13) | ((J <= 33.5) & (J.shift(1) <= 13))).astype(float)

    # ── 真阳 / 真阴 ────────────────────────────────────────────────────────
    prev_c = c.shift(1)
    real_yang = ((c > o) & ~(c < prev_c)).astype(float)
    real_yin  = ((c < o) & ~(c > prev_c)).astype(float)

    # ── 阴阳量比 ──────────────────────────────────────────────────────────
    vy57 = (v * real_yang).rolling(57, min_periods=20).sum()
    vi57 = (v * real_yin ).rolling(57, min_periods=20).sum()
    vy14 = (v * real_yang).rolling(14, min_periods=5 ).sum()
    vi14 = (v * real_yin ).rolling(14, min_periods=5 ).sum()
    out["YANGYIN_OK1"] = (vy57 > 1.25 * vi57).astype(float)
    out["YANGYIN_OK2"] = (vy14 > 2.05 * vi14).astype(float)
    # 连续量比（原始比值作为连续因子）
    out["yangyin_ratio57"] = vy57 / vi57.replace(0, np.nan)
    out["yangyin_ratio14"] = vy14 / vi14.replace(0, np.nan)

    # ── GOOD28：高位无放量阴线 ─────────────────────────────────────────────
    lo28 = _llv(o, 28)
    hi28 = _hhv(o, 28)
    o85  = lo28 + 0.95 * (hi28 - lo28)
    top15o = (o >= o85).astype(float)
    fd15   = ((c < prev_c) & (c <= o) & (v >= 1.15 * v.shift(1))).astype(float)
    cnt28  = (top15o * fd15).rolling(28, min_periods=1).sum()
    out["GOOD28"] = (cnt28 == 0).astype(float)

    # ── MAX56_OK：56日最大量能不是阴线 ────────────────────────────────────
    maxvol56  = _hhv(v, 56)
    max56_bad = ((v == maxvol56) & (real_yin == 1)).astype(float)
    out["MAX56_OK"] = (max56_bad.rolling(56, min_periods=1).sum() == 0).astype(float)

    # ── 关键防线震荡器（stable_v1 / v2.51fm N1=9,N2=3,N3=6）──────────────
    var1a = (hh9 - c) / denom * 100 - 70
    var2a = _sma_tdx(var1a, 9, 1) + 100
    var3a = (c - ll9) / denom * 100
    var4a = _sma_tdx(var3a, 3, 1)
    var5a = _sma_tdx(var4a, 3, 1) + 100
    var6a = var5a - var2a
    gjf   = var6a.clip(lower=0) - 6
    gjf   = gjf.clip(lower=0)
    aa    = (gjf.shift(1) < gjf).astype(float)   # 防线上升
    cc    = ((aa.shift(1) == 0) & (aa == 1)).astype(float)  # 刚从下降转上升
    out["GJF_val"]  = gjf
    out["GJF_AA"]   = aa
    out["GJF_CC"]   = cc   # 主触发：刚翻头

    return out


# ── 构建面板 ───────────────────────────────────────────────────────────── #

def build_panel(max_stocks: int = 0) -> pd.DataFrame:
    files = glob.glob(os.path.join(STOCK_DATA_DIR, "S[HZ]*.csv"))
    if max_stocks:
        files = files[:max_stocks]

    start_dt = pd.Timestamp(START_DATE) - pd.Timedelta(days=90)  # 留窗口
    end_dt   = pd.Timestamp(END_DATE)

    rows = []
    skipped = 0
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        if sym.endswith(".HK"):
            continue
        # ETF过滤
        code = sym[2:]
        if (sym.startswith("SH") and (code[:3] in {"510","511","512","513","514","515","516","517","518","519","588"} or code[:2] == "56")):
            continue
        if sym.startswith("SZ") and code[:3] == "159":
            continue

        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        except Exception:
            skipped += 1
            continue

        # 统一列名
        col_map = {}
        for c in df.columns:
            lc = c.strip()
            if lc in ("日期",):      col_map[c] = "date"
            elif lc in ("开盘",):    col_map[c] = "open"
            elif lc in ("收盘",):    col_map[c] = "close"
            elif lc in ("最高",):    col_map[c] = "high"
            elif lc in ("最低",):    col_map[c] = "low"
            elif lc in ("成交量",):  col_map[c] = "vol"
            elif lc in ("成交额",):  col_map[c] = "amount"
            elif lc in ("涨跌幅",):  col_map[c] = "pct_chg"
        df = df.rename(columns=col_map)

        needed = ["date", "open", "close", "high", "low", "vol"]
        if not all(c in df.columns for c in needed):
            skipped += 1
            continue

        df["date"]  = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for c in ["open", "close", "high", "low", "vol"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=needed)
        df = df[df["close"] > 0].sort_values("date")

        if "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
        else:
            df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
            # 填补缺失的pct_chg
            mask = df["pct_chg"].isna()
            df.loc[mask, "pct_chg"] = df["close"].pct_change()[mask] * 100

        df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        if len(df) < 100:
            continue

        df = df.set_index("date")
        sigs = _compute_signals(df)
        sigs["close"]        = df["close"].values
        sigs["pct_chg"]      = df["pct_chg"].values
        sigs["stock_symbol"] = sym
        sigs["date"]         = df.index
        rows.append(sigs.reset_index(drop=True))

    print(f"Loaded {len(rows)} stocks, skipped {skipped}")
    panel = pd.concat(rows, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])

    # 前向收益：用收盘价计算 h日后累计涨幅（百分比）
    panel = panel.sort_values(["stock_symbol", "date"])
    for h in [1, 5, 10]:
        panel[f"fwd_{h}d"] = (
            panel.groupby("stock_symbol")["close"]
            .transform(lambda s: s.shift(-h) / s - 1.0) * 100
        )

    # 只保留研究窗口
    panel = panel[panel["date"] >= pd.Timestamp(START_DATE)]
    return panel


# ── IC工具 ────────────────────────────────────────────────────────────── #

def _ic_series(panel: pd.DataFrame, factor: str, ret: str,
               binary: bool = False) -> pd.Series:
    """Per-date Spearman IC between factor and return."""
    sub = panel.dropna(subset=[factor, ret])
    if binary:
        # 对二值因子用rank近似
        return sub.groupby("date").apply(
            lambda g: g[factor].corr(g[ret], method="spearman")
            if len(g) >= 30 else np.nan
        ).dropna()
    return sub.groupby("date").apply(
        lambda g: g[factor].corr(g[ret], method="spearman")
        if len(g) >= 30 else np.nan
    ).dropna()


def _ic_summary(ics: pd.Series, label: str, ret_col: str) -> dict:
    if ics.empty:
        return {"factor": label, "ret": ret_col, "IC": np.nan,
                "ICIR": np.nan, "hit%": np.nan, "n": 0}
    return {
        "factor": label,
        "ret":    ret_col,
        "IC":     round(float(ics.mean()), 4),
        "ICIR":   round(float(ics.mean() / ics.std()), 3) if ics.std() > 0 else np.nan,
        "hit%":   round(float((ics > 0).mean() * 100), 1),
        "n":      len(ics),
    }


# ── 涨停惯性专项分析 ───────────────────────────────────────────────────── #

def analyze_zt_continuation(panel: pd.DataFrame):
    print("\n" + "="*70)
    print("【涨停惯性分析】")
    print("="*70)

    zt_events = panel[panel["zt_lag1"] == 1].copy()
    non_zt    = panel[panel["zt_lag1"] == 0].copy()

    print(f"  涨停次日样本: {len(zt_events):,}  /  非涨停次日: {len(non_zt):,}")

    for h in [1, 5, 10]:
        col = f"fwd_{h}d"
        zt_sub  = zt_events[col].dropna()
        all_sub = panel[col].dropna()
        if zt_sub.empty:
            continue
        excess = zt_sub.mean() - all_sub.mean()
        pos_rate = (zt_sub > 0).mean()
        print(f"\n  {h}日后（涨停次日 vs 全市场）:")
        print(f"    涨停次日均值: {zt_sub.mean():+.2f}%   |  全市场均值: {all_sub.mean():+.2f}%   |  超额: {excess:+.2f}%")
        print(f"    涨停次日正收益率: {pos_rate:.1%}")
        print(f"    涨停次日中位数: {zt_sub.median():+.2f}%")

    # 封板 vs 非封板
    fb_events    = panel[(panel["zt_lag1"] == 1) & (panel["zt_fengban"].shift(1) == 1)].copy()
    nonfb_events = panel[(panel["zt_lag1"] == 1) & (panel["zt_fengban"].shift(1) == 0)].copy()
    print(f"\n  封板涨停次日: {len(fb_events):,}  vs  非封板涨停次日: {len(nonfb_events):,}")
    for h in [1, 5]:
        col = f"fwd_{h}d"
        fb_m  = fb_events[col].dropna().mean()
        nfb_m = nonfb_events[col].dropna().mean()
        print(f"    {h}日后 — 封板: {fb_m:+.2f}%  |  非封板: {nfb_m:+.2f}%")

    # 年度分布
    print(f"\n  涨停次日1日均值 — 按年:")
    zt_events["year"] = zt_events["date"].dt.year
    by_yr = zt_events.groupby("year")["fwd_1d"].mean().dropna()
    for yr, v in by_yr.items():
        bar  = "█" * max(0, int(abs(v) / 0.5))
        sign = "+" if v >= 0 else ""
        print(f"    {yr}: {sign}{v:.2f}%  {bar}")


# ── 主程序 ────────────────────────────────────────────────────────────── #

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Building panel …", flush=True)
    panel = build_panel()
    print(f"Panel: {panel['stock_symbol'].nunique()} stocks, "
          f"{panel['date'].nunique()} dates, {len(panel):,} rows")

    # ── 涨停惯性 ─────────────────────────────────────────────────────── #
    analyze_zt_continuation(panel)

    # ── 各信号 IC ─────────────────────────────────────────────────────── #
    factors = [
        ("zt_lag1",         "昨日涨停",         True),
        ("J_OK",            "J≤13（超卖）",      True),
        ("J_OK33",          "J≤33.5宽松版",     True),
        ("J_val",           "J值（连续）",       False),
        ("YANGYIN_OK1",     "57日量比>1.25",    True),
        ("YANGYIN_OK2",     "14日量比>2.05",    True),
        ("yangyin_ratio57", "57日量比（连续）",  False),
        ("yangyin_ratio14", "14日量比（连续）",  False),
        ("GOOD28",          "GOOD28无高位阴",   True),
        ("MAX56_OK",        "MAX56无放量阴",     True),
        ("GJF_CC",          "关键防线刚上穿",   True),
        ("GJF_AA",          "关键防线上升中",   True),
        ("GJF_val",         "关键防线值（连续）",False),
    ]

    print(f"\n{'='*70}")
    print("【B1组件 IC分析】")
    print(f"{'='*70}")
    print(f"{'因子':<22s}  {'fwd_1d IC':>9s} {'ICIR':>6s} {'hit%':>6s}  "
          f"{'fwd_5d IC':>9s} {'ICIR':>6s} {'hit%':>6s}  "
          f"{'fwd_10d IC':>10s} {'ICIR':>6s} {'hit%':>6s}")
    print("-" * 100)

    all_rows = []
    for col, label, binary in factors:
        if col not in panel.columns:
            continue
        row = {"factor": col, "label": label}
        parts = []
        for h in [1, 5, 10]:
            ret = f"fwd_{h}d"
            ics = _ic_series(panel, col, ret, binary)
            s   = _ic_summary(ics, label, ret)
            row.update({f"IC_{h}d": s["IC"], f"ICIR_{h}d": s["ICIR"], f"hit_{h}d": s["hit%"]})
            parts.append(f"{s['IC']:>+9.4f} {s['ICIR']:>6.3f} {s['hit%']:>5.1f}%")
        all_rows.append(row)
        print(f"{label:<22s}  {'  '.join(parts)}")

    pd.DataFrame(all_rows).to_csv(
        os.path.join(OUT_DIR, "zt_ic_study.csv"), index=False, encoding="utf-8-sig"
    )

    # ── 组合B1有效条件 ────────────────────────────────────────────────── #
    print(f"\n{'='*70}")
    print("【B1完整公式 vs 有效条件组合 回测对比（IC维度）】")
    print(f"{'='*70}")

    # 原始B1最终信号（不含关键防线，基础量价版）
    panel["b1_base"] = (
        panel["J_OK"] *
        panel["YANGYIN_OK1"] *
        panel["GOOD28"] *
        panel["MAX56_OK"]
    )
    # 含关键防线的完整信号
    panel["b1_full"] = panel["b1_base"] * panel["GJF_CC"]

    for col, label in [("b1_base", "B1基础（量价，无防线）"),
                        ("b1_full", "B1完整（量价+防线CC）")]:
        parts = []
        for h in [1, 5, 10]:
            ics = _ic_series(panel, col, f"fwd_{h}d", binary=True)
            s   = _ic_summary(ics, label, f"fwd_{h}d")
            parts.append(f"{s['IC']:>+9.4f} {s['ICIR']:>6.3f} {s['hit%']:>5.1f}%  [n={s['n']}]")
        print(f"{label:<28s}")
        for h, p in zip([1, 5, 10], parts):
            print(f"  fwd_{h}d: {p}")

    # B1信号触发频率
    print(f"\n  信号触发率（全样本）:")
    for col, label in [("J_OK", "J_OK"), ("YANGYIN_OK1","YANGYIN_OK1"),
                        ("GOOD28","GOOD28"), ("MAX56_OK","MAX56_OK"),
                        ("b1_base","B1_base"), ("b1_full","B1_full（+CC）")]:
        if col in panel.columns:
            rate = panel[col].mean()
            print(f"    {label:<20s}: {rate:.2%}")

    print(f"\n结果已保存 → {OUT_DIR}/zt_ic_study.csv")


if __name__ == "__main__":
    main()
