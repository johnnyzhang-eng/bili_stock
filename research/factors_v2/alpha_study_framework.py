"""
小盘 Alpha 验证框架 — 强制内置 Random Control
================================================
遵循 CLAUDE.md 的 backtest QC 规则:
  1. 每个因子自动跑同宇宙随机对照组
  2. Alpha 定义 = Signal - Random, 不用 HS300
  3. 宇宙覆盖率强制报告
  4. 成本统一应用
  5. 样本期偏差明确标注

用法:
  from alpha_study_framework import build_universe, run_factor_study

  df = build_universe()
  results = run_factor_study(df, factor_fn=my_factor, factor_name="MyFactor")
"""
import os, glob, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL     = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
OUT_DIR   = os.path.join(ROOT, "research", "factors_v2", "output")

# 正确披露延迟 (防前视)
CORRECT_DELAY = {1: 45, 2: 77, 3: 46, 4: 130}
Q_MONTH = [3, 6, 9, 12]
Q_DAY   = [31, 30, 30, 31]

# 真实成本 (from CLAUDE.md)
ROUND_TRIP_COST = 0.0056  # 56 bp


# ── 1. 宇宙构造 ───────────────────────────────────────────────────────────────
def build_universe(verbose=True):
    """构造完整宇宙: panel 数据 + 价格缓存 + 单季利润差分.

    返回:
        panel_df: 基本面 (含 np_single 单季利润)
        price_cache: {code: DataFrame(date, close)}
        meta: 宇宙诊断信息
    """
    if verbose: print("[+] 加载 panel...")
    raw = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    raw["report_date"] = pd.to_datetime(raw["report_date"], errors="coerce")
    raw = raw.dropna(subset=["report_date", "net_profit", "eps"])
    raw = raw[raw["eps"].abs() > 1e-6]
    raw["quarter"] = raw["report_date"].dt.quarter.astype(int)
    raw["year"]    = raw["report_date"].dt.year.astype(int)

    if verbose: print("[+] 计算单季利润 (Q1=累计, Q2-Q4=差分)...")
    rows = []
    for code, g in raw.groupby("code", sort=False):
        g = g.sort_values("report_date").reset_index(drop=True)
        for _, row in g.iterrows():
            q, yr, np_cum = int(row["quarter"]), int(row["year"]), row["net_profit"]
            if q == 1:
                np_s = np_cum
            else:
                pm = (g["year"] == yr) & (g["quarter"] == q - 1)
                np_s = np_cum - g.loc[pm, "net_profit"].values[-1] if pm.any() else np.nan
            rows.append({**row.to_dict(), "np_single": np_s})
    panel_df = pd.DataFrame(rows)

    if verbose: print("[+] 加载 OHLCV 缓存...")
    price_cache = {}
    for fp in glob.glob(os.path.join(STOCK_DIR, "*.csv")):
        code = os.path.basename(fp)[2:8]
        try:
            pf = pd.read_csv(fp, encoding="utf-8-sig")
            dc = next((c for c in ["date","日期"] if c in pf.columns), None)
            cc = next((c for c in ["close","收盘"] if c in pf.columns), None)
            tc = next((c for c in ["turn","换手率"] if c in pf.columns), None)
            if not dc or not cc: continue
            pf[dc] = pd.to_datetime(pf[dc], errors="coerce")
            pf = pf.dropna(subset=[dc, cc]).sort_values(dc).reset_index(drop=True)
            cols = {dc: "date", cc: "close"}
            if tc: cols[tc] = "turn"
            pf = pf.rename(columns=cols)
            keep = ["date", "close"] + (["turn"] if tc else [])
            price_cache[code] = pf[keep]
        except Exception:
            continue

    # 诊断
    panel_codes = set(panel_df["code"].unique())
    priced = panel_codes & set(price_cache.keys())
    meta = {
        "panel_stocks": len(panel_codes),
        "priced_stocks": len(priced),
        "coverage_pct": len(priced) / len(panel_codes) * 100,
        "panel_sh_sz": len([c for c in panel_codes if c[0] in "036789"]),
        "priced_sh_sz": len([c for c in priced if c[0] in "036789"]),
    }

    if verbose:
        print(f"  宇宙: {meta['panel_stocks']} 只 (panel)  "
              f"{meta['priced_stocks']} 只有价 ({meta['coverage_pct']:.1f}%)")
        print(f"  SH/SZ 可投: {meta['priced_sh_sz']} / {meta['panel_sh_sz']} 只")
        print(f"  BJ (4/8) 暂不可投 (无 OHLCV)")

    return panel_df, price_cache, meta


# ── 2. 定价工具 ───────────────────────────────────────────────────────────────
def _get_price_at(price_cache, code, target_date):
    if code not in price_cache: return None
    pf = price_cache[code]
    c = pf[pf["date"] >= target_date]
    return float(c.iloc[0]["close"]) if not c.empty else None


def _get_turn_20d_at(price_cache, code, target_date):
    if code not in price_cache: return None
    pf = price_cache[code]
    if "turn" not in pf.columns: return None
    sub = pf[pf["date"] < target_date].tail(20)
    return float(sub["turn"].mean()) if len(sub) >= 10 else None


# ── 3. 横截面宇宙: 某日可投股票列表 ──────────────────────────────────────────
def _investable_at(panel_df, price_cache, rpt_date, sig_date,
                   mcap_range=(30, 500), min_turn=0.15):
    """计算某信号日的可投宇宙.

    过滤条件:
      - panel 中 report_date <= rpt_date 的最新期
      - 有 OHLCV 数据且在 sig_date 可以定价
      - 市值在 mcap_range 范围 (单位: 亿)
      - 近20日换手率 >= min_turn (liquidity)

    返回: 有效 code 列表 + 各股特征 dict
    """
    avail = panel_df[panel_df["report_date"] <= rpt_date]
    latest = avail.sort_values("report_date").groupby("code").tail(1).reset_index(drop=True)

    # 只保留最新报告日 = 目标季度附近 (排除老报告掉队股)
    # 比如 sig_date 2024-05-15 要看的是 2024Q1 (或最多上半年前).
    cutoff = rpt_date - pd.Timedelta(days=200)
    latest = latest[latest["report_date"] >= cutoff]

    records = []
    for _, r in latest.iterrows():
        code = r["code"]
        if code not in price_cache: continue
        price = _get_price_at(price_cache, code, sig_date)
        if price is None or price <= 0: continue
        eps = r["eps"]
        np_v = r["net_profit"]
        if abs(eps) < 1e-6: continue
        shares_yi = abs(np_v / eps) / 1e8
        mcap_yi = price * shares_yi
        if mcap_yi < mcap_range[0] or mcap_yi > mcap_range[1]: continue
        turn = _get_turn_20d_at(price_cache, code, sig_date)
        if turn is None or turn < min_turn: continue

        records.append({
            "code": code,
            "name": r.get("name", ""),
            "industry": r.get("industry", ""),
            "report_date": r["report_date"],
            "eps": eps,
            "bps": r.get("bps", np.nan),
            "roe": r.get("roe", np.nan),
            "net_profit": np_v,
            "np_single": r.get("np_single", np.nan),
            "ocf_ps": r.get("ocf_ps", np.nan),
            "rev_yoy": r.get("rev_yoy", np.nan),
            "np_yoy": r.get("np_yoy", np.nan),
            "gross_margin": r.get("gross_margin", np.nan),
            "price": price,
            "mcap_yi": mcap_yi,
            "turn20": turn,
            "bm_ratio": r.get("bps", np.nan) / price if not pd.isna(r.get("bps", np.nan)) else np.nan,
        })
    return pd.DataFrame(records)


# ── 4. 12-1M 动量 (不含最后 1 个月) ──────────────────────────────────────────
def _momentum_12_1(price_cache, code, sig_date):
    """12 月收益减去最近 1 月收益 (经典 Jegadeesh-Titman)."""
    if code not in price_cache: return np.nan
    pf = price_cache[code]
    end = pf[pf["date"] <= sig_date]
    if len(end) < 252: return np.nan
    ret_12m = end.iloc[-1]["close"] / end.iloc[-252]["close"] - 1
    ret_1m  = end.iloc[-1]["close"] / end.iloc[-21]["close"]  - 1
    return ret_12m - ret_1m


def _vol_60d(price_cache, code, sig_date):
    if code not in price_cache: return np.nan
    pf = price_cache[code]
    sub = pf[pf["date"] <= sig_date].tail(61)
    if len(sub) < 40: return np.nan
    return float(sub["close"].pct_change().std() * np.sqrt(252))


# ── 5. 核心回测函数 — 强制带 random control ──────────────────────────────────
def run_factor_study(panel_df, price_cache, meta,
                     factor_fn,
                     factor_name: str,
                     top_pct: float = 0.20,
                     n_random: int = 30,
                     n_signal_cap: int = 30,
                     hold_days: int = 180,
                     mcap_range=(30, 500),
                     year_start: int = 2017,
                     year_end: int = 2025,
                     verbose=True):
    """
    factor_fn: signature (row_dict, price_cache, sig_date) -> float
               越大越好 (取 top_pct 的股票)
    factor_name: 展示用因子名
    top_pct: 取宇宙前 top_pct 作为信号组
    n_signal_cap: 信号组最多 N 只 (匹配 random 组大小)
    n_random: 随机对照组大小
    hold_days: 持仓天数
    """
    np.random.seed(42)  # 固定随机种子, 可复现

    periods = []
    for yr in range(year_start, year_end):
        for q in [1, 2, 3, 4]:
            rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
            sig_date = rpt_date + pd.Timedelta(days=CORRECT_DELAY[q])
            fwd_date = sig_date + pd.Timedelta(days=hold_days)
            periods.append((yr, q, rpt_date, sig_date, fwd_date))

    results = []
    for yr, q, rpt_date, sig_date, fwd_date in periods:
        uni = _investable_at(panel_df, price_cache, rpt_date, sig_date, mcap_range=mcap_range)
        if len(uni) < 50: continue

        # 算因子值
        uni["factor"] = uni.apply(
            lambda r: factor_fn(r.to_dict(), price_cache, sig_date), axis=1
        )
        uni = uni.dropna(subset=["factor"])
        if len(uni) < 30: continue

        # 信号组: top 20% 中的 n_signal_cap 只 (按因子值最高)
        uni_sorted = uni.sort_values("factor", ascending=False).reset_index(drop=True)
        n_top = max(int(len(uni_sorted) * top_pct), 10)
        signal_portfolio = uni_sorted.head(min(n_top, n_signal_cap))["code"].tolist()

        # 随机组: 从全宇宙等大小抽 n_random
        random_portfolio = np.random.choice(
            uni["code"].tolist(),
            size=min(n_random, len(uni)),
            replace=False,
        ).tolist()

        # 计算 6M 前向收益
        def _avg_fwd(codes):
            rets = []
            for c in codes:
                ep = _get_price_at(price_cache, c, sig_date)
                xp = _get_price_at(price_cache, c, fwd_date)
                if ep and xp and ep > 0:
                    rets.append(xp / ep - 1)
            return (np.mean(rets), len(rets)) if rets else (np.nan, 0)

        sig_ret, sig_n = _avg_fwd(signal_portfolio)
        rnd_ret, rnd_n = _avg_fwd(random_portfolio)
        if np.isnan(sig_ret) or np.isnan(rnd_ret): continue

        # 成本: 1 个周期 = 1 次换仓 (买 + 卖) = 56bp
        sig_net = sig_ret - ROUND_TRIP_COST
        rnd_net = rnd_ret - ROUND_TRIP_COST

        results.append({
            "yr": yr, "q": q,
            "sig_date": sig_date,
            "n_universe": len(uni),
            "n_signal":  sig_n,
            "n_random":  rnd_n,
            "signal_ret_gross":  sig_ret,
            "random_ret_gross":  rnd_ret,
            "signal_ret_net":    sig_net,
            "random_ret_net":    rnd_net,
            "alpha_gross":       sig_ret - rnd_ret,
            "alpha_net":         sig_net - rnd_net,
        })

    if not results:
        if verbose: print(f"[!] {factor_name}: 无有效回测期")
        return None

    rdf = pd.DataFrame(results)
    years = (rdf["sig_date"].max() - rdf["sig_date"].min()).days / 365.25

    # t-stat on alpha
    alpha_mean = rdf["alpha_gross"].mean()
    alpha_std  = rdf["alpha_gross"].std(ddof=1)
    t_stat = alpha_mean / (alpha_std / np.sqrt(len(rdf))) if alpha_std > 0 else np.nan

    summary = {
        "factor": factor_name,
        "periods": len(rdf),
        "avg_universe": rdf["n_universe"].mean(),
        "avg_signal_n": rdf["n_signal"].mean(),
        "signal_ret_6m_gross": rdf["signal_ret_gross"].mean(),
        "random_ret_6m_gross": rdf["random_ret_gross"].mean(),
        "alpha_6m_gross": alpha_mean,
        "alpha_6m_net":   rdf["alpha_net"].mean(),
        "alpha_std":     alpha_std,
        "t_stat": t_stat,
        "win_pct_vs_random": (rdf["alpha_gross"] > 0).mean() * 100,
        "years": years,
    }

    if verbose:
        print(f"\n=== {factor_name} ===")
        print(f"  有效期数: {summary['periods']}  平均宇宙 {summary['avg_universe']:.0f}  "
              f"信号组 {summary['avg_signal_n']:.0f} 只")
        print(f"  信号 6M: {summary['signal_ret_6m_gross']*100:>+5.2f}%   "
              f"随机 6M: {summary['random_ret_6m_gross']*100:>+5.2f}%")
        print(f"  Alpha gross: {summary['alpha_6m_gross']*100:>+5.2f}%/6M  "
              f"net: {summary['alpha_6m_net']*100:>+5.2f}%/6M  "
              f"t-stat: {summary['t_stat']:.2f}")
        print(f"  胜率 vs 随机: {summary['win_pct_vs_random']:.0f}%")
        # 年化
        ann_gross = (1 + summary['alpha_6m_gross'])**2 - 1
        ann_net   = (1 + summary['alpha_6m_net'])**2 - 1
        print(f"  年化 alpha gross: {ann_gross*100:+.1f}%  net: {ann_net*100:+.1f}%")
        # 判定
        if summary['t_stat'] > 2.0 and summary['alpha_6m_net'] > 0.005:
            print(f"  判定: ✓ 有 alpha (t>2, net>0.5%/6M)")
        elif summary['alpha_6m_net'] < 0:
            print(f"  判定: ✗ 无 alpha (net 为负)")
        else:
            print(f"  判定: ~ 边缘 (alpha<0.5%/6M or t<2)")

    return {"summary": summary, "details": rdf}
