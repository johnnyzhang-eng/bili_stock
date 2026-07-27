# Bili_Stock Rerun Ledger — 2026-05-25

目标: 把历史上用错误方法得出的错误结论, 用当前最严格方法重新跑一遍。这个文件记录「已重跑 / 可直接重跑 / 需要改造 / 数据缺口」, 防止旧报告继续被误引用。

## 执行标准

- 正确解释器: `.venv/bin/python`。系统 `python3` 是 3.9.6, 会在 `DataBundle | None` 注解处导入失败。
- 基础 gate: `research/foundation/self_test.py` 必须通过。
- 当前通过状态: 2026-05-25 已跑通 7/7, OHLCV coverage 94%。
- 最新方法底线: point-in-time 数据、真实成本、random/matched control、train/test OOS、同宇宙 benchmark、禁止 live-capital、避免 snapshot 选样、B8 axis-stability gate。
- 数字口径: 除非特别说明, alpha 都是 signal vs random/matched baseline, 不是 vs HS300。

## 已完成重跑

| 家族 | 旧错误结论 | 最新方法/命令 | 当前结果 | Verdict |
| --- | --- | --- | --- | --- |
| Foundation 自检 | 回测框架本身可能带 bug | `.venv/bin/python -B research/foundation/self_test.py` | 7/7 PASS; NULL/RANDOM 无显著 alpha; 高换手负; 前视强正; event NULL 无偏 | 框架可继续用于重跑 |
| Cycle001 A1 smart-cube avoidance | 2026-05-23 A1 `VALIDATED`, `+13.91%/yr excess`, `+40.44% test CAGR` | `.venv/bin/python -B research/foundation/run_all_hypotheses.py --quiet` | A1 `+0.15%/period`, `t=+0.12` | REJECT |
| Cycle001 H2 cluster buy | 智能组合集群买入可能有 alpha | 同上 | H2 `+0.90%/period`, `t=+0.71` | REJECT |
| Cycle001 H3 mass exit | 智能组合集体卖出可能有 alpha | 同上 | H3 `+0.33%/period`, `t=+0.29` | REJECT |
| Cycle001 H4 skill-weighted buy intensity | 用 cube skill 加权可能恢复信号 | 同上 | H4 `-1.17%/period`, `t=-0.99` | REJECT |
| Cycle001 matched baseline | A1/H4 可能只是 random baseline 不够匹配 | `.venv/bin/python -B research/foundation/cycle001_matched_baseline.py` | A1 matched `+0.57%/period`, `t=+0.70`; H4 matched `-1.66%/period`, `t=-1.31`; 输出与既有报告一致无 diff | 不救 A1/H4 |
| 低波 baseline | `CAGR 13.17% / Calmar 0.86` 可作为系统低波 alpha | `.venv/bin/python -B research/foundation/strategies_lowvol.py` | Full alpha `-0.32%/期`, `t=-0.59`; Test alpha `-0.52%/期`, `t=-0.77` | REJECT |
| 52-week high 动量 | 经典 52W high 动量可能迁移到 A 股 | `.venv/bin/python -B research/foundation/strategies_52w_high.py` | Train alpha `+2.63%/期`, `t=+0.78`; Test alpha `-4.52%/期`, `t=-0.86`; Full alpha `-1.17%/期`, `t=-0.36` | REJECT |
| 12 因子 battery | README/旧 memory 说 12 单因子全 `t<2` / 无 alpha | `.venv/bin/python -B research/foundation/run_factor_battery_foundation.py` | 11/12 为负或不显著; 小盘 SMB Test alpha `+6.44%/期`, `t=+2.31`, 但 Train alpha `-6.25%/期`, `t=-2.95`, Full alpha `+0.49%/期`, `t=+0.24` | 11 个 REJECT; SMB 需二次复验 |
| SMB sensitivity | 小盘 SMB 是否是 12 因子里唯一可疑正 alpha | `.venv/bin/python -B research/foundation/run_smb_sensitivity_foundation.py` | broad 30-500: seed 1/42/99 Test t `0.99/2.31/0.60`; small 30-100 Test t `1.55/1.29/0.53`; mid 100-500 Test t `1.79/1.63/1.61`, Full t 最高 `1.84` | 不稳健, 不入生产; 仅保留研究观察 |
| MAX IC diagnostic | `MAX因子(待做)` 可能补上低波以外的行为 alpha | `.venv/bin/python -B research/factors_v2/run_max_factor_ic.py` | IC `+0.0294`, ICIR `0.176`; top bucket gross `+3.97%/yr`, ann cost `6.69%`, net top `-2.72%/yr`; rank corr with low_vol `+0.620` | diagnostic 可跑但非 foundation; 扣成本后不支持生产 |
| BAB IC diagnostic | BAB/low-vol stack 可能提高收益 | `.venv/bin/python -B research/factors_v2/run_bab_factor_ic.py` | BAB IC `-0.0040`; stack net CAGR `+20.13%` 但 MDD `-61.49%`; broad panel only `828/5051` stock files loaded | 方法不合格的高 CAGR red flag; 需 foundation 迁移后才能判断 |
| Reversal IC diagnostic | 短反转可能是独立低相关 alpha | `.venv/bin/python -B research/factors_v2/run_reversal_ic.py` | reversal 5d IC `+0.0138`; hs=5 net CAGR `+3.95%~+5.57%`, MDD `-82%`; hs=12 reversal net CAGR `+18.29%`, MDD `-68.26%`; stack 不优于 low_vol baseline | diagnostic 可跑但非 production; 高换手/大回撤/无 random OOS gate |
| Clean factor / GOOD28 / MAX56_OK | legacy clean_dist A 显示 `CAGR_net +27.33% / Calmar 0.706`, 可能是新 alpha | legacy diagnostic: `.venv/bin/python -B research/factors_v2/run_clean_factor_backtest.py`; strict rerun: `.venv/bin/python -B research/foundation/run_clean_factor_foundation.py --modes dist_a --seeds 1,42,99` + `--modes hvbal_b,combo_z --seeds 42 --merge-existing` | dist_a seeds 1/42/99 Test alpha `-0.19%/+0.18%/-0.46%`, t `-0.38/+0.41/-0.61`; hvbal_b seed42 Test alpha `-1.35%`, t `-1.92`; combo_z seed42 Test alpha `-0.24%`, t `-0.35` | REJECT; legacy high CAGR 不满足 foundation/random/OOS |
| 全天候 T2 overlay | T2 应作为默认生产; 旧报告 OOS Calmar 差 `-0.18` | `.venv/bin/python -B research/factors_v2/all_weather_alpha_decomp.py`; `.venv/bin/python -B research/factors_v2/all_weather_oos.py` | 当前数据到 2026-05-18: Static Test Calmar `0.86`; T2 Test Calmar `0.81`; T2 vs static `-0.05`; T2 Full `+8.18%/-17.4%` | 静态仍默认; T2 仅可选 |
| 全天候 T2 参数敏感性 | T2 单点参数可能过拟合 | `.venv/bin/python -B research/factors_v2/all_weather_t2_sensitivity.py` | 16 组 SMA/MOM: CAGR `+6.20%`~`+7.59%`, Calmar `0.36`~`0.44`, std(CAGR) `0.42%`; 输出 `t2_sensitivity.csv` | 参数不脆, 但不改变静态默认 |
| 全天候权重 sweep | 优化权重可能替代 30/30/40 | `.venv/bin/python -B research/factors_v2/all_weather_sweep.py` | Calmar Top1 是 30/30/40: CAGR `+7.36%`, MDD `-19.4%`, Calmar `0.38`; CAGR Top among Calmar>=0.30 是 40/20/40: CAGR `+7.70%`, MDD `-24.7%`, Calmar `0.31`; 黄金 SMA200 overlay 降 CAGR 到 `+7.10%` 但 Calmar `0.41` | 不替代 30/30/40; sweep 只作探索 |
| H1 首板次日 open | 一进二/打板普通执行可能赚钱 | `.venv/bin/python -B research/foundation/strategies_first_to_second_board.py` | 75,290 events; H1 Full alpha `-0.18%`, `t=-9.89`; net `-0.49%` | REJECT |
| H1b 尾盘抢板 | T close -> T+1 close 隔夜 alpha | 同上 | Full alpha `+2.06%`, `t=+82.27`; net `+0.30%`; 95% CI `[+2.013%, +2.109%]` | 数学存在, 执行待纸面验证; 不等于 dashboard 生产 |
| H3 首板按换手切分 | 换手过滤能救次日 open 追板 | 同上 | H1 Q1/Q2 负; Q3 alpha `+0.06%`, `t=+0.76`; 不显著 | REJECT |
| H9 教学规则 | 量能/小盘/人气/高开等教学规则叠加能翻正 | `.venv/bin/python -B research/foundation/strategies_h9_textbook_rules.py` | base `-0.13%`, `t=-6.97`; ALL 765 events `-1.47%`, `t=-7.25`; net `-1.51%` | REJECT |
| v4-v6 雪球/SRF legacy | `baseline_v6_1`/SRF/hold_step=12 仍可能是生产 alpha | `.venv/bin/python -B research/foundation/run_xueqiu_legacy_foundation.py --seeds 1,42,99 --hold-bdays 10,12,15 --rebuild-panel` | follow Top30 全部 OOS 弱或 sign flip; contrarian Bottom30 全部 OOS 弱或 sign flip; SRF v2 仅 hold=12 seed 42/99 出现 Test alpha `+1.08%/期`, `t=2.05/2.11`, 但 hold=10/15 OOS 全弱 | 旧生产 REJECT; SRF v2 12日弱正只列 warning, 不入 dashboard |
| SRF v2 hold=12 deep audit | hold=12 弱正是否能升级为候选 alpha | 读 `research/factors_v2/output/xueqiu_legacy_v6_foundation.csv`; 输出 `research/factors_v2/output/srf_v2_hold12_deep_audit.md` | date-mean hold=12 Test matched alpha `+1.063%`, `t=2.15`, 但 Bonferroni over 9 tests 后 p `0.3232`; by-year 无一年独立显著; 第二半段 t 仅 `0.76/1.09/1.21`; hold=10/15 失败 | NOT PRODUCTION; research-only anomaly |
| smart_consensus contrarian diagnostic | `Top30 - Bottom30 = -6.8pp` 可作为当前数字 | `.venv/bin/python -B research/smart_consensus/test_contrarian.py` | bot-top mean weekly `+0.0063%`, ann `+0.33%`, `t=+0.09`; avoid-top excess ann `-0.80%`, `t=-0.23` | 旧 `-6.8pp` 不是当前 strict evidence; 方向 lesson 保留 |
| Cube attention delta/momentum/accel | 2026-05-21 `momentum_short` 接近 2σ, 可能发展成 contrarian attention alpha | 本轮检查 `research/cube_attention_delta/verdict_2026-05-23.md` 与 `output/final_summary_v2.csv`; 未完整重跑, 因 `factor_delta.csv/factor_momentum.csv/factor_accel.csv` 当前缺失 | full-data v2: momentum_long mean IC `+0.0037`, all t `+2.06`, Test IC `+0.0018`, Test t `+0.76`; long-only Test signal gross `+16.64%` vs random `+16.61%`, Test excess `-0.016%/wk` | 当前证据 REJECT; 若要再跑需重建 factor matrices |

## 当前输出文件变更

- `research/factors_v2/output/low_vol_foundation_validation.md`: 当前重跑数字覆盖旧数字, 结论仍 REJECT。
- `research/factors_v2/output/52w_high_foundation.md`: 当前重跑数字覆盖旧数字, 结论仍 REJECT。
- `research/foundation/run_factor_battery_foundation.py`: 新增 foundation 版 12 因子 runner, 替代旧 `factor_battery_test.py` 的自有 loop。
- `research/factors_v2/output/factor_battery_foundation_report.md`: 当前 foundation 重跑报告。
- `research/factors_v2/output/factor_battery_foundation_results.csv`: 当前 foundation 重跑 CSV, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/foundation/run_smb_sensitivity_foundation.py`: 新增 SMB 二次复验 runner。
- `research/factors_v2/output/smb_sensitivity_foundation.md`: SMB seed/size-bucket 复验报告。
- `research/factors_v2/output/smb_sensitivity_foundation.csv`: SMB 复验 CSV, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/factors_v2/output/max_factor_ic.csv`: MAX IC diagnostic 输出, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/factors_v2/output/bab_factor_ic.csv`: BAB/low-vol stack diagnostic 输出, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/factors_v2/output/reversal_ic.csv`: reversal/low-vol stack diagnostic 输出, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/foundation/run_clean_factor_foundation.py`: 新增 clean factor foundation rerun, 用于审计 GOOD28/MAX56_OK/clean_dist 遗留高收益。
- `research/factors_v2/output/clean_factor_foundation.md`: clean factor strict rerun 报告。
- `research/factors_v2/output/clean_factor_foundation.csv`: clean factor strict rerun CSV, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/factors_v2/output/all_weather_alpha_decomp.md`: 数据刷新到 2026-05-18; T2 OOS 差距更新为 `-0.05`。
- `research/factors_v2/run_all_weather_signal.py`: 未改代码, 但发现 DingTalk markdown 文案仍写旧回测数字。入口可用, 文案数字不可复用。
- `research/factors_v2/output/first_board_suite.md`: 当前事件数 75,290, 输出 H1/H1b/H3 详细表。
- `research/factors_v2/output/h9_textbook_rules.md`: 当前事件数和 alpha 更新, 结论仍 REJECT。
- `research/factors_v2/output/t2_sensitivity.csv`: 由 T2 sensitivity 重跑生成, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/factors_v2/output/all_weather_sweep.csv`: 由 all-weather weight sweep 重跑生成, 当前被 ignore, 不在普通 `git status` 中显示。
- `research/foundation/run_xueqiu_legacy_foundation.py`: 新增 v4-v6/SRF foundation-compatible rerun, 禁用旧 backtest loop/go-flat/Top30-Bottom30 执行口径。
- `research/factors_v2/output/xueqiu_legacy_v6_foundation.md`: v4-v6/SRF 严格重跑报告。
- `research/factors_v2/output/xueqiu_legacy_v6_foundation.csv`: v4-v6/SRF 重跑明细 CSV, 含 hold 10/12/15、seed 1/42/99、matched control、size/turnover audit fields。
- `research/factors_v2/output/srf_v2_hold12_deep_audit.md`: SRF v2 hold=12 弱正异常的二次稳定性审计; 结论为 research-only anomaly, not production。
- `research/smart_consensus/output/contrarian_diagnostic_2026-05-25.md`: current corrected smart_consensus diagnostic; confirms old `-6.8pp` should not be cited as strict current evidence。

## 可直接继续重跑

这些已有脚本或报告路径, 可继续用 `.venv/bin/python` 跑, 但还没在本 ledger 完成验收:

- `research/cube_attention_delta/rerun_ic_only.py`, `long_only_backtest.py`: 当前缺 `output/factor_delta.csv`, `output/factor_momentum.csv`, `output/factor_accel.csv`, 所以不能从源矩阵复现 2026-05-23 verdict。`rerun_with_full_data.py` 只能重建 `forward_returns_v2.csv`, 不重建 factor matrices。

## 需要改造后再重跑

这些不能直接算「最新最对方法」, 因为当前脚本不是 foundation/attack-registry 全套 gate:

- 12 因子 battery 后续: foundation 版已完成第一轮重跑, SMB seed/size-bucket 复验不支持生产级 alpha。若还要深挖, 只剩 matched size/liquidity control 和更长样本, 但当前 dashboard 不应接入。
- IC-only 因子脚本: `run_max_factor_ic.py`, `run_bab_factor_ic.py`, `run_reversal_ic.py` 已可运行, 但只是 diagnostic。它们没有 foundation random/matched control、正式 train/test gate、same-universe alpha attribution, 且 `build_broad_panel` 当前只成功加载 `828/5051` stock files。任何正 CAGR 都不能作为生产结论。
- 5-asset 全天候: `.venv/bin/python -B research/factors_v2/all_weather_5asset_oos.py` 当前失败, 缺 `research/factors_v2/output/long_history_5asset.csv`。需要先确认数据生成链路或把它降级为未复现探索。
- v4-v6 雪球/SRF/baseline_v6_1 深查: 最小 foundation-compatible rerun 已完成, 旧生产结论不成立。若要继续研究 SRF v2 的 12日弱正异常, 需要更深层 audit, 不能直接接 production。
  - 旧正向 claims: `CHANGELOG.md` v5 Calmar `0.359`, v4.2 `0.181`, v4 `0.173`; `archive/unusable_2026_05_25/research/baseline_v6_1/report/phase2_research_report.md` SRF v2 / asymmetric choppy go-flat best Calmar `0.480`, annual return `6.91%`; `ARCHITECTURE.md` 仍残留 elite-cube production 架构。
  - 生成旧数字的关键代码: `research/baseline_v4/code/run_baseline_v4_2_up_filter.py`, `research/baseline_v5/code/run_baseline_v5_with_costs.py`, `research/baseline_v6_1/code/run_baseline_v6_v61_suite.py`, `research/baseline_v6_1/prod_config.py`。
  - 明确 invalidators: `research/baseline_v6_1/report/visual/_STALE_NOTICE.md` 标记 pre-audit visual invalid; `README.md` timeline 写 v1-v4 前视/指标错、v5 long-short invalid、v6.1 go-flat 用未来收益; `CLAUDE.md` 当前 honest numbers 写旧 `22.9%` fake、修后 ann return `~2%`, Calmar `0.04-0.05`。
  - 数据可得性: 不是数据全缺。`data/cubes.db` success rebalancing `8,070` 行、`1,350` 个 stock_symbol、时间 `2014-11-25` 到 `2026-03-02`; `data/stock_data` 有 `5,051` 个价格文件。问题是旧 runner 的评价口径和风险控制污染, 不是完全不能研究。
  - 可 port 的只有信号定义: `factor_z` / `factor_z_neu`, regime-conditioned sign, Xueqiu rank/gate, SRF v2 score components。不可 port: asymmetric choppy go-flat、Top30-Bottom30 performance claim、旧 visual/cached outputs、旧 cost/risk-control metrics。
  - 已实现的最小 runner: `research/foundation/run_xueqiu_legacy_foundation.py`; 从 `data/cubes.db` / `research/factors/factor_rebalance_momentum.py` 重建 point-in-time signal panel, B2-style shift 到事件后首个交易日, 禁用旧 backtest loop。
  - 已深查的部分: SRF v2 hold=12 seed 42/99 matched alpha 弱正, 但 hold=10/15 OOS 全弱; date-mean t `2.15` 经 9-test Bonferroni 后 p `0.3232`; by-year/second-half/regime 不稳。归类为 research-only anomaly。
- 早期 B 站荐股/荐股博主: 当前只有 `archive/unusable_2026_05_25/analysis/backtest_report.md` 摘要, 记录 `总交易次数 278`, `胜率 24.5%`, `累计收益 -91.85%`; 但原始 `data/dataset_videos.csv`, `data/dataset_comments.csv`, `data/trading_signals.csv`, `data/backtest_report.csv`, `strategy_log.csv`, `data/ocr_results.csv` 都缺失。`core/extract_signals.py`, `core/backtest_engine.py`, `archive/bilibili_legacy/core/bili_collector.py`, `archive/bilibili_legacy/core/ocr_validation.py` 可见, 但 `archive/bilibili_legacy/` 只有 56K 代码档案且无 CSV/JSON/DB。`find /Users/johnnyzhang/jz_code` 与 `mdfind` 均未找回这些输入; `git rev-list --all` / `git log --all --name-status` 对这些路径无记录, 且 `.gitignore` 忽略 `*.csv` / `*.json`, 大概率从未入库。不能用最新方法重跑。
- CB lead-lag: `docs/cb_leadlag_alpha_research_report.md` 明确只是研究方案, 没有 alpha verdict。当前应保持 `INSUFFICIENT_EVIDENCE`, 不能接入 dashboard。
- Residual stale claim inventory (2026-05-25 read-only scan):
  - `research/attention_orj/cache/DATA_STATUS_2026-05-23.md`: still says `A1 VALIDATED`; superseded by 2026-05-24 foundation REJECT.
  - `archive/unusable_2026_05_25/docs/quant_concepts_guide.md`: still teaches v6.1 Calmar `0.28`, live win rate `53.76%`, Phase2 Calmar `0.48`; numbers are stale/undocumented.
  - `research/baseline_v6_1/prod_config.py`: still named active production branch; comments already admit honest ann_ret `~2%`, Calmar `0.04-0.05`.
  - `archive/unusable_2026_05_25/research/baseline_v6_1/code/wire_phase2_winner.py`: old auto-wire highest-Calmar SRF flow; do not run as production.
  - `archive/unusable_2026_05_25/research/baseline_v4_2/report/baseline_v4_2_lock.md`, `archive/unusable_2026_05_25/research/baseline_v5/report/baseline_v5_lock.md`, `archive/unusable_2026_05_25/research/baseline_v6_1/report/phase_d_validation_report.md`: historical candidates only.
  - `research/factors_v2/output/v2_findings_2026_04.md`: low_vol, DIV/GEM, DCA, and CB market-temperature claims are 2026-04 exploration, not current production.
  - `archive/unusable_2026_05_25/docs/factor_learning_notes_2026_04.md`: still says low_vol was correct at `CAGR_net 13.17%`; superseded by foundation low-vol REJECT.
  - `archive/unusable_2026_05_25/docs/hybrid_signal_mining_system.md`, `archive/unusable_2026_05_25/docs/credibility_scorer_prompt.md`, `archive/unusable_2026_05_25/docs/V2_0_IMPLEMENTATION_GUIDE.md`, `archive/unusable_2026_05_25/docs/AI_Model_Architecture.md`, `archive/unusable_2026_05_25/docs/ocr_processor_prompt.md`, `archive/unusable_2026_05_25/docs/clean_and_rank_prompt.md`: still describe historical win-rate/OCR-weighted scorer ideas; early Bilibili raw datasets are missing and this framework is not current production evidence.
  - `archive/unusable_2026_05_25/research/cube_attention_delta/verdict_2026-05-21.md`: superseded by 2026-05-23 full-data REJECT.
- `live win rate 53.76%`: 文档声明存在于 `CLAUDE.md` / `README.md`, 但本地缺 `data/battle_trades_all.csv`, `battle_reports/report_*/battle_trades_all.csv`, `research/baseline_v6_1/output/live_validation_srf_summary.csv`, `research/baseline_v6_1/output/live_validation_srf_by_date.csv`。`research/baseline_v6_1/code/run_live_validation.py` 需要这些输入; `find /Users/johnnyzhang/jz_code` 与 `mdfind` 均未找回这些文件名, 当前无法复现, 应降级为 historical undocumented claim。
- Xueqiu 旧 JSON 历史: older scripts 可能依赖 `data/history/` 和 `data/massive_cube_list.json`, 当前缺失。若要重跑 v4-v6/SRF, 需要改用当前 `data/cubes.db` 或找回原始 JSON。
- `cubes.db` Top30/Bottom30 `-6.8pp`: direction lesson 有文档支持, 但不是当前 canonical strict metric。当前 corrected smart_consensus 链路主要使用更丰富的 `research/attention_orj/cache/rebalancing/*.json`, 不是直接使用 `data/cubes.db` 的 8,720 条 sparse rebalancing rows。
  - Corrected command chain: `research/smart_consensus/cube_nav_history.py` -> `research/cube_attention_delta/rerun_with_full_data.py` -> `research/smart_consensus/build_signal.py` -> diagnostic `research/smart_consensus/test_contrarian.py` -> strict `research/foundation/run_all_hypotheses.py --quiet` -> `research/foundation/cycle001_matched_baseline.py`。
  - Diagnostic only: `test_contrarian.py` 已在 2026-05-25 重跑; top/bottom smart-consensus 差 `+0.33%/yr`, `t=+0.09`, avoid-top excess `-0.80%/yr`, `t=-0.23`。仍未 fully matched, 不替代 foundation verdict。
  - 当前 canonical strict result 是 A1 matched `+0.57%/period`, `t=+0.70`, REJECT。

## 下一批优先级

1. 找回 live_validation 数据; 找不到就把 `53.76%` 永久降级为 historical undocumented claim。
2. 如 dashboard 需要反向情绪图, 用 smart_consensus corrected chain 生成 diagnostic, 但默认展示 canonical A1/H2/H3/H4 REJECT 和 matched baseline; 不展示 `-6.8pp` 为 strict evidence。
3. SRF v2 hold=12 若未来继续, 必须新建预注册 runner, 做 B8 axis-stability + date bootstrap + stronger matched control; dashboard 当前不接。

## 可行性结论

可行, 但不是一次性跑旧脚本。需要约束为:

- 已 foundation 化的策略: 可以直接批量重跑, 本轮已完成主要负例。
- 未 foundation 化的旧策略: 先迁移方法, 后重跑数字。
- 缺原始数据的历史结论: 只能标为待验证/不可复现, 不能硬重跑。

截至本文件, 已经覆盖了核心 false-positive 家族: smart-cube A1/H2/H3/H4、低波、52W high、12 因子 foundation 重跑 + SMB 二次复验、MAX/BAB/reversal diagnostic、clean factor foundation 重跑、T2 默认性、首板/H8、H9、v4-v6 雪球/SRF 最小 foundation-compatible 重跑 + SRF v2 hold=12 deep audit、当前 smart_consensus contrarian diagnostic。剩余最大缺口是 live validation 原始交易数据。
