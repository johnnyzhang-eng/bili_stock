# H9 教学规则全叠加版 (2026-04-28)

Base = H8 V2 烂板 (盘中跌破涨停再封, T+1 open 进场).
叠加教学视频 5 条 TIER 1 规则: 量能/小盘低价/近期人气/次日高开.

## 总览

| 变体 | n | sig% | rand% | alpha% | t | win% | 净% |
|---|---:|---:|---:|---:|---:|---:|---:|
| base 烂板 | 69,058 | -0.11 | +0.02 | -0.13 | -6.97 | 45.5 | -0.44 |
| +A 量能2x | 32,806 | +0.01 | +0.06 | -0.05 | -1.78 | 45.4 | -0.32 |
| +B 小盘低价 | 20,524 | -0.27 | +0.06 | -0.33 | -9.08 | 43.0 | -0.59 |
| +C 历史涨停40d | 43,556 | -0.06 | +0.11 | -0.17 | -6.61 | 46.7 | -0.39 |
| +D 次日高开4% | 13,953 | -1.18 | +0.20 | -1.38 | -30.72 | 36.7 | -1.51 |
| ALL 全叠加 | 765 | -1.19 | +0.28 | -1.47 | -7.25 | 37.0 | -1.51 |

## 详情

### base 烂板

# Backtest Report: base 烂板

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 69058
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 32637
- 信号 gross 均值: +0.05%/期
- 信号 net 均值: -0.28%/期
- 信号胜率 (>0): 47.6%
- Random 对照 gross: +0.09%/期
- **Alpha vs random**: -0.04%/期
- **t-stat**: -1.44
- Alpha 胜率: 48%

## Test 段
- 期数: 36421
- 信号 gross 均值: -0.26%/期
- 信号 net 均值: -0.58%/期
- 信号胜率 (>0): 43.5%
- Random 对照 gross: -0.04%/期
- **Alpha vs random**: -0.22%/期
- **t-stat**: -8.27
- Alpha 胜率: 46%

## Full 段
- 期数: 69058
- 信号 gross 均值: -0.11%/期
- 信号 net 均值: -0.44%/期
- 信号胜率 (>0): 45.5%
- Random 对照 gross: +0.02%/期
- **Alpha vs random**: -0.13%/期
- **t-stat**: -6.97
- Alpha 胜率: 47%

## 判定
- ✗ **负 alpha**: 不可作系统策略

### +A 量能2x

# Backtest Report: +A 量能2x

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 32806
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 15461
- 信号 gross 均值: +0.18%/期
- 信号 net 均值: -0.14%/期
- 信号胜率 (>0): 48.3%
- Random 对照 gross: +0.09%/期
- **Alpha vs random**: +0.09%/期
- **t-stat**: 2.31
- Alpha 胜率: 49%

## Test 段
- 期数: 17345
- 信号 gross 均值: -0.15%/期
- 信号 net 均值: -0.47%/期
- 信号胜率 (>0): 42.8%
- Random 对照 gross: +0.02%/期
- **Alpha vs random**: -0.17%/期
- **t-stat**: -4.60
- Alpha 胜率: 46%

## Full 段
- 期数: 32806
- 信号 gross 均值: +0.01%/期
- 信号 net 均值: -0.32%/期
- 信号胜率 (>0): 45.4%
- Random 对照 gross: +0.06%/期
- **Alpha vs random**: -0.05%/期
- **t-stat**: -1.78
- Alpha 胜率: 47%

## 判定
- ✗ **负 alpha**: 不可作系统策略

### +B 小盘低价

# Backtest Report: +B 小盘低价

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 20524
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 8285
- 信号 gross 均值: +0.06%/期
- 信号 net 均值: -0.26%/期
- 信号胜率 (>0): 47.2%
- Random 对照 gross: +0.17%/期
- **Alpha vs random**: -0.10%/期
- **t-stat**: -1.81
- Alpha 胜率: 47%

## Test 段
- 期数: 12239
- 信号 gross 均值: -0.49%/期
- 信号 net 均值: -0.82%/期
- 信号胜率 (>0): 40.1%
- Random 对照 gross: -0.01%/期
- **Alpha vs random**: -0.48%/期
- **t-stat**: -10.25
- Alpha 胜率: 44%

## Full 段
- 期数: 20524
- 信号 gross 均值: -0.27%/期
- 信号 net 均值: -0.59%/期
- 信号胜率 (>0): 43.0%
- Random 对照 gross: +0.06%/期
- **Alpha vs random**: -0.33%/期
- **t-stat**: -9.08
- Alpha 胜率: 45%

## 判定
- ✗ **负 alpha**: 不可作系统策略

### +C 历史涨停40d

# Backtest Report: +C 历史涨停40d

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 43556
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 20955
- 信号 gross 均值: +0.12%/期
- 信号 net 均值: -0.20%/期
- 信号胜率 (>0): 48.8%
- Random 对照 gross: +0.15%/期
- **Alpha vs random**: -0.03%/期
- **t-stat**: -0.71
- Alpha 胜率: 49%

## Test 段
- 期数: 22601
- 信号 gross 均值: -0.23%/期
- 信号 net 均值: -0.55%/期
- 信号胜率 (>0): 44.8%
- Random 对照 gross: +0.07%/期
- **Alpha vs random**: -0.30%/期
- **t-stat**: -8.60
- Alpha 胜率: 46%

## Full 段
- 期数: 43556
- 信号 gross 均值: -0.06%/期
- 信号 net 均值: -0.39%/期
- 信号胜率 (>0): 46.7%
- Random 对照 gross: +0.11%/期
- **Alpha vs random**: -0.17%/期
- **t-stat**: -6.61
- Alpha 胜率: 47%

## 判定
- ✗ **负 alpha**: 不可作系统策略

### +D 次日高开4%

# Backtest Report: +D 次日高开4%

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 13953
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 6150
- 信号 gross 均值: -0.76%/期
- 信号 net 均值: -1.09%/期
- 信号胜率 (>0): 42.1%
- Random 对照 gross: +0.31%/期
- **Alpha vs random**: -1.08%/期
- **t-stat**: -15.83
- Alpha 胜率: 44%

## Test 段
- 期数: 7803
- 信号 gross 均值: -1.51%/期
- 信号 net 均值: -1.84%/期
- 信号胜率 (>0): 32.4%
- Random 对照 gross: +0.11%/期
- **Alpha vs random**: -1.62%/期
- **t-stat**: -27.12
- Alpha 胜率: 40%

## Full 段
- 期数: 13953
- 信号 gross 均值: -1.18%/期
- 信号 net 均值: -1.51%/期
- 信号胜率 (>0): 36.7%
- Random 对照 gross: +0.20%/期
- **Alpha vs random**: -1.38%/期
- **t-stat**: -30.72
- Alpha 胜率: 42%

## 判定
- ✗ **负 alpha**: 不可作系统策略

### ALL 全叠加

# Backtest Report: ALL 全叠加

**宇宙**: Universe(size_tier=broad, mcap=5-100000亿, min_turn=0.00%)
**成本**: A股散户季度: round-trip 0.33% (滑点 0.10+0.10, 佣金 2×0.013, 印花税 0.10)
**期数**: 765
**OOS Split**: train ≤ 2020-12-31  /  test ≥ 2021-01-01

## Train 段
- 期数: 264
- 信号 gross 均值: -0.82%/期
- 信号 net 均值: -1.14%/期
- 信号胜率 (>0): 46.2%
- Random 对照 gross: +0.30%/期
- **Alpha vs random**: -1.11%/期
- **t-stat**: -3.26
- Alpha 胜率: 47%

## Test 段
- 期数: 501
- 信号 gross 均值: -1.38%/期
- 信号 net 均值: -1.70%/期
- 信号胜率 (>0): 32.1%
- Random 对照 gross: +0.28%/期
- **Alpha vs random**: -1.65%/期
- **t-stat**: -6.60
- Alpha 胜率: 40%

## Full 段
- 期数: 765
- 信号 gross 均值: -1.19%/期
- 信号 net 均值: -1.51%/期
- 信号胜率 (>0): 37.0%
- Random 对照 gross: +0.28%/期
- **Alpha vs random**: -1.47%/期
- **t-stat**: -7.25
- Alpha 胜率: 42%

## 判定
- ✗ **负 alpha**: 不可作系统策略

