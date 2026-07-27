"""
低波 baseline 在 foundation 下重新验证
==========================================================
**结论 (2026-04-27 二轮): 低波因子在 A 股 broad 30-500亿宇宙下不构成系统 alpha.**

低波因子定义 (CLAUDE.md 中描述):
  - 60 日收益标准差, 取最低 (波动率倒数 → 低波得分高)
  - 入选: 顶 80th 百分位 (top 20%)
  - hold_step: 12 个交易日 ≈ 17 自然日

CLAUDE.md 旧报告: CAGR 13.17% / 14.65% (含 overlay) / MDD -64% / -56% / Calmar 0.86

二轮验证 (2026-04-27, hold_days=17 严格对齐 + B1-B4 引擎修复 + n_random_repeats=1):
  Train 段 (2017-2018, 7期): alpha +1.13%/期, t=+1.79  ← 边缘正显著, 看似有信号
  Test  段 (2019-2024, 25期): alpha -0.75%/期, t=-0.71  ← OOS 反转为负不显著
  Full  段 (32期):           alpha -0.34%/期, t=-0.40  ← 整体零 alpha

  → 典型过拟合特征 (Train 显著, Test 反转). 低波因子在 A 股小盘 boom 期 (如 2024Q2,
  signal +27% α=-21%) 严重吃亏. 不可作系统性策略.

**CLAUDE.md 13.17% CAGR 来源诊断**:
  - 基准错配 (HS300 vs 小盘宇宙): 自动 +5pp
  - 无 random control: 把 universe beta 误算成 alpha
  - 可能 in-sample 优化: train 段确实正显著, 单独看会得 +23.7%/年
  → 综合虚高 10-15pp, 真实表现 ≈ -3.4%/年 net

**对应 memory**:
  - foundation_status.md: 第二轮已验, OOS 仍失败
  - feedback_alpha_fake_pattern.md: 又一例 "看似 13% 实际 0~负"
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


def factor_low_vol(row, price_cache, sig_date):
    """低波因子: -60日收益std (越大越好 = 越低波越好)"""
    code = row["code"]
    if code not in price_cache: return np.nan
    pf = price_cache[code]
    sub = pf[pf["date"] <= sig_date].tail(61)
    if len(sub) < 40: return np.nan
    vol = sub["close"].pct_change().std()
    if pd.isna(vol) or vol == 0: return np.nan
    return -float(vol)  # 取负: 低波 → 因子大 → 被选中


def main():
    print("=" * 80)
    print("  低波 baseline — foundation 严格验证")
    print("=" * 80)
    print("  CLAUDE.md 声称: CAGR 13.17% (无 overlay), Calmar 0.86")
    print("  本次验证: 加 random control + OOS 拆分, 看真 alpha")
    print()

    data = DataBundle.load(verbose=False)
    print(f"  数据加载完成 ({data.audit.ohlcv_coverage_pct:.0f}% OHLCV 覆盖)")
    print()

    # CLAUDE.md 中: 用 top 1000 流动性股 (broad), 实际是中小盘
    # 我们用 broad universe 30-200亿对应 top 流动性中小盘
    uni = Universe.broad(data, mcap_range=(30, 500), min_turnover_20d=0.15,
                          exclude_st=True, exclude_new_listing_days=180)

    strat = CrossSectionalStrategy(
        name="低波 17d (top 20%, hold_step=12 交易日)",
        factor_fn=factor_low_vol,
        top_pct=0.20,           # CLAUDE.md: enter_q=0.80 → top 20%
        n_signal_cap=30,        # 实际可投 30 只
        hold_days=17,           # 17 自然日 ≈ 12 交易日, 对齐 CLAUDE.md hold_step=12
    )

    # 成本: 高换手意味着每年 ~21 次再平衡, swing 比 quarterly 更合适
    # quarterly round-trip 33bp; swing round-trip 63bp.
    # 但 foundation 每"期"独立扣 round-trip, 所以用 swing 更接近 17 日单次往返实况.
    cost = CostModel.a_share_retail_swing()

    bt = Backtest(
        strategy=strat,
        universe=uni,
        cost_model=cost,
        random_control=True,                                  # 强制对照
        train_test_split=("2018-12-31", "2019-01-01"),       # OOS 拆分
        # n_random_repeats=1 (默认, B2 修后): 单次抽样, t-stat 真实
        year_start=2017, year_end=2025,
        seed=42,
    )
    result = bt.run(verbose=True)

    # 标准报告
    report = StandardReport.from_result(result)
    report.print()

    # 年化粗算 (per-period × 一年中的连续 12-交易日窗口数)
    print()
    print("─" * 80)
    print("  年化粗算 (假设每 12 交易日连续重新建仓):")
    periods_per_year = 252 / 12
    for label, summary in [("Train", result.train_summary),
                             ("Test",  result.test_summary),
                             ("Full",  result.full_summary)]:
        if not summary or "alpha_mean" not in summary: continue
        gross_p = summary["signal_mean_gross"]
        net_p   = summary["signal_mean_net"]
        alpha_p = summary["alpha_mean"]
        print(f"  {label:<6s}: gross {gross_p*periods_per_year*100:+5.1f}%/年   "
              f"net {net_p*periods_per_year*100:+5.1f}%/年   "
              f"alpha {alpha_p*periods_per_year*100:+5.1f}%/年   "
              f"t-stat {summary.get('t_stat', float('nan')):+.2f}")

    out_path = os.path.join(
        os.path.dirname(__file__), "..", "factors_v2", "output",
        "low_vol_foundation_validation.md"
    )
    report.save(out_path)
    print(f"\n[+] 报告写入 {out_path}")


if __name__ == "__main__":
    main()
