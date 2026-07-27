# Phase 0 Gate — Sync between Codex & Claude (2026-05-23)

**Status**: GATE BLOCKED. Both audits stopped at `DataBundle.load()` failure.
**Owner**: Codex (this file) + Claude (parallel session). Johnny is bridging.

---

## 1. Confirmed ground truth (no need to re-verify)

| Path | State |
|---|---|
| `data/fundamentals/` | **不存在** — 整个目录缺失 |
| `data/fundamentals/panel_quarterly.csv` | **不存在** — 全 repo 搜不到, .gitignore 里 (从未提交) |
| `data/stock_data/` | 存在但 **0 个文件** |
| `research/attention_orj/cache/daily_k/` | 5,001 个 csv, 2022-01-04 → 2025-06-30 |
| `research/attention_orj/cache/daily_k_pre2022/` | 4,250 个 csv, 2014-01-02 → 2021-12-31 |
| OHLCV 实际数据源 | daily_k 衔接 pre2022 = 2014-2025 ~5,028 unique codes |
| `.venv/bin/python` | pandas 3.0.3 / numpy / scipy 全装好 |
| Rebuild scripts | `research/data_prep/update_stock_data.py` (baostock OHLCV) + `research/factors_v2/fetch_fundamentals.py` (akshare panel) |

Johnny 已选路径 A: **全量重建** (而非改 foundation 契约).

---

## 2. Fast-path 已否决 (不要再考虑)

之前 Claude 想 "merge daily_k → data/stock_data/ 省 1-3 小时", 但发现:

- daily_k schema = `date,open,high,low,close,volume` (6 列), **无 `turn` 换手率列**
- `research/foundation/universe.py:133`:
  ```python
  if "turn" not in pf.columns or len(past20) < 10: continue
  ```
- 没 turn → universe.at() 把所有股 continue 掉 → universe 永远空 → backtest 跑不出 → self_test 全 fail

结论: **必须走 baostock 重拉 (有 turn 字段)**. 没有捷径.

---

## 3. 立即启动 (无需 Codex 同意)

`fetch_fundamentals.py` (akshare, ~10-20 分钟, 走 raw_yjbb cache):

```bash
cd ~/jz_code/bili_stock
.venv/bin/python research/factors_v2/fetch_fundamentals.py
```

产出: `data/fundamentals/panel_quarterly.csv` (~30+ 季度, ~150k 行).
不论选什么路径都要做这步, 无 trade-off.

---

## 4. 需要 Codex 在 30 秒内表态的 3 件事

### Q1. `update_stock_data.py:22` 的 TARGET_END
当前硬编码 `2026-04-18`, 今天 2026-05-23. 改成 `2026-05-23` 拿最新数据?
- **建议**: 改. 一行 patch, 不影响逻辑.

### Q2. update_stock_data 只下 cubes.db 里出现过的股 (line 80-100)
不是全 A 股 5000. 这是否够 self_test universe `mcap_range=(30,200)` 样本量?
- **风险**: cubes.db 里出现的 ~1,373 unique stocks 可能 mcap 偏离 30-200亿区间, universe 抽完后样本不够
- **缓解**: pre2022 cache + daily_k cache 合计 5,028 unique codes 已经在本地. 如果 cubes.db 子集不够, 可以把 daily_k 数据 enrich 进 baostock 增量拉的格式 (借现成 close 算近似 turn = volume / mcap, mcap 来自 panel)
- **建议**: 先按 cubes.db 跑, 完了看 universe.at() 实际 yield 多少股. 如果 <50, 再考虑 enrich

### Q3. baostock 跑的 1-3 小时, Codex 怎么用?
**建议**: 平行开 B1-B5 静态代码审计:
1. **B1 look-ahead**: `research/smart_consensus/build_signal.py:47-58` 用 trader_profile.csv (2026 snapshot 的 ann_gain_rate, followers_count) 筛 96 cubes, 然后这个名单回测到 2022. 量化 bias.
2. **B2 forward alignment**: build_signal.py 把 `created_at` (Unix ms) → `strftime('%Y-W%W')` → `pd.to_datetime(week+'-1', '%Y-W%W-%w')` 转成"周一". 这个 week 跟 `forward_returns_v2.csv` 的 index 怎么对齐? Tuesday 调仓的 signal 有没有 leak 到当周 close.
3. **B3 universe**: `forward_returns_v2.csv` 列数 vs `smart_consensus_ffill.csv` 列数, CB/ETF/STAR 漏过滤多少.
4. **B4 random**: build_signal.py:186-212 每周 row-shuffle 30 次. 跟 foundation `Backtest(random_control=True)` 的同 universe 抽样比, 哪个更严.
5. **B5 survivorship**: daily_k + pre2022 合计 27 个退市候选 (only-pre2022) vs AUDIT_FINDINGS 估计真实 ~150. 量化 inflation.

Codex 不用跑代码, 静态读 build_signal.py + test_contrarian.py + verdict 就能出 finding. 这 1-3 小时不浪费.

Claude 这边平行: 写 baostock 启动 + 监控脚本, 拉到 ~50% 时跑一次 self_test 看 universe.at() yield, 决定要不要 enrich.

---

## 5. Codex 表态后启动顺序

```
T+0min:   Codex 表态 Q1/Q2/Q3 → Claude 启动 fetch_fundamentals + update_stock_data
T+20min:  fetch_fundamentals 应当完成, panel_quarterly.csv 就位
T+1-3hr:  update_stock_data 完成, data/stock_data/ ~1,373+ csv
T+3hr:    跑 self_test, 7 项验证
T+3hr+:   Codex B1-B5 audit 出 finding → 两人 RECONCILIATION
T+4hr:    METHODOLOGY_AUDIT_2026-05-23.md 定稿, Phase 0 PASS
```

如果 Codex 在 5 分钟内不表态, Claude 按 "建议" 列默认推进 (Q1=改, Q2=先按 cubes.db 跑, Q3=平行 B1-B5).

---

## 6. 死线 / Hard rails (重申)

- Phase 0 PASS 之前不跑任何 alpha 工作 (不验证 A1, 不做 size strat, 不做 liquidity filter)
- t > 2 但 universe < 50% 覆盖 = 必须怀疑
- 5%+ alpha 必须先扣 1-3%/yr 退市股偏差
- 不 silent merge: 两人 finding 不一致 → 写 RECONCILIATION 段, 不和稀泥

---

**Last update**: Claude session, 2026-05-23
