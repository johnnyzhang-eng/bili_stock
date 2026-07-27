"""
首板事件回测 — 严格可执行版 (H8)
====================================
**重要**: 此脚本替代 H1b 作为正式结论. H1b 的"T 日 close 进场"使用了 ex-post 信息
(14:55 时不知道收盘是否仍封板, 且能成交意味着板已被撬开 → 实际成交价 ≥ close 价).
H8 全部用 T+1 open 进场, 严格可在 T 日盘后下决定 + T+1 集合竞价执行, 干净可执行.

三个版本 (bug 修正后):
  V1 铁板:    T 日 pct >= 9.8 AND low / close >= 0.999  (盘中没跌破涨停, 真硬板)
  V2 烂板:    T 日 pct >= 9.8 AND low / close < 0.999   (盘中跌破过涨停, 开板再封)
  V3 追板:    T 日 pct >= 9.8 AND T+1 open in [T close × 0.95, × 1.05]
              (民间 0-5% 追板, 排除高/低开异常开盘)

注: A 股涨停时 close 即涨停价, high 必然 == close (high 不能超涨停).
    判断"开过板"必须用 low (盘中最低价是否跌破涨停).

所有版本:
  Entry:      T+1 open (集合竞价)
  Exit:       T+1 close (尾盘)
  Cost:       a_share_retail_quarterly (33bp 集合竞价 + 收盘卖)
  宇宙:       沪/深主板, 排 ST/创/科创/北交
  排除:       首板条件 — 前 5 日无涨停

预测:
  V1 应该 > V2? (硬板更强) — 但散户共识可能反着.
  V3 可能比 V1 V2 都低 (过滤掉强势开盘的真龙).
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from research.foundation import (
    DataBundle, Universe, CostModel,
    EventDrivenStrategy, Backtest, StandardReport,
)

# 配置
LIMIT_UP            = 9.8
LOOKBACK_NO_LIMIT   = 5
MAINBOARD_PREFIXES  = {"600", "601", "603", "605", "000", "001", "002", "003"}
LOW_CLOSE_RATIO     = 0.999   # low / close >= 0.999 算"没开过板" (盘中跌幅 ≤ 0.1%)


def get_st_codes(panel) -> set:
    last_name = panel.sort_values("report_date").groupby("code")["name"].last()
    return set(last_name[last_name.fillna("").str.contains("ST")].index)


def has_recent_limit_up(pct_arr: np.ndarray, i: int, lookback: int) -> bool:
    """前 lookback 日 (不含 i) 是否有涨停"""
    if i < lookback: return True  # 不够数据当作有, 跳过
    return bool((pct_arr[i - lookback:i] >= LIMIT_UP).any())


# ── V1 铁板检测 ──────────────────────────────────────────────────────────────
def make_detect_v1_iron(data: DataBundle, lookback: int = LOOKBACK_NO_LIMIT):
    """V1: T 日 pct >= 9.8 AND low / close >= 0.999 (盘中没跌破涨停)"""
    st_codes = get_st_codes(data.panel)

    def detect(price_cache):
        events = {}
        for code, df in price_cache.items():
            if code[:3] not in MAINBOARD_PREFIXES: continue
            if code in st_codes: continue
            if "pct" not in df.columns or "low" not in df.columns: continue
            if len(df) < lookback + 2: continue

            pct = df["pct"].values
            low = df["low"].values
            close = df["close"].values
            idxs = []
            for i in range(lookback, len(df) - 1):
                if pct[i] < LIMIT_UP: continue
                if has_recent_limit_up(pct, i, lookback): continue
                if close[i] <= 0: continue
                if low[i] / close[i] < LOW_CLOSE_RATIO: continue   # 跌破过 → 不算铁板
                idxs.append(int(i))
            if idxs: events[code] = idxs
        return events
    return detect


# ── V2 烂板检测 ──────────────────────────────────────────────────────────────
def make_detect_v2_rotten(data: DataBundle, lookback: int = LOOKBACK_NO_LIMIT):
    """V2: T 日 pct >= 9.8 AND low / close < 0.999 (盘中跌破过涨停, 即开过板)"""
    st_codes = get_st_codes(data.panel)

    def detect(price_cache):
        events = {}
        for code, df in price_cache.items():
            if code[:3] not in MAINBOARD_PREFIXES: continue
            if code in st_codes: continue
            if "pct" not in df.columns or "low" not in df.columns: continue
            if len(df) < lookback + 2: continue

            pct = df["pct"].values
            low = df["low"].values
            close = df["close"].values
            idxs = []
            for i in range(lookback, len(df) - 1):
                if pct[i] < LIMIT_UP: continue
                if has_recent_limit_up(pct, i, lookback): continue
                if close[i] <= 0: continue
                if low[i] / close[i] >= LOW_CLOSE_RATIO: continue   # 没跌破 → 是铁板, 不属烂板
                idxs.append(int(i))
            if idxs: events[code] = idxs
        return events
    return detect


# ── V3 0-5% 追板检测 ─────────────────────────────────────────────────────────
def make_detect_v3_chase(data: DataBundle, lookback: int = LOOKBACK_NO_LIMIT,
                          gap_lo: float = -0.05, gap_hi: float = 0.05):
    """V3: T 日 pct >= 9.8 AND 前 5 日无涨停 AND T+1 open ∈ [T close × (1+lo), × (1+hi)]"""
    st_codes = get_st_codes(data.panel)

    def detect(price_cache):
        events = {}
        for code, df in price_cache.items():
            if code[:3] not in MAINBOARD_PREFIXES: continue
            if code in st_codes: continue
            if "pct" not in df.columns or "open" not in df.columns: continue
            if len(df) < lookback + 2: continue

            pct = df["pct"].values
            open_ = df["open"].values
            close = df["close"].values
            idxs = []
            for i in range(lookback, len(df) - 1):
                if pct[i] < LIMIT_UP: continue
                if has_recent_limit_up(pct, i, lookback): continue
                # T+1 open 相对 T close 的 gap
                t1_open = open_[i + 1]
                t_close = close[i]
                if t_close <= 0: continue
                gap = t1_open / t_close - 1
                if gap < gap_lo or gap > gap_hi: continue
                idxs.append(int(i))
            if idxs: events[code] = idxs
        return events
    return detect


# ── 单次回测 ─────────────────────────────────────────────────────────────────
def run_variant(data, name: str, detect_fn, cost: CostModel) -> "BacktestResult":
    uni = Universe.broad(data, mcap_range=(5, 100000),
                          min_turnover_20d=0.0, exclude_st=True)
    strat = EventDrivenStrategy(
        name=name,
        detect_fn=detect_fn,
        entry_at="next_open",
        exit_at="next_close",
        hold_days=1,
    )
    bt = Backtest(
        strategy=strat,
        universe=uni,
        cost_model=cost,
        random_control=True,
        train_test_split=("2020-12-31", "2021-01-01"),
        seed=42,
    )
    return bt.run(verbose=False)


def summary_row(label: str, summary: dict) -> str:
    if not summary or "alpha_mean" not in summary: return f"  {label:<8s}  (空样本)"
    return (f"  {label:<8s}  n={summary['n']:>6d}  "
            f"sig={summary['signal_mean_gross']*100:>+5.2f}%  "
            f"net={summary['signal_mean_net']*100:>+5.2f}%  "
            f"rand={summary['random_mean_gross']*100:>+5.2f}%  "
            f"alpha={summary['alpha_mean']*100:>+5.2f}%  "
            f"t={summary['t_stat']:>+6.2f}  "
            f"win={summary['signal_win_pct']:>4.1f}%")


def main():
    print("=" * 80)
    print("  首板事件回测 — 严格可执行版 (H8)")
    print("=" * 80)
    print("  全部 T+1 open 进场, T+1 close 出场, cost=33bp")
    print()

    print("[1/4] 加载数据...")
    data = DataBundle.load(verbose=False)
    print(f"      OHLCV 覆盖 {data.audit.ohlcv_coverage_pct:.0f}%")
    print()

    cost = CostModel.a_share_retail_quarterly()

    variants = [
        ("V1 铁板",       make_detect_v1_iron(data)),
        ("V2 烂板",       make_detect_v2_rotten(data)),
        ("V3 0-5%追板",   make_detect_v3_chase(data, gap_lo=-0.05, gap_hi=0.05)),
    ]

    results = {}
    for i, (name, det) in enumerate(variants, start=2):
        print(f"[{i}/4] 跑 {name}...")
        # 先看事件数 (下面 backtest 会重新检测一次, 但快)
        ev = det(data.price_cache)
        n = sum(len(v) for v in ev.values())
        print(f"      事件数: {n:,}")
        res = run_variant(data, name, det, cost)
        results[name] = res

    # ── 总览对比 ──────────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  总览 (所有版本均 T+1 open 进场, 实盘可执行)")
    print("=" * 80)
    for name, res in results.items():
        print(f"\n— {name} —")
        print(summary_row("Train", res.train_summary))
        print(summary_row("Test",  res.test_summary))
        print(summary_row("Full",  res.full_summary))

    # ── 保存合并报告 ──────────────────────────────────────────────────────────
    print()
    out_dir = os.path.join(os.path.dirname(__file__), "..", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "first_board_executable.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 首板事件回测 — 严格可执行版 (H8)\n\n")
        f.write("替代 H1b (T 日 close 进场, 含 ex-post 信息).\n")
        f.write("全部用 T+1 open 进场, T+1 close 出场, cost=33bp.\n\n")
        for name, res in results.items():
            f.write(f"## {name}\n\n")
            f.write(StandardReport.from_result(res).render() + "\n\n")
    print(f"[+] 报告写入 {md_path}")

    # ── 解读模板 ──────────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  解读")
    print("=" * 80)
    h8_full = {n: r.full_summary for n, r in results.items()}
    best = max(h8_full.items(), key=lambda kv: kv[1].get("alpha_mean", -99))
    print(f"\n  最强 alpha: {best[0]}  alpha={best[1]['alpha_mean']*100:+.2f}%/笔  "
          f"t={best[1]['t_stat']:+.2f}  net={best[1]['signal_mean_net']*100:+.2f}%")
    n_pos = sum(1 for s in h8_full.values()
                  if s.get("alpha_mean", 0) > 0 and s.get("t_stat", 0) > 2)
    print(f"  显著正 alpha (alpha>0 且 t>2): {n_pos}/3 个版本")


if __name__ == "__main__":
    main()
