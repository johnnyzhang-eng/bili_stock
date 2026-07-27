"""
52-Week High Momentum (George & Hwang 2004) — foundation 验证
================================================================
研报溯源:
  George, T.J. & Hwang, C.-Y. (2004), "The 52-Week High and Momentum Investing",
  Journal of Finance 59, 2145-2176.

  Replication: 海通证券金工 (2017) "锚定效应与 52 周高点策略" 在 A 股 2010-2016 给出
  Long-only top 20% net of 56bp 成本 ≈ +5%/年 (作者口径), 未做 random control.

因子定义:
  factor_raw = close_today / max(close over past 252 bdays)
  越接近 1 (= 离顶越近), 因子越大 → 被选中

行为故事:
  锚定偏差: 投资者把"52 周高点"作为心理价格上限, 当股价靠近该位置时, 卖压增加,
  买入意愿降低 → 形成低估 → 未来反向修复 (实证: 短线上涨)

为什么不和现有 12 因子重复:
  - 不同于 12-1M 动量 (Jegadeesh-Titman): 后者看累计 ret, 本因子只看相对位置
  - 不同于低波 60d / MAX: 行为机制是 anchoring, 不是 vol / lottery
  - 不同于反转 1M: 反转是短期均值回归, 此为中长期 trend 延续

测试设计 (foundation 强制):
  - DataBundle.load() 自动审计
  - Universe broad 30-500亿, 与 factor_battery_test 同口径
  - random_control=True, 同宇宙剔除 picks 后随机
  - train_test_split = ("2020-12-31", "2021-01-01")
    train 2017-2020 (含 2018 熊 / 2019 反弹 / 2020 V), test 2021-2024 (含 2022 熊)
  - CostModel.a_share_retail_quarterly (33bp round-trip, 与 180d 持仓周期匹配)
  - hold_days=180 与 factor_battery_test 对齐, 可直接比较
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
import pandas as pd

from research.foundation import (
    DataBundle, Universe, CostModel,
    CrossSectionalStrategy, Backtest, StandardReport,
)


# ── 因子定义 ─────────────────────────────────────────────────────────────────
def factor_52w_high(row, price_cache, sig_date):
    """52 周高点比率: close_today / max(close, past 252 bdays). 越大越好."""
    code = row["code"]
    if code not in price_cache: return np.nan
    pf = price_cache[code]
    sub = pf[pf["date"] <= sig_date].tail(253)
    if len(sub) < 200: return np.nan  # 至少 ~10 个月历史
    px_now = float(sub.iloc[-1]["close"])
    px_max = float(sub["close"].max())
    if px_max <= 0 or px_now <= 0: return np.nan
    return px_now / px_max


# ── 对照: 远离 52 周高点 (理论上反向, 用作 negative control) ────────────────
def factor_52w_low(row, price_cache, sig_date):
    """远离 52 周高点: 1 - close/max. 用作方向性 sanity check."""
    v = factor_52w_high(row, price_cache, sig_date)
    if v is None or np.isnan(v): return np.nan
    return 1.0 - v


def run_one(strat: CrossSectionalStrategy, data: DataBundle, label: str):
    print()
    print("=" * 80)
    print(f"  {label}")
    print("=" * 80)

    uni = Universe.broad(data, mcap_range=(30, 500), min_turnover_20d=0.15,
                          exclude_st=True, exclude_new_listing_days=180)

    bt = Backtest(
        strategy=strat,
        universe=uni,
        cost_model=CostModel.a_share_retail_quarterly(),  # 33bp round-trip, 180d 适用
        random_control=True,
        train_test_split=("2020-12-31", "2021-01-01"),
        year_start=2017, year_end=2025,
        seed=42,
    )
    result = bt.run(verbose=True)
    report = StandardReport.from_result(result)
    report.print()
    return result, report


def main():
    print("=" * 80)
    print("  52-Week High Momentum — foundation 严格验证")
    print("  研报: George & Hwang (2004), JF; 海通金工 2017 A 股复现 +5%/年")
    print("=" * 80)
    data = DataBundle.load(verbose=False)
    print(f"  数据加载完成 (OHLCV 覆盖 {data.audit.ohlcv_coverage_pct:.0f}%)")
    print(f"  样本期 2017-2024, train ≤ 2020, test ≥ 2021")

    # 1) 主信号: 靠近 52 周高点
    strat_high = CrossSectionalStrategy(
        name="52W-High Top20% (hold 180d)",
        factor_fn=factor_52w_high,
        top_pct=0.20,
        n_signal_cap=30,
        hold_days=180,
    )
    result_high, _ = run_one(strat_high, data, "信号组: 靠近 52 周高点")

    # 2) Sanity check: 反向因子. 如果主信号有真 alpha, 反向应该有相反符号
    strat_low = CrossSectionalStrategy(
        name="52W-LOW Top20% (远离高点, sanity)",
        factor_fn=factor_52w_low,
        top_pct=0.20,
        n_signal_cap=30,
        hold_days=180,
    )
    result_low, _ = run_one(strat_low, data, "对照组: 远离 52 周高点 (期望相反)")

    # 3) 总结
    print()
    print("=" * 80)
    print("  对比表 (Test 段 Alpha vs random)")
    print("=" * 80)
    print(f"{'策略':<35s} {'Train α':>10s} {'Train t':>8s} {'Test α':>10s} {'Test t':>8s}")
    print("-" * 75)
    for label, r in [("靠近 52w 高点 (主)", result_high),
                      ("远离 52w 高点 (对)", result_low)]:
        ta = r.train_summary.get("alpha_mean", np.nan)
        tt = r.train_summary.get("t_stat", np.nan)
        sa = r.test_summary.get("alpha_mean", np.nan)
        st = r.test_summary.get("t_stat", np.nan)
        ta_s = f"{ta*100:+.2f}%" if not pd.isna(ta) else "-"
        sa_s = f"{sa*100:+.2f}%" if not pd.isna(sa) else "-"
        tt_s = f"{tt:+.2f}" if not pd.isna(tt) else "-"
        st_s = f"{st:+.2f}" if not pd.isna(st) else "-"
        print(f"  {label:<32s} {ta_s:>10s} {tt_s:>8s} {sa_s:>10s} {st_s:>8s}")

    print()
    print("  解读:")
    print("    1. 主信号 Test t > 2 且 α > 1% → 入库候选")
    print("    2. 反向因子 α 符号应该相反, 否则因子整体无方向意义")
    print("    3. Train>>Test 是典型过拟合, 警惕")

    out_path = os.path.join(
        os.path.dirname(__file__), "..", "factors_v2", "output",
        "52w_high_foundation.md"
    )
    StandardReport.from_result(result_high).save(out_path)
    print(f"\n[+] 主信号报告: {out_path}")


if __name__ == "__main__":
    main()
