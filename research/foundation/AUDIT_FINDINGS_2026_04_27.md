# Foundation 地基审计报告 — 2026-04-27

**审计目标**: 在用 foundation 跑新策略 (一进二/龙头) 之前, 确保引擎数学正确、数据齐全、回测方法正确.

---

## 引擎 Bug (已修)

| ID | 问题 | 影响 | 修复 |
|----|------|------|------|
| **B1** | EventDriven `exit_idx = idx + t_off + hold_days` 多算 1 天 | 所有 event-driven 持仓 +1 日; legacy `limit_up_strategies.py` 结果对不上 | `exit_idx = idx + hold_days`, 与 legacy 统一. 两条入场路径 (`today_close` / `next_open`) 都退出在 `idx + hold_days` 的 close. |
| **B2** | `n_random_repeats=30` 抹掉 random 噪音, 抬高 t-stat | 所有历史 t-stat 偏大 (含低波 -1.78) | 默认 `n_random_repeats=1`, alpha 自带 random 噪音. 想做稳健性检查请用不同 seed 跑多次完整 backtest. |
| **B3** | event random baseline 在整个时间段抽 candidates | 牛市信号 vs 熊市 random → alpha 被市场环境差异夸大 | candidates 限制在 `current_idx ± 90 交易日` (`same_regime_window`). |
| **B4** | cross_sectional random 没排除 signal picks | random 与 signal 重叠, 严格性问题 | `pool = universe_df[~code.isin(picks)]` 后再抽. |
| 防御 | `alpha_std` 在 `n < 2` 或 `std == 0` 时 NaN/除零 | 报告崩 | 加保护: `t_stat = nan` if `se == 0`. |

---

## 数据层结构性偏差 (引擎不能修, 项目级)

### 退市股严重缺失 (生存者偏差)

| 检查 | 结果 |
|------|------|
| Panel 时间: 2015-Q1 → 2026-Q1, 11,777 unique 股 | ✓ |
| Panel 中 `last_rpt < 2024-06-30` (退市候选): | **6 只** |
| 6 只退市候选有 OHLCV: | **0 / 6 = 0%** |

**预期值**: 真实 A 股 2015-2024 退市约 150 只 (含强制退市 + 主动退市). Panel 只剩 6 → **数据源在采集时已按当前活股清单查询, 历史退市股从未进入 panel**.

**影响**: Universe.at() 永远不可能选到"将要退市"的股 → 系统性高估 alpha, 经验级 1-3%/年.

### ST 历史抹除 (轻偏差)

| 检查 | 结果 |
|------|------|
| 每股 unique 名字数 | 1 (panel 中 name 不随时间变化) |
| panel 任一 quarter 含 ST 名 | 349 |
| panel 最新 name 含 ST | 349 |
| 曾 ST 但已摘帽 | **0** |

**含义**: name 是当前快照. 一只股 2017 是 *ST、2020 摘帽, panel 中 name 永远是当前 (无 ST). `universe.at()` 用 `name.contains("ST")` 排除 → 漏掉历史 ST 期, 把 ST 期间的负 alpha 算进策略. 这是**保守方向**的偏差 (低估 alpha).

### 净效应

退市偏差 (高估) >> ST 偏差 (低估). 综合 **alpha 系统性高估约 1-3%/年**.

**所有 foundation 跑出的正 alpha 必须按 1-3%/年贴现后再判定**:
- 真 alpha < 1%/年 → 数据偏差就够解释
- 真 alpha 5-10%/年 → 仍需怀疑 (历史教训)
- 真 alpha > 15%/年 → 几乎确定有别的 bug

### 短期对策 (不能立刻修)

1. ✅ 此报告写入 audit log, 后续 backtest 自动引用
2. ⏳ CLAUDE.md 添加"已知数据局限"段
3. ⏳ 长期任务: 补全退市股 OHLCV (baostock 是否提供历史退市股? 需研究)

---

## Self_test 扩展

| 段 | 测试 | 期望 | 通过线 |
|---|------|------|--------|
| A1 | NULL (恒 0) | alpha ≈ 0 | \|t\| < 2 |
| A2 | RANDOM (每期重抽) | alpha ≈ 0 | \|t\| < 2 |
| A3 | 高换手 (反向) | alpha 强负 | t < -2 (项目历史 -5.37) |
| A4 | 前视 (作弊) | alpha 强正 | t > 3 |
| **B1** (新) | EventDriven 随机日 NULL 事件 | alpha ≈ 0 | \|t\| < 2.5 |
| **C1** (新) | 成本一致性 (signal_net = signal_gross - cost_round_trip) | 浮点严格 | \|diff\| < 1e-9 |
| **C2** (新) | Train/Test 拆分严格性 | 无重叠, 无遗漏 | 集合互斥 |

---

## Pending (未修)

| ID | 问题 | 原因 |
|----|------|------|
| **B6** | Event-driven 把每事件视为 iid 算 t-stat, 但事件聚集 (同日多只涨停) | 修法 = cluster-by-day SE 或日级聚合, 是中等 refactor. self_test EventNULL 通过即可暂缓. |
| **D1** | Index benchmark (HS300/CSI500/CSI1000) `period_return` 返回 None | 未实现, 需要接 AKShare/baostock 拉指数. Random control 已经覆盖核心需求. |

---

## 用法守则 (修后)

```python
from research.foundation import (
    DataBundle, Universe, CostModel,
    CrossSectionalStrategy, EventDrivenStrategy,
    Backtest, StandardReport,
)

data = DataBundle.load()
uni = Universe.broad(data, mcap_range=(30, 500))

# 单次 random control 抽样 (新默认): t-stat 真实
bt = Backtest(strategy=strat, universe=uni,
              cost_model=CostModel.a_share_retail_quarterly(),
              random_control=True,
              train_test_split=("2018-12-31", "2019-01-01"))

# 想做稳健性: 跑 K 次, 每次不同 seed, 取 t-stat 中位数
results = []
for seed in [42, 43, 44, 45, 46]:
    bt = Backtest(..., seed=seed)
    results.append(bt.run().full_summary["t_stat"])
median_t = np.median(results)
```

**禁止**: `n_random_repeats > 1` (除非你懂 t-stat 会被压制, 并显式接受这个偏差).

---

## 2026-05-18 patches inspired by WW-shan

- **Literal[False] type-level dry-run enforcement**: 来自 `WW-shan/Crypto_Research_Agent/pipeline/paper_sim_loop.py`. `Backtest()` 现在带 `execution_mode: Literal["research","paper"]` + `live_capital_enabled: Literal[False]`. 跑 live 必须走独立 execution 层, foundation **不解锁**.
- **Train/test gap_days**: 来自 `WW-shan/meme/pipeline/train_hybrid.py` 的 `_split_lifecycle_files_three_way` enforce_no_overlap 启发. A 股 cross-sectional 域适配为 feature look-ahead 防御——`_split_train_test` 新增 `min_gap_days` 参数 (默认 60), train 末日和 test 首日之间留 buffer, 吸收最长滚动窗口因子. 短于建议值抛 warning (向后兼容).
- **assert_no_feature_lookahead**: 检测因子列是否与自身 shift(1) 高度相关 (>0.95). 在 `DataBundle` 上作为静态方法可用, 可在回测前验证因子不含未来数据.
