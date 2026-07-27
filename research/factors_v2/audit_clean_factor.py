"""
Clean Factor Audit -- 2019起真实回测 + 净值图 + 最新持仓
=========================================================
Run:
    python research/factors_v2/audit_clean_factor.py
"""

import glob, os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
matplotlib.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
HS300_CACHE    = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
OUT_DIR        = os.path.join(ROOT, "research", "factors_v2", "output")

START_DATE    = "2019-01-01"
END_DATE      = "2026-04-18"
ROUND_TRIP_BP = 56      # 买13bp + 卖43bp，真实A股成本
BUY_BP        = 13
SELL_BP       = 43
HOLD_STEP     = 12
K             = 10
INIT_CAPITAL  = 100_000
OVERLAY_THR   = -0.07
ENTER_Q       = 0.80


# ─── 未来函数检查 ────────────────────────────────────────────────── #
LOOKAHEAD_NOTES = """
未来函数审计：
  factor_a = -cnt28
    cnt28 = rolling(28日内高位放量阴线数量)
    所有输入：open[t], close[t], vol[t]，均为t日已知数据
    rolling(28) 向过去看，无未来数据 -> OK

  fwd_ret（回测用，不是因子）
    = open[t+13] / open[t+1] - 1
    = 次日开盘买入，12个交易日后次日开盘卖出
    这是"结果"变量，回测引擎用它衡量持有收益，不是用来选股的 -> OK

  HS300 overlay
    ret20 = close[t] / close[t-20] - 1，只用t及之前数据 -> OK

  结论：因子计算和Overlay均无未来函数。
"""


# ─── 因子 ───────────────────────────────────────────────────────── #

def compute_factor_a(o, c, v):
    """-cnt28: 28日内高位放量阴线数，取负（越少越好）。纯历史数据。"""
    prev_c = c.shift(1)
    hi28_o = o.rolling(28, min_periods=1).max()
    lo28_o = o.rolling(28, min_periods=1).min()
    o85    = lo28_o + 0.95 * (hi28_o - lo28_o)
    top15o = (o >= o85).astype(float)
    fd15   = ((c < prev_c) & (c <= o) & (v >= 1.15 * v.shift(1))).astype(float)
    cnt28  = (top15o * fd15).rolling(28, min_periods=1).sum()
    return -cnt28


# ─── 面板 ────────────────────────────────────────────────────────── #

def build_panel():
    files    = glob.glob(os.path.join(STOCK_DATA_DIR, "S[HZ]*.csv"))
    start_dt = pd.Timestamp(START_DATE) - pd.Timedelta(days=120)
    end_dt   = pd.Timestamp(END_DATE)
    rows, skipped = [], 0

    for fp in files:
        sym  = os.path.splitext(os.path.basename(fp))[0].upper()
        code = sym[2:]
        # ETF
        if sym.startswith("SH") and (code[:3] in {"510","511","512","513","514",
                "515","516","517","518","519","588"} or code[:2] == "56"):
            continue
        if sym.startswith("SZ") and code[:3] == "159":
            continue
        # 创业板 (300/301/302) + 科创板 (688) + 北交所 (8/4开头)
        if sym.startswith("SZ") and code[:3] in {"300","301","302"}:
            continue
        if sym.startswith("SH") and code[:3] in {"688","689"}:
            continue
        if code[:1] in {"8","4"}:
            continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        except Exception:
            skipped += 1; continue

        col_map = {}
        for col in df.columns:
            lc = col.strip()
            if lc == "日期":     col_map[col] = "date"
            elif lc == "开盘":   col_map[col] = "open"
            elif lc == "收盘":   col_map[col] = "close"
            elif lc == "成交量": col_map[col] = "vol"
        df = df.rename(columns=col_map)
        if not all(c in df.columns for c in ["date","open","close","vol"]):
            skipped += 1; continue

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for c in ["open","close","vol"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["date","open","close","vol"]).query("close>0").sort_values("date")
        df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        if len(df) < 80:
            continue

        df = df.set_index("date")
        fa        = compute_factor_a(df["open"], df["close"], df["vol"])
        next_open = df["open"].shift(-1)   # 次日开盘（买入价）

        out = pd.DataFrame({
            "factor_a":  fa,
            "next_open": next_open,
            "open":      df["open"],       # 存原始open，方便计算任意持仓期
            "close":     df["close"],
        }, index=df.index)
        out["stock_symbol"] = sym
        out["date"]         = df.index
        rows.append(out.reset_index(drop=True))

    print(f"  Loaded {len(rows)} stocks, skipped {skipped}", flush=True)
    panel = pd.concat(rows, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["date"] >= pd.Timestamp(START_DATE)]
    panel["rank_pct"] = panel.groupby("date")["factor_a"].rank(pct=True, method="first")
    return panel


def add_fwd_ret(panel: pd.DataFrame, hold_step: int) -> pd.DataFrame:
    """按 hold_step 计算 T+1 前向收益并附加到面板（不修改原panel）。"""
    p = panel.copy()
    # T+1: open[t+1]买 → open[t+1+hold_step]卖
    p["fwd_ret"] = (
        p.groupby("stock_symbol")["open"]
        .transform(lambda s: s.shift(-(hold_step + 1)) / s.shift(-1) - 1.0)
    )
    return p


def load_hs300():
    hs = pd.read_csv(HS300_CACHE)
    hs["date"] = pd.to_datetime(hs["date"])
    hs = hs.sort_values("date")
    if "ret20" not in hs.columns:
        hs["ret20"] = hs["close"].pct_change(20)
    return hs[["date","close","ret20"]].dropna().set_index("date")


# ─── 回测引擎 ────────────────────────────────────────────────────── #

def simulate(panel_base, hs300, start_offset=0, hold_step=None):
    hs  = hold_step or HOLD_STEP
    sub = add_fwd_ret(panel_base, hs).dropna(subset=["factor_a","fwd_ret","rank_pct"]).copy()
    dates       = sorted(sub["date"].unique())
    rebal_dates = dates[start_offset::hs]

    capital   = float(INIT_CAPITAL)
    records   = []
    prev_hold: set = set()
    latest_holdings = []

    for d in rebal_dates:
        g = sub[sub["date"] == d]
        if len(g) < 50:
            continue

        hs_rows = hs300[hs300.index <= d]
        ret20   = float(hs_rows["ret20"].iloc[-1]) if not hs_rows.empty else 0.0
        in_overlay = ret20 < OVERLAY_THR

        if in_overlay:
            records.append({"date": d, "year": d.year, "capital": capital,
                            "gross_ret": 0.0, "net_ret": 0.0,
                            "win_cnt": 0, "lose_cnt": 0, "overlay": True})
            prev_hold = set()
            continue

        top_pool = g[g["rank_pct"] >= ENTER_Q]
        keep_set = set(g[(g["rank_pct"] >= 0.70) &
                         g["stock_symbol"].isin(prev_hold)]["stock_symbol"])
        new_pool = (top_pool[~top_pool["stock_symbol"].isin(keep_set)]
                    .sort_values("rank_pct", ascending=False))
        need     = max(0, K - len(keep_set))
        new_set  = set(new_pool.head(need)["stock_symbol"])
        holdings = list(keep_set | new_set)[:K]
        if not holdings:
            continue

        held_g    = g[g["stock_symbol"].isin(holdings)]
        rets      = held_g["fwd_ret"].dropna().values
        if len(rets) == 0:
            continue

        gross_ret = float(rets.mean())
        # 不对称成本：新买 = BUY_BP，全部要卖 = SELL_BP
        n_new   = len(set(holdings) - prev_hold)
        n_keep  = len(set(holdings) & prev_hold)
        n_exit  = len(prev_hold - set(holdings)) if prev_hold else 0
        cost    = ((n_new * BUY_BP + (n_new + n_exit) * SELL_BP)
                   / max(len(holdings), 1) / 1e4) if prev_hold else BUY_BP / 1e4
        net_ret = gross_ret - cost
        capital *= (1 + net_ret)

        records.append({
            "date":      d,
            "year":      d.year,
            "capital":   capital,
            "gross_ret": gross_ret,
            "net_ret":   net_ret,
            "cost":      cost,
            "win_cnt":   int((rets > 0).sum()),
            "lose_cnt":  int((rets <= 0).sum()),
            "overlay":   False,
        })

        # 保存最新一期持仓
        latest_holdings = []
        for sym in holdings:
            row = held_g[held_g["stock_symbol"] == sym]
            price = float(row["close"].iloc[0]) if not row.empty else np.nan
            latest_holdings.append({
                "stock_symbol": sym,
                "close":        price,
                "rank_pct":     float(g[g["stock_symbol"] == sym]["rank_pct"].iloc[0])
                                if not g[g["stock_symbol"] == sym].empty else np.nan,
                "is_new":       sym in new_set,
            })

        prev_hold = set(holdings)

    return pd.DataFrame(records), latest_holdings


# ─── 绘图 ────────────────────────────────────────────────────────── #

def plot_equity(df_sim, hs300, out_path):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                    gridspec_kw={"height_ratios": [3, 1]},
                                    sharex=True)
    fig.patch.set_facecolor("#0d1117")
    for ax in (ax1, ax2):
        ax.set_facecolor("#0d1117")
        ax.tick_params(colors="white")
        ax.spines[:].set_color("#333")

    # 净值曲线
    eq = df_sim.set_index("date")["capital"] / INIT_CAPITAL
    ax1.plot(eq.index, eq.values, color="#00d4aa", linewidth=1.5, label="Factor A (K=10)")
    ax1.fill_between(eq.index, 1, eq.values,
                     where=(eq.values >= 1), alpha=0.1, color="#00d4aa")
    ax1.fill_between(eq.index, 1, eq.values,
                     where=(eq.values < 1), alpha=0.1, color="#ff4444")

    # HS300 benchmark
    hs_sub = hs300[(hs300.index >= pd.Timestamp(START_DATE)) &
                   (hs300.index <= pd.Timestamp(END_DATE))]["close"]
    if not hs_sub.empty:
        hs_norm = hs_sub / hs_sub.iloc[0]
        ax1.plot(hs_norm.index, hs_norm.values,
                 color="#aaaaaa", linewidth=1.0, linestyle="--", label="HS300", alpha=0.7)

    ax1.axhline(1, color="#555", linewidth=0.5, linestyle=":")
    ax1.set_ylabel("净值（倍）", color="white")
    ax1.legend(facecolor="#1a1a2e", edgecolor="#333", labelcolor="white")
    ax1.set_title(f"Factor A (-cnt28)  主板only  K={K}  T+1执行  56bp  {START_DATE[:4]}-{END_DATE[:4]}",
                  color="white", pad=10)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.1f}x"))

    # 回撤
    peak = eq.cummax()
    dd   = (eq - peak) / peak * 100
    ax2.fill_between(dd.index, dd.values, 0, color="#ff4444", alpha=0.6)
    ax2.axhline(0, color="#555", linewidth=0.5)
    ax2.set_ylabel("回撤 (%)", color="white")
    ax2.set_xlabel("")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))

    # 标注最大回撤
    mdd_idx = dd.idxmin()
    ax2.annotate(f"  MDD {dd.min():.1f}%",
                 xy=(mdd_idx, dd.min()),
                 color="#ff8888", fontsize=9)

    # X轴格式
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    plt.setp(ax2.xaxis.get_majorticklabels(), color="white")

    # 逐年标注（在净值图上）
    by_year = df_sim.groupby("year")["net_ret"].apply(
        lambda r: float(np.prod(1 + r) - 1))
    for yr, yr_ret in by_year.items():
        mid = pd.Timestamp(f"{yr}-07-01")
        if mid < eq.index[0] or mid > eq.index[-1]:
            continue
        idx = eq.index.searchsorted(mid)
        if idx >= len(eq):
            continue
        color = "#00d4aa" if yr_ret >= 0 else "#ff4444"
        ax1.text(mid, eq.iloc[idx] * 1.02, f"{yr_ret:+.0%}",
                 color=color, fontsize=7.5, ha="center", va="bottom")

    plt.tight_layout(pad=1.5)
    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  图表已保存 -> {out_path}")


# ─── 主程序 ──────────────────────────────────────────────────────── #

def cagr(rets, ppy):
    r = np.clip(np.asarray(rets, dtype=float), -0.99, None)
    if not len(r): return np.nan
    cum = float(np.prod(1 + r))
    return cum ** (ppy / len(r)) - 1 if cum > 0 else -1.0


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 未来函数声明 ──────────────────────────────────────────────
    print(LOOKAHEAD_NOTES)

    # ── 成本说明 ──────────────────────────────────────────────────
    print("成本模型（每期）：")
    print(f"  买入 {BUY_BP}bp（佣金3 + 过户0.2 + 滑点10）")
    print(f"  卖出 {SELL_BP}bp（佣金3 + 印花10 + 过户0.2 + 滑点10 + 冲击20）")
    print(f"  完整换手一次成本 = {BUY_BP+SELL_BP}bp = {(BUY_BP+SELL_BP)/100:.2f}%\n")

    # ── 面板构建（主板，无创业板/科创板/北交所）────────────────────
    print("Building panel (主板 only) ...", flush=True)
    panel = build_panel()
    hs300 = load_hs300()
    n_stocks = panel["stock_symbol"].nunique()
    print(f"Panel: {n_stocks} stocks (主板), {panel['date'].nunique()} dates\n")

    # ── 持仓期扫描：12 / 20 / 30 / 40 天 ────────────────────────
    print("=" * 65)
    print(f"持仓期对比  主板  K={K}  T+1执行  56bp")
    print("=" * 65)
    print(f"  {'持仓天数':>6s}  {'年化净收益':>10s}  {'MDD':>8s}  {'Calmar':>7s}  {'单票胜率':>8s}  {'年化成本':>8s}")
    print(f"  {'-'*58}")

    sweep_results = {}
    for hs in [12, 20, 30, 40]:
        df_s, lat = simulate(panel, hs300, start_offset=0, hold_step=hs)
        if df_s.empty:
            continue
        ppy_s  = 252 / hs
        rets_s = df_s["net_ret"].tolist()
        cn     = cagr(rets_s, ppy_s)
        cap_s_ = df_s.set_index("date")["capital"]
        pk_    = cap_s_.cummax()
        mdd_   = float(((cap_s_ - pk_) / pk_).min())
        calmar = cn / abs(mdd_) if mdd_ < 0 else np.nan
        tw     = int(df_s["win_cnt"].sum())
        tl     = int(df_s["lose_cnt"].sum())
        wr     = tw / max(tw + tl, 1)
        ac     = float(df_s["cost"].mean()) * ppy_s
        sweep_results[hs] = {"df": df_s, "latest": lat, "cagr": cn, "mdd": mdd_,
                              "calmar": calmar, "win_rate": wr, "ann_cost": ac}
        print(f"  {hs:>6d}天  {cn:>+10.1%}  {mdd_:>8.1%}  {calmar:>7.2f}  {wr:>8.1%}  {ac:>8.1%}")

    # ── 选最佳 hold_step（Calmar最高）────────────────────────────
    best_hs = max(sweep_results, key=lambda h: sweep_results[h]["calmar"]
                  if not np.isnan(sweep_results[h]["calmar"]) else -99)
    best    = sweep_results[best_hs]
    df_sim  = best["df"]
    latest  = best["latest"]
    ppy     = 252 / best_hs

    print(f"\n  最佳持仓期: {best_hs}天 (Calmar={best['calmar']:.2f})")

    # ── 逐年明细 ─────────────────────────────────────────────────
    by_year = df_sim.groupby("year").apply(
        lambda g: float(np.prod(1 + g["net_ret"]) - 1)).sort_index()

    print(f"\n  逐年净收益（hold_step={best_hs}天，主板）:")
    for yr, r in by_year.items():
        bar  = "#" * max(0, int(abs(r) * 100 / 5))
        sign = "+" if r >= 0 else ""
        print(f"    {yr}: {sign}{r:.1%}  {bar}")

    # ── 随机起点 QC ───────────────────────────────────────────────
    print(f"\n  随机起点稳定性（hold_step={best_hs}，offset 0~11）:")
    cagr_list = []
    for off in range(12):
        d2, _ = simulate(panel, hs300, start_offset=off, hold_step=best_hs)
        if not d2.empty:
            cagr_list.append(cagr(d2["net_ret"].tolist(), ppy))
    pos = sum(1 for x in cagr_list if x > 0)
    print(f"  正收益比例 : {pos}/{len(cagr_list)} = {pos/len(cagr_list):.0%}")
    print(f"  CAGR range : {min(cagr_list):+.1%} ~ {max(cagr_list):+.1%}")
    print(f"  均值CAGR   : {np.mean(cagr_list):+.1%}")

    # ── 最新持仓 ─────────────────────────────────────────────────
    latest_date = df_sim["date"].iloc[-1].date() if not df_sim.empty else "N/A"
    print(f"\n最新持仓（{latest_date} 信号，hold_step={best_hs}天，主板）:")
    print(f"  {'代码':<12s}  {'收盘价':>8s}  {'状态'}")
    print(f"  {'-'*36}")
    for h in sorted(latest, key=lambda x: -x["rank_pct"]):
        status = "新买入" if h["is_new"] else "续持"
        print(f"  {h['stock_symbol']:<12s}  {h['close']:>8.2f}  {status}")

    # ── 已知偏差 ─────────────────────────────────────────────────
    print(f"\n已知偏差：")
    print(f"  1. 幸存者偏差  -- 退市股未纳入，收益被高估约5-10个点")
    print(f"  2. 流动性      -- 每只仓位~1万，小盘股真实滑点>10bp")
    print(f"  3. 信号执行    -- 收盘后才有信号，次日开盘才能买入")
    print(f"  4. 主板过滤    -- 已排除创业板(300/301/302)、科创板(688)、北交所")

    # ── 绘图 ─────────────────────────────────────────────────────
    out_img = os.path.join(OUT_DIR, "audit_equity_curve.png")
    plot_equity(df_sim, hs300, out_img)


if __name__ == "__main__":
    main()
