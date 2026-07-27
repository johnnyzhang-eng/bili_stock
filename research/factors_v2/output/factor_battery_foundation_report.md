# 12-factor Battery — Foundation Rerun (2026-05-25)

Execution: `.venv/bin/python -B research/foundation/run_factor_battery_foundation.py`.

Rules: DataBundle audit, broad 30-500亿 universe, 180d hold, quarterly retail cost, random_control=True, OOS split 2021-01-01.

## Summary

| factor | n | train alpha | train t | test alpha | test t | full alpha | full t | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 小盘 SMB | 32 | -6.25% | -2.95 | +6.44% | +2.31 | +0.49% | +0.24 | WEAK_POSITIVE |
| 短期反转 1M | 32 | -5.10% | -2.63 | +1.15% | +0.42 | -1.78% | -0.99 | REJECT_NOT_SIGNIFICANT |
| 基本面反转 | 29 | -0.69% | -0.37 | +1.02% | +0.37 | +0.25% | +0.14 | REJECT_NOT_SIGNIFICANT |
| 对照 大盘 | 32 | -0.84% | -0.29 | +0.32% | +0.19 | -0.22% | -0.14 | REJECT_NOT_SIGNIFICANT |
| 价值 BM ratio | 32 | +1.33% | +0.36 | -0.91% | -0.24 | +0.14% | +0.05 | REJECT_NEGATIVE |
| 多因子合成 | 32 | -1.05% | -0.50 | -1.64% | -0.51 | -1.37% | -0.70 | REJECT_NEGATIVE |
| 低 PE | 32 | +0.64% | +0.21 | -3.06% | -0.72 | -1.32% | -0.50 | REJECT_NEGATIVE |
| 动量 12-1M | 32 | +2.89% | +1.56 | -2.58% | -0.78 | -0.02% | -0.01 | REJECT_NEGATIVE |
| 低换手 20d | 32 | +4.29% | +1.52 | -2.94% | -1.40 | +0.45% | +0.25 | REJECT_NEGATIVE |
| 对照 高换手 | 32 | -10.16% | -3.94 | -4.91% | -1.88 | -7.37% | -3.94 | REJECT_NEGATIVE |
| 质量 ROE | 32 | +1.39% | +0.72 | -6.04% | -2.07 | -2.56% | -1.36 | REJECT_NEGATIVE |
| 低波动 60d | 32 | -4.75% | -2.09 | -6.74% | -2.15 | -5.81% | -2.97 | REJECT_NEGATIVE |

## 动量 12-1M

# Backtest Report: FactorBattery::动量 12-1M

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +7.85%/期
- 信号 net 均值: +7.52%/期
- 信号胜率 (>0): 80.0%
- Random 对照 gross: +4.95%/期
- **Alpha vs random**: +2.89%/期
- **t-stat**: 1.56
- Alpha 胜率: 60%

## Test 段
- 期数: 17
- 信号 gross 均值: +10.52%/期
- 信号 net 均值: +10.19%/期
- 信号胜率 (>0): 70.6%
- Random 对照 gross: +13.10%/期
- **Alpha vs random**: -2.58%/期
- **t-stat**: -0.78
- Alpha 胜率: 47%

## Full 段
- 期数: 32
- 信号 gross 均值: +9.27%/期
- 信号 net 均值: +8.94%/期
- 信号胜率 (>0): 75.0%
- Random 对照 gross: +9.28%/期
- **Alpha vs random**: -0.02%/期
- **t-stat**: -0.01
- Alpha 胜率: 53%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 短期反转 1M

# Backtest Report: FactorBattery::短期反转 1M

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +0.76%/期
- 信号 net 均值: +0.44%/期
- 信号胜率 (>0): 40.0%
- Random 对照 gross: +5.87%/期
- **Alpha vs random**: -5.10%/期
- **t-stat**: -2.63
- Alpha 胜率: 27%

## Test 段
- 期数: 17
- 信号 gross 均值: +12.00%/期
- 信号 net 均值: +11.68%/期
- 信号胜率 (>0): 70.6%
- Random 对照 gross: +10.85%/期
- **Alpha vs random**: +1.15%/期
- **t-stat**: 0.42
- Alpha 胜率: 65%

## Full 段
- 期数: 32
- 信号 gross 均值: +6.74%/期
- 信号 net 均值: +6.41%/期
- 信号胜率 (>0): 56.2%
- Random 对照 gross: +8.52%/期
- **Alpha vs random**: -1.78%/期
- **t-stat**: -0.99
- Alpha 胜率: 47%

## 判定
- - **不显著**: |t| < 2 或 net α 接近 0

## 低波动 60d

# Backtest Report: FactorBattery::低波动 60d

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +1.29%/期
- 信号 net 均值: +0.96%/期
- 信号胜率 (>0): 73.3%
- Random 对照 gross: +6.03%/期
- **Alpha vs random**: -4.75%/期
- **t-stat**: -2.09
- Alpha 胜率: 27%

## Test 段
- 期数: 17
- 信号 gross 均值: +5.96%/期
- 信号 net 均值: +5.63%/期
- 信号胜率 (>0): 76.5%
- Random 对照 gross: +12.70%/期
- **Alpha vs random**: -6.74%/期
- **t-stat**: -2.15
- Alpha 胜率: 35%

## Full 段
- 期数: 32
- 信号 gross 均值: +3.77%/期
- 信号 net 均值: +3.44%/期
- 信号胜率 (>0): 75.0%
- Random 对照 gross: +9.58%/期
- **Alpha vs random**: -5.81%/期
- **t-stat**: -2.97
- Alpha 胜率: 31%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 低换手 20d

# Backtest Report: FactorBattery::低换手 20d

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +7.45%/期
- 信号 net 均值: +7.12%/期
- 信号胜率 (>0): 66.7%
- Random 对照 gross: +3.15%/期
- **Alpha vs random**: +4.29%/期
- **t-stat**: 1.52
- Alpha 胜率: 60%

## Test 段
- 期数: 17
- 信号 gross 均值: +7.12%/期
- 信号 net 均值: +6.79%/期
- 信号胜率 (>0): 76.5%
- Random 对照 gross: +10.06%/期
- **Alpha vs random**: -2.94%/期
- **t-stat**: -1.40
- Alpha 胜率: 47%

## Full 段
- 期数: 32
- 信号 gross 均值: +7.27%/期
- 信号 net 均值: +6.95%/期
- 信号胜率 (>0): 71.9%
- Random 对照 gross: +6.82%/期
- **Alpha vs random**: +0.45%/期
- **t-stat**: 0.25
- Alpha 胜率: 53%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 价值 BM ratio

# Backtest Report: FactorBattery::价值 BM ratio

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +6.21%/期
- 信号 net 均值: +5.89%/期
- 信号胜率 (>0): 53.3%
- Random 对照 gross: +4.88%/期
- **Alpha vs random**: +1.33%/期
- **t-stat**: 0.36
- Alpha 胜率: 40%

## Test 段
- 期数: 17
- 信号 gross 均值: +9.11%/期
- 信号 net 均值: +8.78%/期
- 信号胜率 (>0): 70.6%
- Random 对照 gross: +10.02%/期
- **Alpha vs random**: -0.91%/期
- **t-stat**: -0.24
- Alpha 胜率: 47%

## Full 段
- 期数: 32
- 信号 gross 均值: +7.75%/期
- 信号 net 均值: +7.43%/期
- 信号胜率 (>0): 62.5%
- Random 对照 gross: +7.61%/期
- **Alpha vs random**: +0.14%/期
- **t-stat**: 0.05
- Alpha 胜率: 44%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 低 PE

# Backtest Report: FactorBattery::低 PE

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +7.33%/期
- 信号 net 均值: +7.01%/期
- 信号胜率 (>0): 60.0%
- Random 对照 gross: +6.69%/期
- **Alpha vs random**: +0.64%/期
- **t-stat**: 0.21
- Alpha 胜率: 60%

## Test 段
- 期数: 17
- 信号 gross 均值: +6.37%/期
- 信号 net 均值: +6.04%/期
- 信号胜率 (>0): 58.8%
- Random 对照 gross: +9.42%/期
- **Alpha vs random**: -3.06%/期
- **t-stat**: -0.72
- Alpha 胜率: 35%

## Full 段
- 期数: 32
- 信号 gross 均值: +6.82%/期
- 信号 net 均值: +6.49%/期
- 信号胜率 (>0): 59.4%
- Random 对照 gross: +8.14%/期
- **Alpha vs random**: -1.32%/期
- **t-stat**: -0.50
- Alpha 胜率: 47%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 质量 ROE

# Backtest Report: FactorBattery::质量 ROE

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +6.50%/期
- 信号 net 均值: +6.17%/期
- 信号胜率 (>0): 73.3%
- Random 对照 gross: +5.11%/期
- **Alpha vs random**: +1.39%/期
- **t-stat**: 0.72
- Alpha 胜率: 47%

## Test 段
- 期数: 17
- 信号 gross 均值: +7.01%/期
- 信号 net 均值: +6.69%/期
- 信号胜率 (>0): 64.7%
- Random 对照 gross: +13.05%/期
- **Alpha vs random**: -6.04%/期
- **t-stat**: -2.07
- Alpha 胜率: 24%

## Full 段
- 期数: 32
- 信号 gross 均值: +6.77%/期
- 信号 net 均值: +6.44%/期
- 信号胜率 (>0): 68.8%
- Random 对照 gross: +9.33%/期
- **Alpha vs random**: -2.56%/期
- **t-stat**: -1.36
- Alpha 胜率: 34%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 小盘 SMB

# Backtest Report: FactorBattery::小盘 SMB

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: -0.21%/期
- 信号 net 均值: -0.54%/期
- 信号胜率 (>0): 53.3%
- Random 对照 gross: +6.04%/期
- **Alpha vs random**: -6.25%/期
- **t-stat**: -2.95
- Alpha 胜率: 33%

## Test 段
- 期数: 17
- 信号 gross 均值: +16.86%/期
- 信号 net 均值: +16.54%/期
- 信号胜率 (>0): 82.4%
- Random 对照 gross: +10.42%/期
- **Alpha vs random**: +6.44%/期
- **t-stat**: 2.31
- Alpha 胜率: 82%

## Full 段
- 期数: 32
- 信号 gross 均值: +8.86%/期
- 信号 net 均值: +8.53%/期
- 信号胜率 (>0): 68.8%
- Random 对照 gross: +8.37%/期
- **Alpha vs random**: +0.49%/期
- **t-stat**: 0.24
- Alpha 胜率: 59%

## 判定
- ~ **弱信号**: 2 < |t| < 3.5, 经济意义存在但需谨慎

## 基本面反转

# Backtest Report: FactorBattery::基本面反转

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 29
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 13
- 信号 gross 均值: +7.73%/期
- 信号 net 均值: +7.40%/期
- 信号胜率 (>0): 69.2%
- Random 对照 gross: +8.42%/期
- **Alpha vs random**: -0.69%/期
- **t-stat**: -0.37
- Alpha 胜率: 46%

## Test 段
- 期数: 16
- 信号 gross 均值: +9.41%/期
- 信号 net 均值: +9.08%/期
- 信号胜率 (>0): 50.0%
- Random 对照 gross: +8.39%/期
- **Alpha vs random**: +1.02%/期
- **t-stat**: 0.37
- Alpha 胜率: 56%

## Full 段
- 期数: 29
- 信号 gross 均值: +8.66%/期
- 信号 net 均值: +8.33%/期
- 信号胜率 (>0): 58.6%
- Random 对照 gross: +8.41%/期
- **Alpha vs random**: +0.25%/期
- **t-stat**: 0.14
- Alpha 胜率: 52%

## 判定
- - **不显著**: |t| < 2 或 net α 接近 0

## 多因子合成

# Backtest Report: FactorBattery::多因子合成

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +5.65%/期
- 信号 net 均值: +5.33%/期
- 信号胜率 (>0): 80.0%
- Random 对照 gross: +6.71%/期
- **Alpha vs random**: -1.05%/期
- **t-stat**: -0.50
- Alpha 胜率: 53%

## Test 段
- 期数: 17
- 信号 gross 均值: +9.13%/期
- 信号 net 均值: +8.80%/期
- 信号胜率 (>0): 70.6%
- Random 对照 gross: +10.77%/期
- **Alpha vs random**: -1.64%/期
- **t-stat**: -0.51
- Alpha 胜率: 41%

## Full 段
- 期数: 32
- 信号 gross 均值: +7.50%/期
- 信号 net 均值: +7.18%/期
- 信号胜率 (>0): 75.0%
- Random 对照 gross: +8.87%/期
- **Alpha vs random**: -1.37%/期
- **t-stat**: -0.70
- Alpha 胜率: 47%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 对照 高换手

# Backtest Report: FactorBattery::对照 高换手

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: -3.71%/期
- 信号 net 均值: -4.04%/期
- 信号胜率 (>0): 46.7%
- Random 对照 gross: +6.45%/期
- **Alpha vs random**: -10.16%/期
- **t-stat**: -3.94
- Alpha 胜率: 7%

## Test 段
- 期数: 17
- 信号 gross 均值: +6.58%/期
- 信号 net 均值: +6.25%/期
- 信号胜率 (>0): 52.9%
- Random 对照 gross: +11.49%/期
- **Alpha vs random**: -4.91%/期
- **t-stat**: -1.88
- Alpha 胜率: 29%

## Full 段
- 期数: 32
- 信号 gross 均值: +1.75%/期
- 信号 net 均值: +1.43%/期
- 信号胜率 (>0): 50.0%
- Random 对照 gross: +9.12%/期
- **Alpha vs random**: -7.37%/期
- **t-stat**: -3.94
- Alpha 胜率: 19%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## 对照 大盘

# Backtest Report: FactorBattery::对照 大盘

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +5.47%/期
- 信号 net 均值: +5.14%/期
- 信号胜率 (>0): 73.3%
- Random 对照 gross: +6.30%/期
- **Alpha vs random**: -0.84%/期
- **t-stat**: -0.29
- Alpha 胜率: 40%

## Test 段
- 期数: 17
- 信号 gross 均值: +10.12%/期
- 信号 net 均值: +9.80%/期
- 信号胜率 (>0): 70.6%
- Random 对照 gross: +9.80%/期
- **Alpha vs random**: +0.32%/期
- **t-stat**: 0.19
- Alpha 胜率: 53%

## Full 段
- 期数: 32
- 信号 gross 均值: +7.94%/期
- 信号 net 均值: +7.62%/期
- 信号胜率 (>0): 71.9%
- Random 对照 gross: +8.16%/期
- **Alpha vs random**: -0.22%/期
- **t-stat**: -0.14
- Alpha 胜率: 47%

## 判定
- - **不显著**: |t| < 2 或 net α 接近 0
