"""
首板事件回测 (H1 / H1b / H3)
====================================
H1:  次日开盘买、次日收盘卖, cost=33bp        ← 普通散户操作
H1b: 当日尾盘抢板买, 次日收盘卖, cost=186bp   ← 游资节奏
H3:  H1 events 按信号日 turn 三分位切分        ← 低换手 vs 高换手板的 alpha 差异

由 foundation 的 EventDrivenStrategy 跑, random baseline 是同股 ±90 交易日内随机非事件日.

宇宙: 沪/深主板 (600/601/603/605/000/001/002/003), 排除创业板/科创板/北交所/ST.
原因: 首板进二战法语境是主板 ±10% 涨停, 创业板/科创板 ±20% 节奏完全不同.

数据警告:
- 涨停阈值用 9.8 (主板 ±10%, 留 0.2% 浮动余量)
- 价格使用前复权, 已通过 audit 复权一致性 (~95%)
- 没有封单/题材/龙头数据 → 这是 "毛胚版无筛选" 测试
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from research.foundation import (
    DataBundle, Universe, CostModel,
    EventDrivenStrategy, Backtest, StandardReport,
)

# ── 阈值与宇宙配置 ─────────────────────────────────────────────────────────────
LIMIT_UP            = 9.8     # 主板 ±10%, 留 0.2% 浮动余量
LOOKBACK_NO_LIMIT   = 5       # 前 N 日无涨停才算"首板"
MAINBOARD_PREFIXES  = {"600", "601", "603", "605", "000", "001", "002", "003"}
# 排除:
#   688 (科创板 ±20%) / 300, 301 (创业板 ±20% 自 2020-08-24) / 4,8 (北交所 ±30% 且无 OHLCV)


# ── Detect 函数构造 ───────────────────────────────────────────────────────────
def make_first_board_detect(data: DataBundle,
                              lookback: int = LOOKBACK_NO_LIMIT,
                              exclude_st: bool = True):
    """
    返回 detect_fn 闭包. 闭包内捕获 panel 用于 ST 过滤, 调用时只接 price_cache.
    """
    panel = data.panel
    if exclude_st:
        last_name = panel.sort_values("report_date").groupby("code")["name"].last()
        st_codes = set(last_name[last_name.fillna("").str.contains("ST")].index)
    else:
        st_codes = set()

    def detect(price_cache: Dict[str, pd.DataFrame]) -> Dict[str, List[int]]:
        events: Dict[str, List[int]] = {}
        for code, df in price_cache.items():
            if code[:3] not in MAINBOARD_PREFIXES: continue
            if code in st_codes: continue
            if "pct" not in df.columns: continue
            if len(df) < lookback + 2: continue

            pct = df["pct"].values
            idxs = []
            # i: 信号日; range 上限 len-1 留次日做 entry
            for i in range(lookback, len(df) - 1):
                if pct[i] < LIMIT_UP: continue
                if (pct[i - lookback:i] >= LIMIT_UP).any(): continue
                idxs.append(int(i))
            if idxs: events[code] = idxs
        return events
    return detect


def build_h3_turn_lookup(price_cache: Dict[str, pd.DataFrame],
                          events_dict: Dict[str, List[int]],
                          entry_at: str) -> Dict:
    """
    为 H3 准备 (code, entry_date) → 信号日 turn 映射.
    entry_at='next_open': entry_date = df.iloc[idx+1].date, signal_day = idx
    entry_at='today_close': entry_date = df.iloc[idx].date, signal_day = idx
    """
    lookup = {}
    t_off = 1 if entry_at == "next_open" else 0
    for code, idx_list in events_dict.items():
        df = price_cache.get(code)
        if df is None or "turn" not in df.columns: continue
        for idx in idx_list:
            entry_idx = idx + t_off
            if entry_idx >= len(df): continue
            entry_date = df.iloc[entry_idx]["date"]
            t = df.iloc[idx]["turn"]   # 信号日本身的 turn
            if pd.isna(t): continue
            lookup[(code, entry_date)] = float(t)
    return lookup


def cost_sensitivity_table(result, cost_grid_bps: List[int]) -> pd.DataFrame:
    """成本敏感性: 给定 round-trip cost 列表 (bp), 计 signal_net 和 alpha (alpha 不变)."""
    sg = result.full_summary.get("signal_mean_gross", 0)
    rg = result.full_summary.get("random_mean_gross", 0)
    rows = []
    for c_bp in cost_grid_bps:
        c = c_bp / 10000
        rows.append({
            "round_trip_bp": c_bp,
            "signal_gross": sg,
            "signal_net":   sg - c,
            "random_net":   rg - c,
            "alpha":        sg - rg,             # cost 抵消, alpha 不变
            "signal_net_pos": "✓" if (sg - c) > 0 else "✗",
        })
    return pd.DataFrame(rows)


def yearly_alpha_stability(result) -> pd.DataFrame:
    """H1b alpha 按年聚合, 看是否被 1-2 异常年驱动."""
    rows = []
    for p in result.train_periods + result.test_periods:
        if p.alpha_gross is None: continue
        rows.append({
            "year": p.signal_date.year,
            "alpha": p.alpha_gross,
            "ret": p.signal_ret_gross,
        })
    df = pd.DataFrame(rows)
    if df.empty: return df
    grp = df.groupby("year").agg(
        n=("alpha", "size"),
        alpha=("alpha", "mean"),
        ret=("ret", "mean"),
        win=("ret", lambda x: (x > 0).mean() * 100),
    ).reset_index()
    # per-year t-stat
    grp_t = df.groupby("year")["alpha"].agg(
        lambda x: x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) >= 5 and x.std(ddof=1) > 0 else float("nan")
    ).reset_index().rename(columns={"alpha": "t_stat"})
    return grp.merge(grp_t, on="year")


def bootstrap_alpha_ci(result, n_boot: int = 2000, seed: int = 42) -> dict:
    """事件 alpha bootstrap 95% CI. 用于检验 t-stat 大样本膨胀的稳健性."""
    alphas = np.array([p.alpha_gross for p in result.train_periods + result.test_periods
                        if p.alpha_gross is not None])
    if len(alphas) < 100:
        return {"n": len(alphas)}
    rng = np.random.default_rng(seed)
    boot_means = []
    for _ in range(n_boot):
        sample = rng.choice(alphas, size=len(alphas), replace=True)
        boot_means.append(sample.mean())
    boot_means = np.array(boot_means)
    return {
        "n": len(alphas),
        "alpha_mean": float(alphas.mean()),
        "ci_low": float(np.percentile(boot_means, 2.5)),
        "ci_high": float(np.percentile(boot_means, 97.5)),
        "ci_width": float(np.percentile(boot_means, 97.5) - np.percentile(boot_means, 2.5)),
    }


def h3_turn_bucket_analysis(result, lookup: Dict, n_buckets: int = 3) -> pd.DataFrame:
    """按信号日 turn 三分位切 events, 计每桶 alpha + t-stat."""
    rows = []
    for p in result.train_periods + result.test_periods:
        code = p.signal_picks[0]
        key = (code, p.signal_date)
        t = lookup.get(key)
        if t is None or p.alpha_gross is None: continue
        rows.append({
            "code": code,
            "signal_date": p.signal_date,
            "turn": t,
            "ret_gross": p.signal_ret_gross,
            "ret_net": p.signal_ret_net,
            "alpha": p.alpha_gross,
            "is_train": p.signal_date <= pd.Timestamp(result.train_test_split[0]),
        })
    df = pd.DataFrame(rows)
    if df.empty: return df

    # 全样本 turn 分位边界 (.values 在新 pandas 是 read-only, 显式 copy)
    qs = np.linspace(0, 1, n_buckets + 1)
    edges = np.array(df["turn"].quantile(qs).values, dtype=float, copy=True)
    edges[0] -= 1e-9; edges[-1] += 1e-9
    df["bucket"] = pd.cut(df["turn"], bins=edges,
                            labels=[f"Q{i+1}" for i in range(n_buckets)])

    out = []
    for label, g in df.groupby("bucket"):
        if len(g) < 5: continue
        alpha = g["alpha"]
        se = alpha.std(ddof=1) / np.sqrt(len(alpha))
        t_stat = alpha.mean() / se if se > 0 else float("nan")
        out.append({
            "bucket": label,
            "n": len(g),
            "turn_mean": g["turn"].mean(),
            "ret_gross": g["ret_gross"].mean(),
            "ret_net": g["ret_net"].mean(),
            "alpha": alpha.mean(),
            "win": (g["ret_gross"] > 0).mean() * 100,
            "t_stat": t_stat,
        })
    return pd.DataFrame(out)


# ── 行业分群报告 ─────────────────────────────────────────────────────────────
def industry_breakdown(result, data: DataBundle, top_n: int = 12) -> pd.DataFrame:
    """按行业分组聚合 alpha / 胜率 / 样本数. 返回排序后的 DataFrame."""
    last_industry = (data.panel.sort_values("report_date")
                          .groupby("code")["industry"].last())

    rows = []
    for p in result.train_periods + result.test_periods:
        code = p.signal_picks[0]  # event-driven 一票
        ind = last_industry.get(code, "未分类")
        rows.append({
            "industry": ind,
            "code": code,
            "signal_date": p.signal_date,
            "ret_gross": p.signal_ret_gross,
            "ret_net": p.signal_ret_net,
            "alpha": p.alpha_gross if p.alpha_gross is not None else np.nan,
        })
    df = pd.DataFrame(rows)
    if df.empty: return df

    grp = df.groupby("industry").agg(
        n=("ret_gross", "size"),
        ret_gross=("ret_gross", "mean"),
        ret_net=("ret_net", "mean"),
        alpha=("alpha", "mean"),
        win=("ret_gross", lambda x: (x > 0).mean() * 100),
    ).reset_index()
    # alpha t-stat per industry
    grp_t = df.groupby("industry")["alpha"].agg(
        lambda x: x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) >= 5 and x.std(ddof=1) > 0 else np.nan
    ).reset_index().rename(columns={"alpha": "t_stat"})
    grp = grp.merge(grp_t, on="industry")

    return grp.sort_values("n", ascending=False).head(top_n)


# ── 单次回测 (H1 / H1b 共用) ─────────────────────────────────────────────────
def run_first_board_backtest(data, detect_fn, entry_at, cost, name):
    uni = Universe.broad(data, mcap_range=(5, 100000),
                          min_turnover_20d=0.0,
                          exclude_st=True)
    strat = EventDrivenStrategy(
        name=name,
        detect_fn=detect_fn,
        entry_at=entry_at,
        exit_at="next_close",
        hold_days=1,
    )
    bt = Backtest(
        strategy=strat,
        universe=uni,
        cost_model=cost,
        random_control=True,
        train_test_split=("2020-12-31", "2021-01-01"),
        year_start=2017, year_end=2025,
        seed=42,
    )
    return bt.run(verbose=False)


def print_summary_table(label: str, summary: dict):
    if not summary or "alpha_mean" not in summary: return
    n = summary.get("n", 0)
    sg = summary.get("signal_mean_gross", 0)
    sn = summary.get("signal_mean_net", 0)
    rg = summary.get("random_mean_gross", 0)
    a  = summary.get("alpha_mean", 0)
    t  = summary.get("t_stat", float("nan"))
    win_sig = summary.get("signal_win_pct", 0)
    print(f"  {label:<6s} n={n:>5d}  sig_gross={sg*100:>+5.2f}%  sig_net={sn*100:>+5.2f}%  "
          f"rand={rg*100:>+5.2f}%  alpha={a*100:>+5.2f}%  t={t:>+6.2f}  win={win_sig:>4.1f}%")


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("  首板事件回测套件: H1 / H1b / H3")
    print("=" * 80)
    print()

    print("[1/4] 加载数据...")
    data = DataBundle.load(verbose=False)
    print(f"      OHLCV 覆盖 {data.audit.ohlcv_coverage_pct:.0f}%")

    detect_fn = make_first_board_detect(data, exclude_st=True)
    # 预算事件 (用于 H3 lookup)
    print("[2/4] 检测首板事件...")
    events_dict = detect_fn(data.price_cache)
    n_events = sum(len(v) for v in events_dict.values())
    print(f"      {n_events:,} 个首板信号 (主板沪/深, 排 ST/创/科创/北交)")
    print()

    # ── H1: 次日开盘买 ────────────────────────────────────────────────────────
    print("[3/4] H1 跑回测 (次日 open 买, 次日 close 卖, cost=33bp 集合竞价)...")
    res_h1 = run_first_board_backtest(
        data, detect_fn,
        entry_at="next_open",
        cost=CostModel.a_share_retail_quarterly(),
        name="H1 首板·次日开盘买",
    )
    print()

    # ── H1b: 尾盘抢板 ──────────────────────────────────────────────────────────
    print("[4/4] H1b 跑回测 (信号日 close 抢板, 次日 close 卖, cost=186bp 抢板)...")
    res_h1b = run_first_board_backtest(
        data, detect_fn,
        entry_at="today_close",
        cost=CostModel.a_share_retail_intraday(),  # 100bp 抢板 + 50bp 抛压
        name="H1b 首板·尾盘抢板",
    )
    print()

    # ── 总览对比 ──────────────────────────────────────────────────────────────
    print("=" * 80)
    print("  H1 vs H1b 总览")
    print("=" * 80)
    for label, res in [("H1 (次日 open)", res_h1), ("H1b (尾盘抢板)", res_h1b)]:
        print(f"\n— {label} —")
        print_summary_table("Train", res.train_summary)
        print_summary_table("Test",  res.test_summary)
        print_summary_table("Full",  res.full_summary)

    # ── H3 + A: 换手率三分位切 H1 与 H1b ──────────────────────────────────────
    print()
    print("=" * 80)
    print("  H3 + A: 按信号日 turn 三分位切 (Q1 低换手 / Q3 高换手)")
    print("=" * 80)
    lookup_h1  = build_h3_turn_lookup(data.price_cache, events_dict, entry_at="next_open")
    lookup_h1b = build_h3_turn_lookup(data.price_cache, events_dict, entry_at="today_close")
    h3_h1  = h3_turn_bucket_analysis(res_h1,  lookup_h1,  n_buckets=3)
    h3_h1b = h3_turn_bucket_analysis(res_h1b, lookup_h1b, n_buckets=3)

    def print_bucket_table(label, df):
        print(f"\n— {label} —")
        if df.empty:
            print("  (空)"); return
        print(f"{'桶':<5s}{'n':>7s}{'turn 均值':>12s}{'gross':>10s}{'net':>10s}{'alpha':>10s}{'胜率':>8s}{'t':>8s}")
        for _, r in df.iterrows():
            t_str = f"{r['t_stat']:+.2f}" if not pd.isna(r['t_stat']) else "  --"
            print(f"  {str(r['bucket']):<5s}{int(r['n']):>7d}{r['turn_mean']:>10.2f}%"
                  f"{r['ret_gross']*100:>+8.2f}%"
                  f"{r['ret_net']*100:>+8.2f}%"
                  f"{r['alpha']*100:>+8.2f}%"
                  f"{r['win']:>7.0f}%"
                  f"{t_str:>8s}")

    print_bucket_table("H1 次日 open 买", h3_h1)
    print_bucket_table("H1b 尾盘抢板", h3_h1b)
    print()
    print("  解读: Q1=低换手 (锁仓板)  Q3=高换手 (博弈板)")

    # ── D: H1b 成本敏感性 ─────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  D: H1b 成本敏感性 (round-trip 25-200bp 扫描)")
    print("=" * 80)
    cost_df = cost_sensitivity_table(res_h1b, [25, 50, 75, 100, 125, 150, 175, 200])
    print(f"\n{'cost (bp)':>10s}{'sig_gross':>12s}{'sig_net':>12s}{'rand_net':>12s}{'alpha':>10s}{'净>0?':>7s}")
    for _, r in cost_df.iterrows():
        print(f"  {int(r['round_trip_bp']):>8d}"
              f"{r['signal_gross']*100:>+10.2f}%"
              f"{r['signal_net']*100:>+10.2f}%"
              f"{r['random_net']*100:>+10.2f}%"
              f"{r['alpha']*100:>+8.2f}%"
              f"{r['signal_net_pos']:>7s}")
    print(f"\n  alpha 不随 cost 变 (signal/random 都扣同样 cost)")
    print(f"  break-even: 当 round-trip = signal_gross = "
          f"{res_h1b.full_summary['signal_mean_gross']*100:.2f}%")

    # ── E: H1b alpha 年度稳定性 ───────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  E: H1b alpha 年度稳定性 (单年 alpha < 0 几个?)")
    print("=" * 80)
    yr_df = yearly_alpha_stability(res_h1b)
    print(f"\n{'year':>6s}{'n':>7s}{'ret':>10s}{'alpha':>10s}{'胜率':>8s}{'t':>8s}")
    for _, r in yr_df.iterrows():
        t_str = f"{r['t_stat']:+.2f}" if not pd.isna(r['t_stat']) else "  --"
        print(f"  {int(r['year']):>4d}{int(r['n']):>7d}"
              f"{r['ret']*100:>+8.2f}%"
              f"{r['alpha']*100:>+8.2f}%"
              f"{r['win']:>7.0f}%"
              f"{t_str:>8s}")
    n_neg_yr = (yr_df["alpha"] < 0).sum()
    print(f"\n  负 alpha 年份: {n_neg_yr} / {len(yr_df)}")
    if n_neg_yr <= 2:
        print("  → 年度方向稳健 (大多数年份正 alpha)")
    else:
        print("  → 年度方向不稳, 平均值可能被异常年拉高")

    # ── F: H1b alpha bootstrap 95% CI ─────────────────────────────────────────
    print()
    print("=" * 80)
    print("  F: H1b alpha bootstrap 95% CI (2000 次重抽)")
    print("=" * 80)
    boot = bootstrap_alpha_ci(res_h1b, n_boot=2000, seed=42)
    if "ci_low" in boot:
        print(f"\n  n={boot['n']:,}")
        print(f"  alpha 点估: {boot['alpha_mean']*100:+.3f}%/笔")
        print(f"  95% CI:     [{boot['ci_low']*100:+.3f}%, {boot['ci_high']*100:+.3f}%]")
        print(f"  CI 宽度:    {boot['ci_width']*100:.3f}%")
        if boot["ci_low"] > 0:
            print(f"  → CI 完全在 0 之上, alpha 鲁棒")
        else:
            print(f"  → CI 跨 0, alpha 不稳健")

    # ── 行业分群 (H1) ─────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  H1 行业分群 (Top 12 by 样本数)")
    print("=" * 80)
    ind_df = industry_breakdown(res_h1, data, top_n=12)
    if not ind_df.empty:
        print(f"\n{'行业':<14s}{'n':>6s}{'gross':>9s}{'net':>9s}{'alpha':>9s}{'win%':>7s}{'t':>7s}")
        for _, r in ind_df.iterrows():
            t_str = f"{r['t_stat']:+.2f}" if not pd.isna(r['t_stat']) else "  --"
            print(f"  {r['industry']:<12s}{int(r['n']):>6d}"
                  f"{r['ret_gross']*100:>+8.2f}%"
                  f"{r['ret_net']*100:>+8.2f}%"
                  f"{r['alpha']*100:>+8.2f}%"
                  f"{r['win']:>6.0f}%"
                  f"{t_str:>7s}")

    # ── 一进二率 ──────────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  一进二率 (信号次日是否再涨停)")
    print("=" * 80)
    next_lu, total = 0, 0
    cache = data.price_cache
    for p in res_h1.train_periods + res_h1.test_periods:
        code = p.signal_picks[0]
        df = cache.get(code)
        if df is None: continue
        m = df["date"] == p.signal_date
        if not m.any(): continue
        total += 1
        if df.loc[m, "pct"].iloc[0] >= LIMIT_UP:
            next_lu += 1
    if total > 0:
        print(f"  {next_lu:,} / {total:,} = {next_lu/total*100:.1f}% 次日涨停 (一进二成功率)")

    # ── 保存合并报告 ──────────────────────────────────────────────────────────
    out_dir = os.path.join(os.path.dirname(__file__), "..", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "first_board_suite.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 首板事件回测套件 (H1 / H1b / H3)\n\n")
        f.write(f"事件数: {n_events:,} (主板沪/深 2014-2025)\n\n")
        for label, res in [("H1 次日 open 买 (cost 33bp)", res_h1),
                            ("H1b 尾盘抢板 (cost 186bp)",  res_h1b)]:
            f.write(f"## {label}\n\n")
            f.write(StandardReport.from_result(res).render() + "\n\n")
        if not h3_h1.empty:
            f.write("## H3 — H1 (次日 open) 按 turn 分位\n\n")
            f.write(h3_h1.to_markdown(index=False) + "\n\n")
        if not h3_h1b.empty:
            f.write("## A — H1b (尾盘抢板) 按 turn 分位\n\n")
            f.write(h3_h1b.to_markdown(index=False) + "\n\n")
        f.write("## D — H1b 成本敏感性\n\n")
        f.write(cost_df.to_markdown(index=False) + "\n\n")
        f.write("## E — H1b 年度稳定性\n\n")
        f.write(yr_df.to_markdown(index=False) + "\n\n")
        f.write("## F — H1b bootstrap 95% CI\n\n")
        for k, v in boot.items():
            v_str = f"{v*100:.3f}%" if isinstance(v, float) and abs(v) < 1 else str(v)
            f.write(f"- {k}: {v_str}\n")
        f.write("\n")
        if not ind_df.empty:
            f.write("## H1 行业分群\n\n")
            f.write(ind_df.to_markdown(index=False) + "\n\n")
        f.write(f"## 一进二率\n\n- {next_lu:,} / {total:,} = {next_lu/total*100:.1f}%\n")
    print(f"\n[+] 合并报告写入 {md_path}")


if __name__ == "__main__":
    main()
