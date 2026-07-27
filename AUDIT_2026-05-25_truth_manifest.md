# Bili_Stock Truth Manifest — 2026-05-25

审计口径: 本文件只标记事实状态, 不修 bug, 不替策略辩护。没有本地复现的数据一律标为「待验证」或「警告」。

## TL;DR (3 行)
- 当前唯一可直接接入 dashboard 的生产资产: 静态 30/30/40 四 ETF 全天候组合, 即 30% 股票腿(512890:159915 = 7:3) + 30% 511010 + 40% 518880; `run_all_weather_signal.py` 默认静态, T2 只能通过 `--t2` 启用。
- 实测可信 10 条 / 警告至少 9 条 / 明确过时或证伪至少 22 条 / 待验证至少 10 条; README 的静态 `CAGR 7.43% / MDD -18.96%` 未在当前数据精确复现, 当前脚本复现为 `CAGR 7.36% / MDD -19.4%`。
- 推荐对接给外部 dashboard 的资产: [`30/30/40 static allocation`, `research/factors_v2/output/long_history_4asset.csv`, `research.foundation`, `4 条 QC 硬规则`, `6 类证伪 lessons`, `data/cubes.db` 反向情绪素材, `run_all_weather_signal.py --push`]。

## 审计命令与环境事实

- 必跑命令里的 `python` 在当前机器不存在: `python not found`。系统 `python3` 是 `3.9.6`, 不适合 foundation 代码；本轮实测统一用 `.venv/bin/python 3.12.13`。
- 根目录 `long_history_4asset.csv` 不存在; 真实生产数据在 `research/factors_v2/output/long_history_4asset.csv`。
- 当前 HEAD: `4dae699 chore(cycle002): commit per-bond data, single-brain launcher, codex H2 report`。
- repo 总大小 `3.1G`; `data/` 为 `1.2G`; 全天候接入最小必需文件 `long_history_4asset.csv` 约 `395K`。
- `data/market_cache/` 存在 5 个文件, 约 `552K`: 4 个 ETF cache + `hs300_daily_cache.csv`。

关键复现结果:

| 项目 | 本地结果 |
| --- | --- |
| `.venv/bin/python -B research/factors_v2/all_weather_oos.py` | 静态 30/30/40 Full `+7.36% / -19.4% / Calmar 0.38 / Sharpe 0.60`; Train `+3.71% / -19.4%`; Test `+11.32% / -13.1%` |
| 同脚本 T2 SMA200/12M | Full `+8.18% / -17.4% / Calmar 0.47`; Train `+6.34% / -17.4%`; Test `+10.10% / -12.5%`; 但不是默认生产 |
| `research/factors_v2/output/long_history_4asset.csv` | 3872 行含表头, 3871 个交易日, `2010-06-01` -> `2026-05-18`, 约 `395K` |
| `.venv/bin/python -B research/foundation/self_test.py` | 7/7 通过, 输出 `✓ 框架自检通过. 可以用于策略验证.` |
| `from research.foundation import ...` | 可导入; `Backtest` API 可实例化检查 |
| `data/cubes.db` | 221M, `cubes=55306`, `rebalancing_history=8720` |

## ✓ 可信资产（可以直接接入 dashboard）

- [x] 30/30/40 静态全天候配置
  - 真实数据源: `research/factors_v2/run_all_weather_signal.py`, `research/factors_v2/all_weather_oos.py`, `research/factors_v2/output/long_history_4asset.csv`。
  - 具体权重: 股票腿 30%, 其中 512890 红利低波 70% * 30% = 21%, 159915 创业板 30% * 30% = 9%; 511010 国债 30%; 518880 黄金 40%。
  - 验证方式: `compute_signal(use_t2=False)` 返回 `mode=static`, `weights={'STK':0.30,'BOND':0.30,'GOLD':0.40}`; `compute_rebalance()` 再把 STK 拆成 DIV/GEM 7:3。
  - 接入难度: easy。
  - 依赖 bili 内部模块: 低。dashboard 可直接读取权重和 CSV; 若要复用实盘信号/钉钉消息, 依赖 `run_all_weather_signal.py`。

- [x] 16 年真实 NAV 数据: `long_history_4asset.csv`
  - 真实数据源: `research/factors_v2/output/long_history_4asset.csv`。
  - 验证方式: `head` + `wc -l` + `tail`; 日期 `2010-06-01` -> `2026-05-18`, 3871 条数据行, columns 为 `date,DIV,GEM,HS300,BOND,GOLD`。
  - 接入难度: easy。
  - 依赖 bili 内部模块: 无。注意根目录同名文件不存在。

- [x] 全天候 OOS 回测脚本作为可复现 baseline
  - 真实数据源: `research/factors_v2/all_weather_oos.py` + `research/factors_v2/output/long_history_4asset.csv`。
  - 验证方式: `.venv/bin/python -B research/factors_v2/all_weather_oos.py`。
  - 当前可信数字: 静态 Full `CAGR +7.36%`, `MDD -19.4%`, `Calmar 0.38`; Test `CAGR +11.32%`, `MDD -13.1%`, `Calmar 0.86`。
  - caveat: README 的 `7.43% / -18.96%` 是旧数据/旧四舍五入口径, 不能当 2026-05-25 当前精确数字。
  - 接入难度: easy。
  - 依赖 bili 内部模块: 低, 只依赖 pandas/numpy 和 CSV。

- [x] `research.foundation` 框架可导入、可自检
  - 真实数据源: `research/foundation/__init__.py`, `research/foundation/backtest.py`, `research/foundation/self_test.py`。
  - 验证方式: `.venv/bin/python -B research/foundation/self_test.py`; 7 段测试通过, 包含 NULL、RANDOM、高换手成本、前视侦测、event NULL、成本一致性、train/test split。
  - 数据边界: `AUDIT_FINDINGS_2026_04_27.md` 明确记录退市股 OHLCV 严重缺失, foundation 股票 alpha 需按 `1-3%/yr` 系统性高估折价后再判断; ETF 全天候不依赖这套股票 universe。
  - 接入难度: medium。
  - 依赖 bili 内部模块: 中。导入 API 容易; 真跑股票/事件策略会依赖 foundation 数据 bundle、universe、成本模型及本 repo 数据布局。

- [x] Foundation 的硬 rail: random control / cost / research-only live guard
  - 真实数据源: `research/foundation/backtest.py`。
  - 验证方式: 检查 `Backtest.__init__` 签名和 runtime 检查。
  - 可信边界: `random_control` 必须显式传 bool; `random_control=False` 必须写 reason; `cost_model` 是必填参数; `live_capital_enabled` 被 assert 为 `False`。
  - caveat: `train_test_split` 在代码里是 `Optional[Tuple[str, str]] = None`, 所以 OOS 是流程/协议硬规则, 不是构造函数层面的硬异常。
  - 接入难度: medium。
  - 依赖 bili 内部模块: 中。

- [x] CLAUDE.md 的 4 条 QC 硬规则仍然是有效 lessons
  - 真实数据源: `CLAUDE.md`, `research/foundation/AUDIT_FINDINGS_2026_04_27.md`, `research/foundation/_engine/lessons_learned.md`。
  - 验证方式: 与 foundation self-test 和后续 methodology audit 交叉检查。
  - 可接入内容: random control、OOS、真实成本、避免前视/幸存者偏差。适合放 dashboard audit/status bar, 不适合当策略信号。
  - 接入难度: easy。
  - 依赖 bili 内部模块: 无。

- [x] 6 类证伪报告作为「不要再踩」资产
  - 真实数据源:
    - 雪球散户/智能资金: `research/smart_consensus/verdict_2026-05-24_foundation.md`, `research/factors_v2/output/xueqiu_legacy_v6_foundation.md`, `research/smart_consensus/output/contrarian_diagnostic_2026-05-25.md`, `docs/quant_strategy_lessons.md`。
    - 12 因子: `research/factors_v2/output/factor_battery_foundation_report.md`, `research/factors_v2/output/smb_sensitivity_foundation.md`。README 旧引用 `memory/factor_battery_findings.md` 在当前 checkout 缺失, 不再作为 canonical path。
    - 低波: `research/factors_v2/output/low_vol_foundation_validation.md`。
    - 一进二板: `research/factors_v2/output/first_board_research_summary.md`。
    - 教学规则: `research/factors_v2/output/h9_textbook_rules.md`。
    - T2: `research/factors_v2/output/all_weather_alpha_decomp.md`, `research/factors_v2/run_all_weather_signal.py`。
  - 验证方式: 文件存在性检查 + 阅读报告 + 与 MORNING_BRIEF / methodology audit / git log 交叉。
  - 接入难度: easy。
  - 依赖 bili 内部模块: 无, 可作为 dashboard 的 lesson/guardrail 文案。

- [x] `data/cubes.db` 原始库存在, 可作为研究数据/反向情绪素材
  - 真实数据源: `data/cubes.db`。
  - 验证方式: `ls -lh`, `sqlite3 .schema`, `SELECT COUNT(*)`。
  - 表结构:
    - `cubes(symbol PRIMARY KEY, name, owner_id, owner_name, followers_count, total_gain, monthly_gain, daily_gain, annualized_gain_rate, description, created_at, updated_at, raw_json)`。
    - `rebalancing_history(id, cube_symbol, stock_symbol, stock_name, prev_weight_adjusted, target_weight, price, net_value, created_at, updated_at, status, UNIQUE(cube_symbol, stock_symbol, created_at))`。
  - 当前计数: `cubes=55306`; `rebalancing_history=8720`; status: `success=8070`, `canceled=444`, `failed=170`, `pending=36`。
  - 接入定位: 只能作为「散户/组合经理行为反向情绪」素材, 不能当正向跟随信号。
  - 接入难度: medium。
  - 依赖 bili 内部模块: 低到中。dashboard 可直接 SQLite 只读接入; 若重跑 alpha 需要 smart_consensus/foundation 代码。

- [x] 钉钉推送入口存在
  - 真实数据源: `research/factors_v2/run_all_weather_signal.py`, `config.example.py`。
  - 验证方式: 代码检查; `--push` 入口存在; `send_dingtalk()` 使用 `requests.post`; config 优先从 `config.py` import, 失败后读取 `DINGTALK_WEBHOOK` / `DINGTALK_SECRET`。
  - caveat: `config.py` 不存在且应为本地 gitignored 配置; `grep -r "dingtalk\|webhook" --include="*.py" config*` 因大小写/文件名范围返回空, 不能说明没有钉钉实现。
  - 接入难度: medium。
  - 依赖 bili 内部模块: 中, 依赖 signal 脚本、requests、akshare 取价以及用户私有 webhook。

- [x] 与 `investment_research_2026_05_24` 的 ETF 重合关系已确认
  - bili 当前生产四 ETF: 512890, 159915, 511010, 518880。
  - dashboard `monitor/config/portfolios.py`: 512890 与 518880 存在; 159915 不存在; 511010 不存在。dashboard 使用的是 511090/511180/511380 等其他债券/转债 ETF。
  - 验证方式: 在 dashboard repo `rg "512890|159915|511010|518880|511090|511180|511380" monitor/config/portfolios.py`。
  - 接入难度: easy。
  - 依赖 bili 内部模块: 无。

## ⚠️ 警告资产（需要附加 caveat 才能用）

- [ ] T2 动量 overlay
  - 状态: 可运行, 但不是默认生产。
  - 证据: `run_all_weather_signal.py` 顶部明确写 `默认静态, T2 动量 overlay 可选`; CLI 需要 `--t2`。
  - caveat: `all_weather_oos.py` 内部配置名仍写 `T2 SMA200/12M (生产)`, 这是脚本文案滞后。README 和 signal 脚本已把静态改为默认。
  - 数字边界: 当前 `all_weather_oos.py` T2 Full `+8.18% / -17.4%`; 2026-05-25 重跑的 `all_weather_alpha_decomp.md` 显示 2018-2026 OOS 段 T2 Calmar 比静态低 `0.05` (`0.81 vs 0.86`)。旧报告的 `-0.18` 是 2026-04-20 数据快照。
  - dashboard 用法: 可以做可选 scenario toggle, 不要默认接入。

- [ ] 雪球散户/Top30 vs Bottom30 反向信号
  - 状态: 方向性 lesson 可信, 正向跟随不可信。
  - 老数字: `docs/quant_strategy_lessons.md` 记录 Top30 约 `0.7%`, Bottom30 约 `7.5%`, 差 `-6.8pp`。
  - 新证据: `research/smart_consensus/verdict_2026-05-24_foundation.md` 将 A1/H2/H3/H4 全部 REJECT; A1 foundation alpha 仅 `+0.15%/period`, `t=+0.12`; matched `+0.57%/period`, `t=+0.70`。
  - 最新 diagnostic: `research/smart_consensus/output/contrarian_diagnostic_2026-05-25.md` 显示 `bot_decile_smart - top_decile_smart` annualized `+0.33%`, `t=+0.09`; avoid-top excess annualized `-0.80%`, `t=-0.23`。当前 strict evidence 不支持继续引用旧 `-6.8pp`。
  - caveat: 当前 corrected smart_consensus 链路主要使用 `research/attention_orj/cache/rebalancing/*.json` -> `build_signal.py` -> foundation, 不是直接用 sparse `data/cubes.db` 重算 `-6.8pp`。`test_contrarian.py` 可做 diagnostic, 但不是 fully matched verdict。
  - dashboard 用法: 可做「不要追随热门组合」教育模块或反向情绪提示, 不要做交易推荐。

- [ ] SRF v2 Xueqiu gate 12日弱正异常
  - 状态: 有弱正迹象, 但不是生产。
  - 证据: 2026-05-25 新增 `.venv/bin/python -B research/foundation/run_xueqiu_legacy_foundation.py --seeds 1,42,99 --hold-bdays 10,12,15 --rebuild-panel`; 输出 `research/factors_v2/output/xueqiu_legacy_v6_foundation.md`。
  - 数字边界: `srf_v2_gate_top15_no_goflat` 在 hold=12, seed 42/99 上 Test alpha `+1.08%/期`, `t=2.05/2.11`; 但 hold=10 和 hold=15 的 OOS t 全部 < 2。
  - 深查: `research/factors_v2/output/srf_v2_hold12_deep_audit.md` 显示 date-mean hold=12 Test matched alpha `+1.063%`, `t=2.15`, 但 Bonferroni over 9 tests 后 p `0.3232`; by-year 无一年独立显著, second-half t 只有 `0.76/1.09/1.21`, 且最强贡献来自上涨 regime 而不是原始 choppy thesis。
  - caveat: 这是典型 hold_step sensitivity / multiple-testing red flag。它只说明「SRF v2 是 research-only anomaly」, 不说明可以交易或接 dashboard。
  - dashboard 用法: 不接 alpha; 最多作为 research backlog。

- [ ] baseline_v6_1 live validation historical claim: `53.76%`
  - 状态: 文档数字, 本地不可复现。
  - 证据: `run_live_validation.py` 依赖 `data/battle_trades_all.csv`, 但当前仓库未找到该文件或对应 `live_validation_srf_summary.csv` / `live_validation_srf_by_date.csv`。
  - dashboard 用法: 不要展示为已审计 KPI; 只能标成 `baseline_v6_1 live validation historical claim` / 待重跑。

- [ ] Foundation OOS hard rail
  - 状态: 规则有效, 但「代码硬强制」表述过强。
  - 证据: `Backtest.__init__` 的 `train_test_split` 默认 `None`; self-test 会检查 split, 但构造函数不强制抛错。
  - dashboard 用法: audit page 可以显示「OOS required by project protocol」, 不要写成「API 无法绕过」。

- [ ] README/ARCHITECTURE 的「当前生产」声明
  - 状态: 部分过时。
  - 证据: README 2026-04-28 的全天候生产声明仍大体有效; CLAUDE.md 和 ARCHITECTURE.md 仍残留 v5/v6 smart-money / SRF / baseline_v6_1 生产语境, 已被后续证伪和 cycle001/002 覆盖。
  - dashboard 用法: 以 git log + 最新 audit/verdict 为准, 不直接信 README/ARCHITECTURE 的生产描述。

- [ ] Cycle002 I-B1 可转债数据
  - 状态: 数据抓取/coverage 较完整, 尚未有策略 verdict。
  - 证据: `b6dd495 impl(cycle002 §2.5): coverage manifest — 608 valid double_low + 332 redeem`; `research/foundation/_sync/control.md` 指向 `CYCLE002_I_B1_FETCHER_COMPLETE_DRAFTING_VERDICT`。
  - dashboard 用法: 可以列入 research backlog, 不接入生产。

- [ ] all-weather 回测数字随数据日期变化
  - 状态: 策略框架可信, 具体数字需要随 CSV 刷新重算。
  - 证据: README 静态 `7.43% / -18.96%`; 当前 `2026-05-18` 数据复现为 `7.36% / -19.4%`。
  - dashboard 用法: 展示指标时记录 data as-of date, 不写死 README 数字。

- [ ] IC-only 因子 diagnostic: MAX / BAB / reversal
  - 状态: 2026-05-25 已用 `.venv/bin/python` 跑通, 但不是 foundation verdict。
  - 证据: `research/factors_v2/run_max_factor_ic.py`, `run_bab_factor_ic.py`, `run_reversal_ic.py`; 输出 CSV 当前被 `.gitignore` 忽略。
  - 当前数字: MAX IC `+0.0294` 但 net top ann `-2.72%`; BAB stack net CAGR `+20.13%` 但 MDD `-61.49%`; reversal hs=12 net CAGR `+18.29%` 但 MDD `-68.26%`。
  - caveat: 这些脚本没有 foundation random/matched control、正式 OOS gate、same-universe alpha attribution; `build_broad_panel` 当前只加载成功 `828/5051` stock files。
  - dashboard 用法: 不接入。若未来继续研究, 先迁移到 foundation 再看。

- [ ] Clean factor / GOOD28 / MAX56_OK
  - 状态: 旧 diagnostic 跑出过非常漂亮的 `clean_dist A` 数字, 但 foundation 重跑不支持。
  - 旧数字: `.venv/bin/python -B research/factors_v2/run_clean_factor_backtest.py` 显示 clean_dist A `CAGR_net +27.33%`, `MDD -38.69%`, `Calmar 0.706`。
  - 严格重跑: `research/foundation/run_clean_factor_foundation.py` + `research/factors_v2/output/clean_factor_foundation.md`。
  - 当前数字: dist_a seed 1/42/99 Test alpha `-0.19%/+0.18%/-0.46%`, t `-0.38/+0.41/-0.61`; hvbal_b seed42 Test alpha `-1.35%`, t `-1.92`; combo_z seed42 Test alpha `-0.24%`, t `-0.35`。
  - caveat: Foundation engine 是季度截面回测, 旧脚本是 12 交易日自有 loop; 这不是逐行复制旧执行, 而是用当前 hard rails 验证信号是否能穿越 random/OOS/cost。
  - dashboard 用法: 不接入; 旧高 CAGR 视为 legacy loop artifact。

## ❌ 过时资产（不要接入）

- [ ] 雪球 v5/v6 SRF、baseline_v6_1、hold_step=12 生产配置
  - 原因: CLAUDE.md/ARCHITECTURE 残留 smart-money / SRF 生产语境; README 已把 `baseline_v6_1/` 降为遗留审计可复现目录。`prod_config.py` 自己也写明修后 long-only 年化约 `~2%`, MDD `-45%~-50%`, 成本 `9.8%/yr` 吃掉 gross alpha。
  - 可用边界: 数据和信号定义还可用于研究迁移。`data/cubes.db` 有 8,070 条 success rebalancing、1,350 个 stock_symbol, `data/stock_data` 有 5,051 个价格文件; 但必须抽出 `factor_z/factor_z_neu/regime/SRF v2 score` 后用 foundation 重跑。
  - 禁止: 直接复跑旧 `_build_rebalance()` / `_apply_risk_controls()` / `Top30-Bottom30` / asymmetric choppy go-flat 后当生产数字。
  - 最新重跑: `research/foundation/run_xueqiu_legacy_foundation.py` 已按 B2-style timestamp shift、真实 56bp 成本、same-universe random + size/turnover matched control、hold 10/12/15、seed 1/42/99 重跑。旧 follow Top30 与 contrarian Bottom30 均未通过; SRF v2 只有 hold=12 的弱正异常, 10/15 不稳。
  - 结论: 不要接入 dashboard 作为生产策略。

- [ ] `22.9% / 31% CAGR` 等高收益雪球回测数字
  - 原因: 修复前视/幸存者/事件回填等问题后大幅坍缩; 2026-05-24 foundation verdict 已 REJECT。
  - 结论: 只能作为「为什么要 audit」案例。

- [ ] `research/smart_consensus/verdict_2026-05-23.md` 的 A1 VALIDATED 结论
  - 原因: 2026-05-24 foundation verdict 和 git log 已明确 retraction。
  - 结论: 以 `research/smart_consensus/verdict_2026-05-24_foundation.md` 为准。

- [ ] 12 单因子库作为 alpha source
  - 当前最新证据: 2026-05-25 已新增并运行 `research/foundation/run_factor_battery_foundation.py`, 输出 `research/factors_v2/output/factor_battery_foundation_report.md`。
  - 结果: 11/12 因子为负或不显著; 小盘 SMB 在 Test 段弱正 `+6.44%/期`, `t=+2.31`, 但 Train 段反向 `-6.25%/期`, `t=-2.95`, Full alpha 只有 `+0.49%/期`, `t=+0.24`。
  - SMB 复验: `research/foundation/run_smb_sensitivity_foundation.py` 已跑 seed/size-bucket 矩阵; broad 30-500 的 Test t 为 `0.99/2.31/0.60`, small 30-100 为 `1.55/1.29/0.53`, mid 100-500 为 `1.79/1.63/1.61`。
  - 结论: 不要接入生产。SMB 弱正不稳健, 最多保留研究观察。

- [ ] 低波单因子正向 alpha
  - 证据: `research/factors_v2/output/low_vol_foundation_validation.md` 已于 2026-05-25 用 `.venv/bin/python` 重跑; Full alpha `-0.32%`, `t=-0.59`; Test alpha `-0.52%`, `t=-0.77`。
  - 结论: 不要作为独立信号。

- [ ] H1/H8 一进二板策略
  - 证据: `research/factors_v2/output/first_board_suite.md` 已于 2026-05-25 重跑, 覆盖 H1/H1b/H3; `research/factors_v2/output/first_board_executable.md` 记录 H8 可执行版首板战法; 合并看 75,290 events。
  - caveat: H1 T+1 open Full alpha `-0.18%`, `t=-9.89`, net `-0.49%`; H1b T 日 close 抢板在数学上仍强正 alpha `+2.06%`, `t=+82.27`, net `+0.30%`, 但依赖尾盘抢板成交、封板未炸、真实排队/滑点, 不等于普通散户可执行策略。
  - 结论: 不要接入。

- [ ] H9 教学规则策略
  - 证据: `research/factors_v2/output/h9_textbook_rules.md` 已于 2026-05-25 重跑; base alpha `-0.13`, `t=-6.97`; ALL 765 events alpha `-1.47`, `t=-7.25`, net `-1.51`。
  - 结论: 不要接入。

- [ ] 52-week high 动量因子
  - 证据: `research/factors_v2/output/52w_high_foundation.md` 已于 2026-05-25 重跑; Train alpha `+2.63%/期`, `t=+0.78`; Test alpha `-4.52%/期`, `t=-0.86`; Full alpha `-1.17%/期`, `t=-0.36`。
  - 结论: Train 正向不显著且 OOS 反转, 不要作为独立信号。

- [ ] H5 cubes-behavior / smart-pool 轴
  - 证据: cycle002 git log `36d3184 audit(codex): accept H5 B8 stop and pivot I-B1`; axis stability reports BLOCK。
  - 关键数字: H5 V2 composite median rotation `54.4%/Q`; turnover-only median rotation `43.7%/Q`; rolling ann_gain axis median rotation `33.7%/Q`。
  - 结论: 被 B8 axis-stability gate 拦截, 不接入。

- [ ] T6 dd_cut emergency-brake 变体
  - 原因: all-weather OOS 脚本定位为过拟合反面教材, 不是生产候选。
  - 结论: 不接入。

- [ ] ARCHITECTURE.md 的 smart-money current production 架构
  - 原因: 文档 last updated 2026-04-10; 后续 2026-05 methodology audit 已推翻核心假设。
  - 结论: 只作为历史架构阅读。

- [ ] 根目录 `long_history_4asset.csv`
  - 原因: 文件不存在; 真实路径在 `research/factors_v2/output/long_history_4asset.csv`。
  - 结论: 外部接入不要引用根目录路径。

- [ ] `all_weather_oos.py` 里 T2 标注「生产」的文案
  - 原因: 与 README 2026-04-28 和 `run_all_weather_signal.py` 默认行为矛盾。
  - 结论: 以 signal 脚本默认和 README 的 `--t2` 可选说明为准。

- [ ] `research/factors_v2/run_all_weather_signal.py` 钉钉文案里的旧回测数字
  - 原因: `build_markdown()` 仍写 T2 `Full CAGR 8.59% / Calmar 0.49` 和 Static `Full CAGR 8.11% / Calmar 0.42`。
  - 当前事实: 本轮复现是静态 `7.36% / -19.4% / Calmar 0.38`; T2 `8.18% / -17.4% / Calmar 0.47`。
  - 结论: 信号/推送入口可用, 文案数字过时。dashboard 不要复用这段 copy。

- [ ] `research/attention_orj/cache/DATA_STATUS_2026-05-23.md` 的 `A1 VALIDATED`
  - 原因: 文件仍写 IC `-0.0164`, `+13.91%/yr`, OOS `+40%`; 但 2026-05-24 foundation verdict 已正式 retracted。
  - 结论: 只可作为历史事故证据, 不可引用为当前结果。

- [ ] `archive/unusable_2026_05_25/docs/quant_concepts_guide.md` 的 v6.1 教学数字
  - 原因: 仍写 production baseline Calmar `0.28`, live win rate `53.76%`, Phase2 Calmar `0.10 -> 0.48`。
  - 结论: 教学概念可读, 里面的 v6.1/SRF/Phase2 生产数字过时或不可复现。

- [ ] `research/baseline_v6_1/prod_config.py` / `archive/unusable_2026_05_25/research/baseline_v6_1/code/wire_phase2_winner.py` 旧生产入口
  - 原因: `prod_config.py` 仍标 `Active production branch`; archived `wire_phase2_winner.py` 会按最高 Calmar 自动 patch 旧 v6.1/SRF 配置。
  - 当前事实: v6.1/SRF 已被 legacy foundation-compatible rerun 降级; 旧 go-flat/Calmar 选择流程不满足当前 hard rails。
  - 结论: dashboard 不要调用这些旧生产入口; 只可读信号定义做研究迁移。

- [ ] baseline v4/v5/v6.1 锁定/Phase 报告里的生产候选
  - 典型路径: `archive/unusable_2026_05_25/research/baseline_v4_2/report/baseline_v4_2_lock.md`, `archive/unusable_2026_05_25/research/baseline_v5/report/baseline_v5_lock.md`, `archive/unusable_2026_05_25/research/baseline_v6_1/report/phase2_research_report.md`, `archive/unusable_2026_05_25/research/baseline_v6_1/report/phase_d_validation_report.md`。
  - 旧数字: v4.2 Calmar `0.180671`; v5 Calmar `0.359286`; Phase2 asymmetric choppy Calmar `0.480`; PhaseD OOS best Calmar `0.353` 但可信度只有 `30/100`。
  - 结论: 全部归入 v4-v6 历史候选, 不接入 dashboard。

- [ ] `research/factors_v2/output/v2_findings_2026_04.md` 的短窗口生产候选
  - 旧数字: low_vol + overlay `CAGR_net 14.65% / Calmar 0.26`; DIV70/GEM30 `CAGR_net 15.15% / MDD -17.61% / Calmar 0.86`; DCA 估值加权 + 季度再平衡 IRR `14.2%`; CB 等权近一年年化 `30.1%`。
  - 当前事实: 低波单因子 foundation 已 REJECT; DIV/GEM 已被 30/30/40 四资产全天候取代; CB 数字只是市场温度快照, 不是 alpha。
  - 结论: 只能作为 2026-04 探索日志, 不作为 dashboard 策略资产。

- [ ] `archive/unusable_2026_05_25/docs/factor_learning_notes_2026_04.md` 的因子学习数字
  - 原因: 仍写 `low_vol因子`「对了 (`CAGR_net 13.17%`)」, 但当前 foundation 重跑显示低波 Full alpha `-0.32%`, Test alpha `-0.52%`, 不支持生产级正 alpha。
  - 结论: 概念解释可读, 具体 low_vol 结论过时。

- [ ] `archive/unusable_2026_05_25/docs/hybrid_signal_mining_system.md` / `archive/unusable_2026_05_25/docs/credibility_scorer_prompt.md` 的历史胜率加权框架
  - 原因: 仍把「历史胜率 > 70%」或 `backtest_report.csv` 胜率作为观点权重来源; 但早期 B 站荐股原始数据缺失, 现有 `archive/unusable_2026_05_25/analysis/backtest_report.md` 只支持负面历史摘要, 不支持生产可信度打分。
  - 同类归档: `archive/unusable_2026_05_25/docs/V2_0_IMPLEMENTATION_GUIDE.md`, `archive/unusable_2026_05_25/docs/AI_Model_Architecture.md`, `archive/unusable_2026_05_25/docs/ocr_processor_prompt.md`, `archive/unusable_2026_05_25/docs/clean_and_rank_prompt.md`。
  - 结论: 不要把这套 hybrid scorer / OCR scorer 接入 dashboard; 最多作为早期系统设计档案。

- [ ] 早期 B 站荐股/荐股博主流水线
  - 当前事实: `archive/bilibili_legacy/` 只有 56K 代码档案, 无 CSV/JSON/DB 原始数据; `core/extract_signals.py`, `core/backtest_engine.py`, `archive/bilibili_legacy/core/bili_collector.py` 需要 `dataset_videos.csv`, `dataset_comments.csv`, `trading_signals.csv`, `backtest_report.csv`, `ocr_results.csv` 等输入。
  - 恢复检查: `find /Users/johnnyzhang/jz_code`, `mdfind`, `git rev-list --all`, `git log --all --name-status` 均未找回这些输入; `.gitignore` 忽略 `*.csv` / `*.json`, 大概率从未入库。
  - 已有摘要: `archive/unusable_2026_05_25/analysis/backtest_report.md` 只记录 278 笔、胜率 `24.5%`, 累计收益 `-91.85%` 的负面结果。
  - 结论: 当前 checkout / 本地 `jz_code` workspace 不可用最新方法重跑; 不接入 dashboard。

- [ ] `archive/unusable_2026_05_25/research/cube_attention_delta/verdict_2026-05-21.md` 的 momentum_short 乐观判断
  - 原因: 05-21 写 `momentum_short` 可能补数据后通过 2σ; 05-23 补齐 full data 后已 REJECT。
  - 当前数字: 05-23 full-data v2 momentum_long Test IC `+0.0018`, Test t `+0.76`; Test long-only signal gross `+16.64%` vs random `+16.61%`, excess `-0.016%/wk`。
  - 结论: 以 `research/cube_attention_delta/verdict_2026-05-23.md` 为准; 05-21 只作 superseded 记录。

## 🔍 待验证（我没时间深查）

- [ ] 小盘 SMB 的 matched-control 复验
  - 状态: 12 因子 battery 已用 foundation 首轮重跑, seed/size-bucket 二次复验不支持生产级 alpha。
  - 需要: 若要继续深挖, 只剩 size/liquidity matched control 和更长样本; dashboard 当前不要接入。

- [ ] baseline_v6_1 live validation `53.76%`
  - 状态: 文档声明存在, 本地缺少源交易记录和验证输出。
  - 需要: 找回或重建 live validation dataset。

- [ ] Cycle002 I-B1 策略 verdict
  - 状态: coverage/fetcher 已推进, verdict drafting 尚未关闭。
  - 需要: 等 `research/foundation/_sync/control.md` 从 drafting 进入 accepted/rejected verdict。

- [ ] README 静态 `7.43% / -18.96%` 的精确复现条件
  - 状态: 当前数据 as-of `2026-05-18` 复现为 `7.36% / -19.4%`。
  - 需要: 用 README 当时数据快照或旧 CSV hash 复跑。

- [ ] Foundation attack registry 的剩余防线
  - 状态: D1 已在 `ff680e4` / `9c97b11` 中修到 upstream + registry, B8 axis-stability gate 已 ACTIVE; 但 B6 event-driven clustered standard error 仍是 `AUDIT_FINDINGS_2026_04_27.md` 的 Pending; B7 tie-order bias 只在 self_test 的 NULL factor 局部 mitigated, 不是 `CrossSectionalStrategy.select()` framework-level 修复。
  - 需要: 若未来用 event-driven 高密度同日事件或大量 tied factor, 必须新增日级聚合/cluster SE 和 framework-level stable jitter 后再给生产 verdict。

- [ ] `research.foundation` 在 dashboard Python 3.9 环境下的兼容性
  - 状态: bili 当前用 `.venv/bin/python 3.12.13` 跑通; 系统 `python3` 是 3.9.6, dashboard 也可能是 Python 3.9。
  - 需要: 在 dashboard venv 中 import/run self_test, 或通过 bili 自己的 `.venv/bin/python` subprocess 隔离。

- [ ] `run_all_weather_signal.py --push` 的真实发送
  - 状态: 代码路径存在; 未发送真实钉钉消息。
  - 需要: 用户配置 `config.py` 或环境变量后人工确认。

- [ ] `data/market_cache/` 与 long_history 的刷新链路
  - 状态: cache 文件存在; 本轮未重跑 fetcher。
  - 需要: 明确数据刷新命令、数据源、失败 fallback 和 dashboard 更新频率。

- [ ] 5-asset all-weather / SP500 扩展
  - 状态: `.venv/bin/python -B research/factors_v2/all_weather_5asset_oos.py` 当前失败。
  - 证据: 缺 `research/factors_v2/output/long_history_5asset.csv`。
  - 需要: 先重建 5 资产真实 NAV 数据, 再复验。dashboard 当前不要接。

- [ ] CB lead-lag / 双低可转债方向
  - 状态: `docs/cb_leadlag_alpha_research_report.md` 明确只是研究方案; cycle002 I-B1 还在数据/coverage/verdict drafting 阶段。
  - 需要: 历史全量转债、点时转股价、强赎/下修事件、成本后 OOS 和 random control。
  - dashboard 当前不要接。

- [ ] Cube attention delta/momentum/accel 源矩阵复现
  - 状态: 05-23 verdict 已 REJECT, 但当前 checkout 缺 `research/cube_attention_delta/output/factor_delta.csv`, `factor_momentum.csv`, `factor_accel.csv`。
  - 需要: 若要从源头重跑, 需重建 factor matrices; 当前只能依赖已生成的 `final_summary_v2.csv` 和 verdict。

## 6 类证伪策略审计表

| 类别 | 最新可信路径 | 是否被 cycle002 反转 | 当前结论 |
| --- | --- | --- | --- |
| 雪球散户 / smart consensus | `research/smart_consensus/verdict_2026-05-24_foundation.md`; `research/factors_v2/output/xueqiu_legacy_v6_foundation.md`; `docs/quant_strategy_lessons.md` | 否。cycle001 全 REJECT; cycle002 H5 被 B8 BLOCK; legacy SRF 最小重跑不支持生产 | 不可正向 follow; SRF v2 仅 research backlog; 可作为反向情绪/lesson |
| 12 因子 | `research/foundation/run_factor_battery_foundation.py`; `research/factors_v2/output/factor_battery_foundation_report.md`; `research/factors_v2/output/smb_sensitivity_foundation.md` | 已更新: 11/12 REJECT; SMB 弱正经 seed/size 复验不稳健 | 不接入 |
| 低波 | `research/factors_v2/output/low_vol_foundation_validation.md` | 无反转证据 | REJECT |
| 一进二板 H1/H8 | `research/factors_v2/output/first_board_research_summary.md` | 无反转证据 | REJECT |
| 教学规则 H9 | `research/factors_v2/output/h9_textbook_rules.md` | 无反转证据 | REJECT |
| T2 动量 overlay | `research/factors_v2/output/all_weather_alpha_decomp.md`; `run_all_weather_signal.py` | 没有被证明废弃, 但已降级为可选 | 可运行但非默认; dashboard 只能作为 scenario |

## 5 个引擎 bug 修复状态

`git log --oneline | grep -i "B[1-5]"` 会命中 I-B1/H5 等周期名, 还会把两套不同的 B 编号混在一起, 必须手工过滤。

Foundation 引擎 bug 的权威口径不是五个独立 B1-B5 commit, 而是 `B1-B4 + 防御保护`:

- `8e44ad6 feat(foundation): 二轮审计 + H8/H9 严格证伪首板战法`
  - commit body 明确写: `backtest.py B1-B4 修复: exit_idx 多算 1 天 / n_random_repeats 默认 1 / event random ±90 日窗口 / cross_sec random pool 排除 picks`。
  - `research/foundation/AUDIT_FINDINGS_2026_04_27.md` 记录 B1-B4 + 防御保护: B1 EventDriven 多持仓 1 天; B2 random repeat 抬高 t-stat; B3 event random 跨全时期; B4 cross-sectional random 没排除 picks; 防御为 `alpha_std` 退化样本/零除保护。
  - 当前 `research/foundation/backtest.py` 仍可见 B2/B4 注释和实现: 默认 `n_random_repeats=1`, random pool `universe_df[~code.isin(picks)]`。
  - 判定: foundation 引擎 B1-B4 + 防御保护已修, self-test 7/7 通过。但 README 口语化成「5 个 bug」会造成 B5 编号误读; 严格写法应是 B1-B4 + defensive guard。

2026-05-23/24 smart_consensus methodology audit 还有另一套 B 编号, 不等同于 foundation engine B1-B4:

- `a541049 feat(B1-builder): cube NAV history + rolling 12M ann_gain reconstruction`
- `96f9226 fix(B1-integration): build_signal.py uses rolling ann_gain per-bucket smart filter`
- `5dd1225 fix(B2): signal entry = first tradable day after latest in-bucket event; rebuild fwd_ret with same convention`
- `ce94ba4 fix(B3-i): mask IC on raw signal contribution, not rank-pct (which was all-non-NaN)`
- `afb9222 fix(B3-ii): exclude CB (可转债) prefixes from signal panel`
- `2e8605d fix(B3-i Step 5): align long-only backtest mask with Step 3 IC`
- `3ad587c fix(B5-i): NaN delisted stocks' weekly close instead of carrying forward`

结论: 引擎级修复是真的, smart_consensus later fixes 也是真的; 但编号体系混乱。接入 dashboard 时不要展示「B1-B5 全部逐项 commit」这种说法, 要按具体 bug 描述引用。

## Cycle002 最新状态

- MORNING_BRIEF 说 cycle001 全 REJECT, cycle002 PROPOSED; 当前 git log 已推进到 cycle002 执行后期。
- HEAD 前 10 个 commit 显示:
  - `4dae699 chore(cycle002): commit per-bond data, single-brain launcher, codex H2 report`
  - `b6dd495 impl(cycle002 §2.5): coverage manifest — 608 valid double_low + 332 redeem`
  - `1a38370 impl(cycle002 §2.5 v1): fetcher mode-split per Codex NEEDS-FIX`
  - `2acb44f audit(codex): require I-B1 fetcher universe split`
  - `7c46faf impl(cycle002 §2.5 v0): I-B1 fetcher + KNOWN selection bug + scope sync`
  - `36d3184 audit(codex): accept H5 B8 stop and pivot I-B1`
  - `11d79bc impl(cycle002 phase1 v2): H5 axis on 926-cube pool fails B8 in both forms`
  - `492a19a BLOCK(codex): reject H5 axis smart-pool leakage`
  - `db3df2f impl(cycle002 phase1): H5 composite axis values for B8 audit`
  - `147a1a2 sync(claude): CYCLE002 LAUNCH α — control.md → RUNNING, IMPL Phase 1 starting`
- H5 / cubes-behavior: BLOCK, not production.
- I-B1: coverage/data stage promising, no final accepted strategy verdict.
- B8 axis-stability gate: active and decisive; H5 被它拦下。

## 推荐接入顺序 (for dashboard integration)

1. 第一优先: 30/30/40 静态全天候 + 16 年真实 NAV。
2. 第二: foundation 框架, 用于 dashboard 的 audit page / strategy validation page。
3. 第三: 4 条硬规则, 做 status bar 或教育模块。
4. 第四: 6 类证伪 lessons, 防止 dashboard 误接 v5/v6 遗留 alpha。
5. 第五: `cubes.db`, 仅作为 sentiment / contrarian indicator 原始素材, 且默认打警告。
6. 第六: 钉钉推送, 只在用户配置 webhook 后接入 signal alert。
7. 不要接入: v5/v6 雪球 SRF、12 因子库、一进二板、教学规则、H5 cubes-behavior、T6。

## 接入风险与边界

- Python 版本: 当前机器 `python` 不存在; 系统 `python3` 是 3.9.6; bili 本轮可靠执行器是 `.venv/bin/python 3.12.13`。dashboard 若是 Python 3.9, 建议通过 subprocess 调 bili `.venv/bin/python`, 或只读 CSV/SQLite。
- 数据量: 整 repo `3.1G`, `data/` `1.2G`; 全天候最小接入只需 `research/factors_v2/output/long_history_4asset.csv` 约 `395K` 和静态权重。
- 依赖隔离: 只接全天候 CSV 不需要 foundation; 接 foundation 策略验证可能需要 stock/fundamental data bundle 和 repo 相对路径。
- 股票数据偏差: foundation 的 A 股 stock universe 仍有退市股 OHLCV 缺失, 所有股票 alpha 展示前要扣 `1-3%/yr` survivorship discount; 全天候 ETF NAV 不受这个 caveat 影响。
- 钉钉 webhook: `config.py` 当前不存在, `config.example.py` 只有空字段; 生产推送必须由用户在本地配置或用环境变量注入。
- 数据 as-of: 当前 long_history 截止 `2026-05-18`; dashboard 展示任何 CAGR/MDD 都必须显示这个日期。
- `cubes.db`: 55,306 cubes 是真; live win rate 不属于 cubes.db 可验证指标, smart ranking 绩效也不是本轮可复现事实。

## 关键风险提醒

- README.md 写的「当前生产」若与最新 git log、signal 脚本、foundation verdict 冲突, 以后者为准。
- 任何 alpha > 10% 的历史回测必须先问: 有没有 random control、OOS、真实成本、前视/幸存者检查。
- cycle002 仍在推进, 但截至 HEAD 没有产生可替代 30/30/40 的新生产策略。
- `cubes.db` 的正确接入姿势是「研究素材 + 反向情绪 caveat」, 不是「智能资金跟随策略」。
- dashboard 第一版应该只接静态全天候和审计 lessons; 不要让 v5/v6 的漂亮数字重新进入产品。
