# Live 声明审计 — 2026-07-02

执行人: Claude (Fable 5) + Johnny
性质: 执行 `RERUN_LEDGER_2026-05-25.md` 的遗留处方 + 建立防再犯基础设施

## 1. 背景

原计划是"用 polyFIFA2026 验证过的 cluster bootstrap 工具箱审计 14 个月
live 记录 (53.76% 胜率)"。审计的第一步 —— 定位底层数据 —— 直接命中
2026-05-25 truth manifest 已经记录的事实:

> `battle_trades_all.csv`, `battle_reports/report_*/battle_trades_all.csv`,
> `research/baseline_v6_1/output/live_validation_srf_summary.csv`,
> `live_validation_srf_by_date.csv` 全部缺失, `find` + `mdfind` 均未找回,
> 当前无法复现, 应降级为 historical undocumented claim。

即: **审计无法进行, 因为被审计对象已经不存在**。这本身就是审计结论。

## 2. 已执行动作

1. **降级 53.76%** (ledger 处方原文: "找不到就把 53.76% 永久降级"):
   - `CLAUDE.md` What This Is 第 3 条 → 删除线 + DEMOTED 标注
   - `README.md` cubes.db 数据集章节 → 删除线 + 降级说明
2. **标注根目录 0 字节 `cubes.db`**: 2026-05-24 意外创建的空文件,
   与真身 `data/cubes.db` (231MB) 同名 — 已在 CLAUDE.md 标注勿引用。
   (未删除: 留给 Johnny 确认没有脚本硬编码根目录路径后自行处理。)
3. **建立 `research/foundation/live_ledger.py`** — 见下节。

## 3. LiveLedger: 为什么 53.76% 事故不会再发生

53.76% 的死因解剖:
- 记录散落在多个 CSV, 无 single source of truth → 迁移/清理时静默丢失
- 声明只有点估计, 无 CI, 无 n → 无法评估其证据强度
- 价格来源无 provenance → 即使找回也无法验证

LiveLedger 逐条对症:

| 死因 | 机制 | 来源 |
|---|---|---|
| 记录丢失/删改不可见 | append-only JSONL + SHA-256 hash chain, `verify()` 检出任何删改, 断链时 `entries()` 拒绝服务 | 审计日志/区块链模式 |
| 无 provenance | `price_source` 白名单强制 (broker_fill / baostock_close / ...), 白名单外 `UnverifiedProvenance` 拒收 | polyFIFA2026 `time-window.ts:26` "unverified clock → no trade" |
| 裸点估计声明 | `audit()` 输出 cluster bootstrap CI (按开仓日聚类); n<30 直接拒绝给出胜率声明 | foundation v2 `stats.py` |

自检 5/5: append/verify/白名单拒收/篡改检测/小样本拒声明。

## 4. 对未来 live 声明的规则 (提议写入 CLAUDE.md 流程)

1. 任何进入 CLAUDE.md/README 的 live 数字, 必须能从 `data/live_ledger.jsonl`
   一条命令复现。
2. 声明格式必须带 CI 和 n: "胜率 54% [49%, 59%], n=87, 41 个交易日" —
   裸点估计一律不收。
3. `LiveLedger.verify()` 进入日常 pipeline (如 MORNING_BRIEF 生成前跑一次)。

## 5. 与 foundation v2 的关系

本次同批落地的 `stats.py` (cluster bootstrap + frame_control) 是审计的
计算基座; LiveLedger 是数据基座。两者合起来兑现同一句话:

> **没有 CI 的点估计不是证据; 没有 provenance 的记录不是数据。**

## 6. 遗留

- [ ] Johnny 确认后删除根目录 0 字节 `cubes.db`
- [ ] 30/30/40 生产组合接入 LiveLedger (季度再平衡时各写一条 BUY/SELL/MARK)
- [ ] 若未来找回 battle_trades_all.csv, 按 §4 规则重新入账并撤销降级
