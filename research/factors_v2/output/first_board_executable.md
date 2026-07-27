# 首板事件回测 — 严格可执行版 (H8)

替代 H1b (T 日 close 进场, 含 ex-post 信息).
全部用 T+1 open 进场, T+1 close 出场, cost=33bp.

## V1 铁板

# Backtest Report: V1 铁板

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 8492
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 2115
- 信号 gross 均值: -0.42%/期
- 信号 net 均值: -0.75%/期
- 信号胜率 (>0): 10.7%
- Random 对照 gross: +0.23%/期
- **Alpha vs random**: -0.75%/期
- **t-stat**: -6.78
- Alpha 胜率: 32%

## Test 段
- 期数: 6377
- 信号 gross 均值: -0.41%/期
- 信号 net 均值: -0.73%/期
- 信号胜率 (>0): 5.3%
- Random 对照 gross: +0.19%/期
- **Alpha vs random**: -0.59%/期
- **t-stat**: -10.67
- Alpha 胜率: 40%

## Full 段
- 期数: 8492
- 信号 gross 均值: -0.41%/期
- 信号 net 均值: -0.74%/期
- 信号胜率 (>0): 6.7%
- Random 对照 gross: +0.19%/期
- **Alpha vs random**: -0.63%/期
- **t-stat**: -12.61
- Alpha 胜率: 38%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## V2 烂板

# Backtest Report: V2 烂板

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 57003
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 16981
- 信号 gross 均值: +0.07%/期
- 信号 net 均值: -0.26%/期
- 信号胜率 (>0): 48.0%
- Random 对照 gross: +0.01%/期
- **Alpha vs random**: +0.06%/期
- **t-stat**: 1.36
- Alpha 胜率: 49%

## Test 段
- 期数: 40022
- 信号 gross 均值: -0.26%/期
- 信号 net 均值: -0.59%/期
- 信号胜率 (>0): 43.5%
- Random 对照 gross: -0.06%/期
- **Alpha vs random**: -0.20%/期
- **t-stat**: -7.83
- Alpha 胜率: 47%

## Full 段
- 期数: 57003
- 信号 gross 均值: -0.16%/期
- 信号 net 均值: -0.49%/期
- 信号胜率 (>0): 44.9%
- Random 对照 gross: -0.04%/期
- **Alpha vs random**: -0.13%/期
- **t-stat**: -5.66
- Alpha 胜率: 48%

## 判定
- ✗ **负 alpha**: 不可作系统策略

## V3 0-5%追板

# Backtest Report: V3 0-5%追板

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 54288
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15876
- 信号 gross 均值: +0.22%/期
- 信号 net 均值: -0.10%/期
- 信号胜率 (>0): 46.6%
- Random 对照 gross: +0.11%/期
- **Alpha vs random**: +0.11%/期
- **t-stat**: 2.45
- Alpha 胜率: 48%

## Test 段
- 期数: 38412
- 信号 gross 均值: +0.03%/期
- 信号 net 均值: -0.30%/期
- 信号胜率 (>0): 40.5%
- Random 对照 gross: +0.02%/期
- **Alpha vs random**: +0.01%/期
- **t-stat**: 0.29
- Alpha 胜率: 47%

## Full 段
- 期数: 54288
- 信号 gross 均值: +0.08%/期
- 信号 net 均值: -0.24%/期
- 信号胜率 (>0): 42.3%
- Random 对照 gross: +0.05%/期
- **Alpha vs random**: +0.04%/期
- **t-stat**: 1.69
- Alpha 胜率: 47%

## 判定
- - **不显著**: |t| < 2 或 net α 接近 0

