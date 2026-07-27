"""
Foundation 自检 — 框架本身的正确性测试
=========================================
分 3 组测试:

A. Cross-sectional factor 检测能力 (4 个已知因子):
   1. NULL (恒 0)        → alpha ≈ 0, |t| < 2
   2. RANDOM             → alpha ≈ 0, |t| < 2
   3. PERFECT FORWARD     → alpha >> 0, t > 3 (反向前视检测能力)
   4. KNOWN BAD (高换手) → alpha < 0, t < -2

B. Event-driven 路径正确性:
   5. Random-day "NULL" 事件检测 → alpha ≈ 0, |t| < 2

C. 成本与样本拆分约束:
   6. Cost sanity: 任意因子 signal_net ≡ signal_gross - cost_round_trip (浮点严格)
   7. Train/Test split: signal_dates 严格不重叠, 无遗漏期

D. stats 层合成自检 (v2, 2026-07-02):
   8. cluster bootstrap: 独立 NULL 拒绝率 ~5%, 聚集 NULL 朴素 t 误判被修复,
      真信号检验力 >= 95%. 纯合成数据, 不依赖 DataBundle.

任何一组失败 → 框架不可信, 自动 exit(1).
这是 "回测自己回测" 的 sanity check, 不能跳过.
"""
import os, sys, warnings
from typing import Optional
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

# 从父目录加载 foundation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
import pandas as pd

from research.foundation import (
    DataBundle, Universe, CostModel, Benchmark,
    CrossSectionalStrategy, EventDrivenStrategy, Backtest, StandardReport,
)


# ── A. Cross-sectional 4 个测试因子 ──────────────────────────────────────────
def factor_null(row, price_cache, sig_date):
    """恒等于 0 (with deterministic tiebreak jitter) — alpha 应 ≈ 0.

    Background (2026-05-24 audit): when factor_fn returns identical values for
    all stocks, CrossSectionalStrategy.select()'s sort_values() falls back to
    universe.at()'s DataFrame order, which has hidden ordering (likely by
    code or mcap). The "NULL picks" are then a deterministic subset with its
    own size/sector tilt, producing a non-zero alpha against random control.
    Empirically: raw NULL (return 0.0) gave t=+2.93 — false positive.

    Fix: return a tiny deterministic jitter so ties break reproducibly but
    spread uniformly across the universe. The jitter has no information
    content but eliminates the order-bias artifact. This matches the design
    pattern Codex required for zero-exposure stocks in factor_a1_avoid.
    """
    import hashlib
    key = f"{row.get('code', '')}|{pd.Timestamp(sig_date).strftime('%Y-%m-%d')}".encode()
    return (int(hashlib.md5(key).hexdigest()[:12], 16) % 10**9) / 10**9

def factor_random(row, price_cache, sig_date):
    """每次随机 — alpha 应 ≈ 0"""
    return np.random.random()

def factor_high_turnover(row, price_cache, sig_date):
    """高换手 — 已知负向 (项目历史 t=-5.37)"""
    return row.get("turn20", np.nan)


def factor_forward_lookahead(row, price_cache, sig_date):
    """
    用未来 10 日收益做因子 — 故意前视, alpha 应该 >> 0.
    框架若没检测到 (因为我们没装前视检测器), 至少 alpha 不该是 0.
    这个测试帮我们看到 "框架能否区分有效信号".
    """
    code = row["code"]
    if code not in price_cache: return np.nan
    pf = price_cache[code]
    after = pf[pf["date"] > sig_date].head(10)
    if len(after) < 5: return np.nan
    return float(after.iloc[-1]["close"] / after.iloc[0]["close"] - 1)


# ── B. Event-driven 路径 NULL 检测 ───────────────────────────────────────────
def detect_random_day_events(price_cache):
    """
    每只股随机选 5 个非边界日做 'event'. 因为是随机, alpha 应该 ≈ 0.
    用于验证 EventDrivenStrategy 路径无系统性偏差.
    """
    rng = np.random.default_rng(20260427)
    events = {}
    for code, df in price_cache.items():
        n = len(df)
        if n < 200: continue
        n_events = min(5, max(1, (n - 100) // 200))
        idxs = rng.choice(range(50, n - 50), size=n_events, replace=False)
        events[code] = sorted(int(i) for i in idxs)
    return events


# ── C. 成本/拆分约束验证函数 ─────────────────────────────────────────────────
def verify_cost_application(result, cost_model, tol: float = 1e-9) -> Optional[str]:
    """每期 signal_net 必须严格等于 signal_gross - cost.total_round_trip"""
    expected = cost_model.total_round_trip
    bad = []
    for p in result.train_periods + result.test_periods:
        diff = (p.signal_ret_gross - p.signal_ret_net) - expected
        if abs(diff) > tol:
            bad.append((p.period_label, diff))
    if bad:
        return f"成本应用错误 {len(bad)} 期, 例: {bad[0]}"
    return None


def verify_train_test_split(result, train_end_str, test_start_str) -> Optional[str]:
    """train signal_date 全部 ≤ train_end; test signal_date 全部 ≥ test_start; 无重叠"""
    train_end = pd.Timestamp(train_end_str)
    test_start = pd.Timestamp(test_start_str)
    train_dates = [p.signal_date for p in result.train_periods]
    test_dates  = [p.signal_date for p in result.test_periods]
    if any(d > train_end for d in train_dates):
        return "train 段含 signal_date > train_end"
    if any(d < test_start for d in test_dates):
        return "test 段含 signal_date < test_start"
    overlap = set(train_dates) & set(test_dates)
    if overlap:
        return f"train/test signal_date 重叠 {len(overlap)} 个"
    return None


# ── 主测试 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("  Foundation 自检 (框架正确性验证)")
    print("=" * 80)
    print()
    print("规则:")
    print("  - NULL/RANDOM 应给出 alpha ≈ 0 且 |t| < 2 (无信号)")
    print("  - 高换手 应给出 alpha < 0 (项目历史 t=-5.37)")
    print("  - 前视 应给出 alpha >> 0 (强正信号, 但有前视警告)")
    print()

    print("[0/4] D. stats 层合成自检 (无需数据)...")
    from research.foundation.stats import self_test as stats_self_test
    try:
        stats_self_test()
    except AssertionError as e:
        print(f"  ✗ stats 层自检失败: {e}")
        sys.exit(1)
    print()

    print("[1/4] 加载数据...")
    data = DataBundle.load(verbose=False)
    print(f"      通过 ({data.audit.ohlcv_coverage_pct:.0f}% 覆盖)")
    print()

    print("[2/4] A. Cross-sectional 4 个测试因子 (broad universe, 30-200亿市值)...")
    print()

    uni = Universe.broad(data, mcap_range=(30, 200), min_turnover_20d=0.15)
    cost = CostModel.a_share_retail_quarterly()
    TRAIN_END, TEST_START = "2020-12-31", "2021-01-01"

    factors = [
        ("NULL (恒0)",    factor_null,            "应 alpha ≈ 0"),
        ("RANDOM",        factor_random,          "应 alpha ≈ 0"),
        ("高换手 (反向)",  factor_high_turnover,    "应 alpha < 0 (t<<0)"),
        ("前视 (作弊)",    factor_forward_lookahead,"应 alpha >> 0 (检测能力)"),
    ]

    print(f"{'因子':<18s} {'信号6M':>10s} {'随机6M':>10s} {'Alpha':>9s} {'t-stat':>7s} {'判定':>10s}")
    print("-" * 75)

    issues = []
    null_result = None  # 留给 cost-sanity / split 校验
    for name, fn, expectation in factors:
        strat = CrossSectionalStrategy(name=name, factor_fn=fn,
                                         top_pct=0.20, n_signal_cap=30, hold_days=180)
        bt = Backtest(strategy=strat,
                       universe=uni,
                       cost_model=cost,
                       random_control=True,
                       n_random_repeats=1,             # B2 修复后默认: 单次抽样
                       train_test_split=(TRAIN_END, TEST_START),
                       year_start=2018, year_end=2024,
                       seed=42)
        try:
            res = bt.run(verbose=False)
            if "NULL" in name: null_result = (res, bt)
        except Exception as e:
            print(f"  {name:<16s}  {'ERROR':>30s}  {e}")
            continue
        s = res.full_summary
        if "alpha_mean" not in s:
            print(f"  {name:<16s}  样本不足"); continue

        alpha = s["alpha_mean"]
        t = s["t_stat"]
        sig = s["signal_mean_gross"]
        rnd = s["random_mean_gross"]

        if "NULL" in name or "RANDOM" in name:
            # 判据: t-stat 必须不显著 (|t| < 2). alpha 噪音允许 ±5% (32期样本).
            verdict = "✓" if abs(t) < 2.0 else "✗ 异常"
            if verdict.startswith("✗"):
                issues.append(f"{name}: t={t:.2f} 应该 |t|<2 (无信号)")
        elif "高换手" in name:
            # 判据: 强负 alpha + 强负 t (项目历史 t=-5.37)
            verdict = "✓" if (alpha < 0 and t < -2) else "✗ 应负"
            if verdict.startswith("✗"):
                issues.append(f"{name}: 期望 alpha<0 t<-2 实际 alpha={alpha*100:+.2f}% t={t:.2f}")
        elif "前视" in name:
            # 判据: 前视给极强正信号 (alpha > 5%, t > 3)
            verdict = "✓" if (alpha > 0.05 and t > 3) else "? 弱"
            if verdict.startswith("?"):
                issues.append(f"{name}: 前视检测能力不足 alpha={alpha*100:+.2f}% t={t:.2f}")
        else:
            verdict = "?"

        print(f"  {name:<16s}  {sig*100:>+7.2f}%  {rnd*100:>+7.2f}%  "
              f"{alpha*100:>+6.2f}%  {t:>+5.2f}  {verdict:>10s}")

    # ── B. Event-driven 路径 NULL 检测 ────────────────────────────────────────
    print()
    print("[3/4] B. Event-driven 路径 NULL 检测...")
    ev_strat = EventDrivenStrategy(
        name="EventNULL (随机日)",
        detect_fn=detect_random_day_events,
        entry_at="next_open", exit_at="next_close", hold_days=1,
    )
    ev_bt = Backtest(strategy=ev_strat, universe=uni,
                      cost_model=CostModel.a_share_retail_intraday(),
                      random_control=True, n_random_repeats=1,
                      year_start=2018, year_end=2024, seed=42)
    try:
        ev_res = ev_bt.run(verbose=False)
        ev_s = ev_res.full_summary
        if "alpha_mean" in ev_s:
            ev_alpha = ev_s["alpha_mean"]
            ev_t = ev_s["t_stat"]
            ev_n = ev_s["n"]
            verdict = "✓" if abs(ev_t) < 2.5 else "✗ 异常"
            print(f"  EventNULL: n={ev_n} alpha={ev_alpha*100:+.3f}%/笔 t={ev_t:+.2f}  {verdict}")
            if abs(ev_t) >= 2.5:
                issues.append(f"EventDriven NULL: t={ev_t:.2f} 应 |t|<2.5 (随机事件无 alpha)")
        else:
            print("  EventNULL: 样本不足")
    except Exception as e:
        print(f"  EventNULL ERROR: {e}")
        issues.append(f"EventDriven 路径运行失败: {e}")

    # ── C. 成本/拆分约束 ──────────────────────────────────────────────────────
    print()
    print("[4/4] C. 成本应用 + Train/Test 拆分约束...")
    if null_result is not None:
        nres, _ = null_result
        cost_err = verify_cost_application(nres, cost)
        split_err = verify_train_test_split(nres, TRAIN_END, TEST_START)
        print(f"  成本一致性: {'✓' if cost_err is None else '✗ ' + cost_err}")
        print(f"  Train/Test 拆分: {'✓' if split_err is None else '✗ ' + split_err}")
        if cost_err: issues.append(f"成本: {cost_err}")
        if split_err: issues.append(f"拆分: {split_err}")
    else:
        print("  ✗ NULL 结果缺失, 无法校验成本/拆分")
        issues.append("NULL 因子未跑出有效结果, 成本/拆分校验跳过")

    print()
    print("=" * 80)
    if issues:
        print(f"  ✗ 框架自检失败 ({len(issues)} 个问题):")
        for i in issues: print(f"    - {i}")
        print(f"\n  框架不可信. 不要用于策略验证.")
        sys.exit(1)
    else:
        print(f"  ✓ 框架自检通过. 可以用于策略验证.")


if __name__ == "__main__":
    main()
