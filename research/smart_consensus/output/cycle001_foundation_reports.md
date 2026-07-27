# Cycle 001 Foundation Reports

## A1

# Backtest Report: A1 smart-cube avoidance (quarterly foundation variant; top 20% avoidable, hold=63d)

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 35
**OOS Split**: train ≤ 2021-12-31  /  test ≥ 2022-01-01

## Train 段
- 期数: 19
- 信号 gross 均值: +3.38%/期
- 信号 net 均值: +3.06%/期
- 信号胜率 (>0): 57.9%
- Random 对照 gross: +5.22%/期
- **Alpha vs random**: -1.84%/期
- **t-stat**: -0.99
- Alpha 胜率: 42%

## Test 段
- 期数: 16
- 信号 gross 均值: +7.43%/期
- 信号 net 均值: +7.10%/期
- 信号胜率 (>0): 81.2%
- Random 对照 gross: +4.92%/期
- **Alpha vs random**: +2.51%/期
- **t-stat**: 1.49
- Alpha 胜率: 50%

## Full 段
- 期数: 35
- 信号 gross 均值: +5.23%/期
- 信号 net 均值: +4.91%/期
- 信号胜率 (>0): 68.6%
- Random 对照 gross: +5.08%/期
- **Alpha vs random**: +0.15%/期
- **t-stat**: 0.12
- Alpha 胜率: 46%

## 判定
- - **不显著**: |t| < 2 或 net α 接近 0

## H2

# Backtest Report: H2 smart-cube cluster buy (min_cubes=3, window=7d, hold=5d)

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户波段: round-trip 0.73% (滑点 0.30+0.30, 佣金 2×0.013, 印花税 0.10)
**期数**: 129
**OOS Split**: train ≤ 2025-12-31  /  test ≥ 2026-03-01

## Train 段
- 期数: 71
- 信号 gross 均值: +4.88%/期
- 信号 net 均值: +4.15%/期
- 信号胜率 (>0): 62.0%
- Random 对照 gross: +2.18%/期
- **Alpha vs random**: +2.70%/期
- **t-stat**: 1.58
- Alpha 胜率: 56%

## Test 段
- 期数: 38
- 信号 gross 均值: -1.57%/期
- 信号 net 均值: -2.30%/期
- 信号胜率 (>0): 44.7%
- Random 对照 gross: +0.87%/期
- **Alpha vs random**: -2.44%/期
- **t-stat**: -1.40
- Alpha 胜率: 47%

## Full 段
- 期数: 109
- 信号 gross 均值: +2.63%/期
- 信号 net 均值: +1.90%/期
- 信号胜率 (>0): 56.0%
- Random 对照 gross: +1.73%/期
- **Alpha vs random**: +0.90%/期
- **t-stat**: 0.71
- Alpha 胜率: 53%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## H3

# Backtest Report: H3 smart-cube mass exit (min_cubes=3, window=7d, hold=5d)

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户波段: round-trip 0.73% (滑点 0.30+0.30, 佣金 2×0.013, 印花税 0.10)
**期数**: 122
**OOS Split**: train ≤ 2025-12-31  /  test ≥ 2026-03-01

## Train 段
- 期数: 74
- 信号 gross 均值: +3.26%/期
- 信号 net 均值: +2.53%/期
- 信号胜率 (>0): 59.5%
- Random 对照 gross: +2.08%/期
- **Alpha vs random**: +1.18%/期
- **t-stat**: 0.83
- Alpha 胜率: 57%

## Test 段
- 期数: 37
- 信号 gross 均值: +0.13%/期
- 信号 net 均值: -0.60%/期
- 信号胜率 (>0): 48.6%
- Random 对照 gross: +1.51%/期
- **Alpha vs random**: -1.37%/期
- **t-stat**: -0.79
- Alpha 胜率: 43%

## Full 段
- 期数: 111
- 信号 gross 均值: +2.22%/期
- 信号 net 均值: +1.49%/期
- 信号胜率 (>0): 55.9%
- Random 对照 gross: +1.89%/期
- **Alpha vs random**: +0.33%/期
- **t-stat**: 0.29
- Alpha 胜率: 52%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## H4

# Backtest Report: H4 skill-weighted buy intensity (quarterly; top 20%, hold=63d)

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 35
**OOS Split**: train ≤ 2021-12-31  /  test ≥ 2022-01-01

## Train 段
- 期数: 19
- 信号 gross 均值: +4.62%/期
- 信号 net 均值: +4.29%/期
- 信号胜率 (>0): 63.2%
- Random 对照 gross: +3.72%/期
- **Alpha vs random**: +0.90%/期
- **t-stat**: 0.52
- Alpha 胜率: 58%

## Test 段
- 期数: 16
- 信号 gross 均值: +3.43%/期
- 信号 net 均值: +3.10%/期
- 信号胜率 (>0): 50.0%
- Random 对照 gross: +7.06%/期
- **Alpha vs random**: -3.63%/期
- **t-stat**: -2.70
- Alpha 胜率: 25%

## Full 段
- 期数: 35
- 信号 gross 均值: +4.08%/期
- 信号 net 均值: +3.75%/期
- 信号胜率 (>0): 57.1%
- Random 对照 gross: +5.24%/期
- **Alpha vs random**: -1.17%/期
- **t-stat**: -0.99
- Alpha 胜率: 43%

## 判定
- ✗ **负 alpha**: 不可作系统策略
