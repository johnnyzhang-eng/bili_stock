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