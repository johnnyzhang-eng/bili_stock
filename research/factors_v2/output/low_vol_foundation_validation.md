# Backtest Report: 低波 17d (top 20%, hold_step=12 交易日)

**宇宙**: Universe(size_tier=broad, mcap=30-500亿, min_turn=0.15%)
**成本**: A股散户波段: round-trip 0.73% (滑点 0.30+0.30, 佣金 2×0.013, 印花税 0.10)
**期数**: 32
**OOS Split**: train ≤ 2018-12-31  /  test ≥ 2019-01-01

## Train 段
- 期数: 7
- 信号 gross 均值: -1.86%/期
- 信号 net 均值: -2.58%/期
- 信号胜率 (>0): 0.0%
- Random 对照 gross: -2.27%/期
- **Alpha vs random**: +0.41%/期
- **t-stat**: 0.71
- Alpha 胜率: 57%

## Test 段
- 期数: 25
- 信号 gross 均值: +1.01%/期
- 信号 net 均值: +0.28%/期
- 信号胜率 (>0): 52.0%
- Random 对照 gross: +1.53%/期
- **Alpha vs random**: -0.52%/期
- **t-stat**: -0.77
- Alpha 胜率: 48%

## Full 段
- 期数: 32
- 信号 gross 均值: +0.38%/期
- 信号 net 均值: -0.35%/期
- 信号胜率 (>0): 40.6%
- Random 对照 gross: +0.70%/期
- **Alpha vs random**: -0.32%/期
- **t-stat**: -0.59
- Alpha 胜率: 50%

## 判定
- ✗ **负 alpha**: 不可作系统策略