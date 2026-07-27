# Backtest Report: 52W-High Top20% (hold 180d)

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15
- 信号 gross 均值: +8.33%/期
- 信号 net 均值: +8.01%/期
- 信号胜率 (>0): 80.0%
- Random 对照 gross: +5.71%/期
- **Alpha vs random**: +2.63%/期
- **t-stat**: 0.78
- Alpha 胜率: 53%

## Test 段
- 期数: 17
- 信号 gross 均值: +6.34%/期
- 信号 net 均值: +6.01%/期
- 信号胜率 (>0): 58.8%
- Random 对照 gross: +10.86%/期
- **Alpha vs random**: -4.52%/期
- **t-stat**: -0.86
- Alpha 胜率: 24%

## Full 段
- 期数: 32
- 信号 gross 均值: +7.27%/期
- 信号 net 均值: +6.95%/期
- 信号胜率 (>0): 68.8%
- Random 对照 gross: +8.44%/期
- **Alpha vs random**: -1.17%/期
- **t-stat**: -0.36
- Alpha 胜率: 38%

## 判定
- ✗ **负 alpha**: 不可作系统策略