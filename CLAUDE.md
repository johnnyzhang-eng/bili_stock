# Bili_Stock — Claude Project Context

## What This Is

A-share **LONG-ONLY** quant system tracking Xueqiu smart-money consensus signals. Core alpha: avoid trading in noisy (choppy) market regimes + SRF multi-factor stock selection within Xueqiu consensus gate.

- **55,000+ cubes** in cubes.db (真身在 `data/cubes.db`; 仓库根目录的 `cubes.db` 是 2026-05-24 意外创建的 0 字节空文件, 勿引用), 291 with rebalancing data, 1,373 unique stocks, 2014-2026
- **7,183 successful deduplicated trades** (after removing 887 duplicates)
- ~~Live validation win rate: 53.76%~~ — **DEMOTED to historical undocumented claim (2026-07-02)**: 底层数据遗失不可复现 (RERUN_LEDGER_2026-05-25.md 处方已执行). 未来任何 live 声明必须走 `research/foundation/live_ledger.py` (append-only + hash chain + provenance).

---

## Production Performance (Honest Numbers — NO look-ahead bias)

**Backtest: 2015-2025 (cubes data starts 2014), LONG-ONLY, realistic costs, inverted factor**

| Metric | Value |
|---|---|
| **Annual Return** | **~2%** (averaged across all start-date offsets) |
| **Max Drawdown** | **-45% to -50%** |
| **Calmar Ratio** | **0.04-0.05** |
| **Win Rate** | **~47%** |
| **Annual Trading Cost** | **9.8%** (83% turnover × 56bp round-trip) |
| **Zero-cost Alpha** | **5.3%** (signal works but costs eat it) |

### Critical Findings
- **Previous 22.9% was fake**: go-flat mechanism used future returns (look-ahead bias)
- **Factor is INVERTED**: Top30 (high consensus) returns 0.7%/yr, Bottom30 (low consensus) returns 7.5%/yr
- **Cost is the bottleneck**: 5.3% raw alpha minus 9.8% cost = negative after-cost return
- **hold_step sensitivity remains**: calmar swings wildly across adjacent values
- **Randomized start test**: hold_step=12 positive in 92% of offsets (most stable)

---

## Production Config

Centralized in `research/baseline_v6_1/prod_config.py`.

| Param | Value | Meaning |
|---|---|---|
| `hold_step` | 12 | rebalance every 12 business days (stable in 10-15 range) |
| `cap_non_up` | 0.10 | max 10% of picks from one industry (non-bull) |
| `cap_up` | 0.20 | max 20% from one industry (bull regime) |
| `liq_other` | 0.60 | keep top 60% by liquidity via `liq_rank_pct` |
| `non_up_vol_q` | 0.50 | vol filter: keep stocks ≤ 50th pct of \|ret20d\| |
| `dd_soft/mid/hard` | -5%/-7%/-10% | tighter drawdown brakes |
| `choppy_loss_scale` | 0.0 | go-flat on losing choppy periods |
| `use_srf_v2` | True | SRF v2 re-ranker within Xueqiu gate |
| `top_k` | 15 | select top 15 stocks per rebalance |
| `buy_cost` | 13bp | commission 3bp + transfer 0.2bp + slippage 10bp |
| `sell_cost` | 43bp | commission 3bp + stamp 10bp + transfer 0.2bp + slippage 10bp + impact 20bp |

**Regime threshold**: ±3% on HS300 ret20 (上涨 >3%, 下跌 <-3%, else 震荡)

---

## Phase Roadmap

| Phase | Status | What |
|---|---|---|
| Phase 1 | Done | Wire choppy_fix_B as production |
| Phase 2 | Done | Choppy optimization: asymmetric go-flat |
| Phase 3 | Done | Signal IC research, net_flow tested (failed), gray pipeline wired |
| Phase 4 | Done | 5 bug fixes, data foundation rebuilt, realistic cost model |
| Phase 5 | Done | SRF grid (top_k=15), regime ±3%, vol/DD tuning, northbound factor |
| QC | Done | Long-only fix, cost audit, hold_step sensitivity, go-flat overfitting check |

### QC Audit Results
- **No look-ahead bias** in factor_z, fwd_ret_2w, or regime classification
- **Go-flat is not overfitted**: 2015 crash it didn't trigger (classified as 下跌); 0% false kill rate on profitable periods
- **hold_step sensitivity is a red flag**: calmar swings 0.41-1.41 across hold_step 14-20
- **Transaction cost was critically underestimated**: 10bp→56bp round-trip changed ann_ret from 31%→23%

---

## Key Files

### Core Engine
| File | Role |
|---|---|
| `research/baseline_v6_1/code/run_baseline_v6_v61_suite.py` | Main engine: `_pick_top()`, `_build_rebalance()`, `_apply_costs()`, `_apply_risk_controls()`, `_metrics()` |
| `research/baseline_v5/code/run_baseline_v5_with_costs.py` | `_prepare_panel_v5()` — panel builder |
| `research/baseline_v4/code/run_baseline_v4_2_up_filter.py` | `_load_hs300()` (cached), `_apply_liq_dynamic()` |
| `research/factors/factor_rebalance_momentum.py` | Signal: count or net_flow mode, bdate_range |
| `research/data_prep/build_data_foundation.py` | Generate liquidity, industry, HS300 cache |
| `research/data_prep/update_stock_data.py` | Refresh stock OHLCV from BaoStock |

### Reports & Visualization
| File | Content |
|---|---|
| `research/baseline_v6_1/code/generate_visual_report.py` | Professional dashboard + 5 charts |
| `archive/unusable_2026_05_25/docs/quant_concepts_guide.md` | Archived plain-language guide with stale v6.1/SRF numbers |

---

## Architecture

```
cubes.db (status='success', deduplicated)
  → factor_rebalance_momentum.py  # net_buy_cube_count, factor_z (bdate_range)
    → _attach_base_fields()       # + industry_l2, amount, ret20d_stock
      → _industry_neutralize()    # + factor_z_neu
        → _apply_liq_dynamic() + _load_hs300(cached)
          # + regime(±3%), hs300_ret20, liq_rank_pct
          → _enrich_from_stock_data()
            # + vol_price_div5d, ret_intra5d, hv20_hv60_ratio, highconv_10d

panel → _run_one(hold_step=12, liq_other=0.60, risk_cfg)
  ├── filter liq_rank_pct <= 0.60
  └── _build_rebalance(hold_step=12)
        └── _pick_top(regime, top_k=15, use_srf_v2=True)
              ├── Xueqiu gate: rank >= 0.7
              ├── Vol filter: |ret20d| <= 50th percentile
              └── SRF v2 score: 49.5% consensus + 18% momentum + 13.5% intraday_rev
                                + 9% vol_price_div + 10% highconv
  └── _apply_costs(buy=13bp, sell=43bp)  # LONG-ONLY, asymmetric
  └── _apply_risk_controls()
        ├── market_hot: scale 0.5/0.7 in overheated bull
        ├── drawdown: scale 0.5/0.6/0.75 at -5%/-7%/-10%
        └── choppy: scale 0 on losing 震荡 periods
  └── _metrics()  # LONG-ONLY: based on Top30_net, not spread
```

---

## Conventions

- **LONG-ONLY**: A-shares have no short selling. All metrics based on Top30 return, NOT Top30-Bottom30
- **Regime**: `上涨` = bull (ret20>3%), `震荡` = choppy, `下跌` = bear (ret20<-3%)
- **Costs**: Asymmetric. buy_cost=13bp, sell_cost=43bp. Round-trip=56bp per unit turnover
- **factor_use**: `-factor_z_raw` in bull (contrarian), `factor_z_neu` in others (momentum)
- **Vol filter**: NaN `ret20d_stock` → treated as infinite vol (filtered out)

## What NOT to Do

- Don't use long-short metrics (Top30-Bottom30) — A-shares are long-only
- Don't trust IC alone — net_flow had IC=+0.005 but calmar=-0.014 in backtest
- Don't optimize hold_step beyond 10-15 range — results are unstable at 16-20
- Don't call `_prepare_panel_v5()` repeatedly — cache the result
- Don't run backtests >10min as Claude Code background tasks — they timeout
- Don't use one_way_cost<40bp — real A-share costs are ~56bp round-trip

## Backtest = use research/foundation, no exceptions

**Hard rail (2026-04-27 onwards)**: All new strategies MUST go through `research/foundation/`. Direct scripts that load OHLCV / panel and run their own backtest loops are PROHIBITED. The foundation package enforces:
1. `DataBundle.load()` runs data audit and raises `DataAuditFailure` if not OK
2. `Backtest()` constructor requires explicit `random_control: bool` (raises `MissingRandomControl` if missing)
3. `Benchmark.auto_for(universe)` matches benchmark to universe size tier (raises `BenchmarkMismatch` on mismatch)
4. `train_test_split` is a required parameter for OOS verification
5. `CostModel` is required (no zero-cost defaults)

**Standard workflow:**
```python
from research.foundation import DataBundle, Universe, CostModel, Backtest, CrossSectionalStrategy

data = DataBundle.load()                                    # Auto-audits
uni = Universe.small_cap(data, mcap_range=(30, 200))         # Explicit size tier
strat = CrossSectionalStrategy(name="my_factor", factor_fn=my_fn, top_pct=0.20, hold_days=180)
bt = Backtest(strategy=strat, universe=uni,
              cost_model=CostModel.a_share_retail_quarterly(),
              random_control=True,                            # MUST be explicit
              train_test_split=("2010-01-01", "2018-06-30"),  # OOS enforced
              n_random_repeats=30)
result = bt.run()
StandardReport.from_result(result).print()
```

**For event-driven strategies (limit-up, news, earnings)**: Use `EventDrivenStrategy` and pass to `Backtest`. The framework auto-generates same-stock random-day baselines.

**Self-test**: Run `python research/foundation/self_test.py` after any framework change. NULL/RANDOM factors must give |alpha| < 1% and |t| < 2; if not, framework has bugs.

## Backtest QC — historical context (now enforced by foundation)

**This project had a repeat failure pattern: backtest initially shows 5-20% alpha, QC reveals it's 0-2%. The foundation package above ENFORCES the rules below. They are kept here for historical understanding:**

### 1. Random control from same universe (STRICT)
Before comparing signal to any benchmark, build a parallel backtest that:
- Samples N random stocks from the SAME universe (same liquidity/size filters)
- Uses SAME date range and hold period
- Reports its own CAGR/Alpha/Win%

**True Alpha = Signal - Random Control, NOT Signal - HS300.**
If Signal ≈ Random Control, the "alpha" is just beta to the universe.

### 2. Benchmark must match universe
- HS300 is ONLY valid benchmark if universe is large-cap (mcap > 500亿)
- Small/mid-cap strategies: use CSI1000 (000852) or 中证2000, or random control from universe
- Never use HS300 for a small-cap signal — this single mistake alone inflates alpha ~5pp

### 3. Data coverage audit
Before running backtest, always compute:
- Panel股票总数 vs OHLCV 文件覆盖率
- If OHLCV coverage < 90%, the missing stocks are likely delisted → report separately
- If signal stocks can't be priced > 10% of time, adjust down estimates

### 4. Period selection disclosure
- 2017-2024 = small-cap bull cycle, results upward biased
- Must either include 2015-2017 bear in test, OR explicitly caveat forward expectations
- Monte Carlo using only bull period returns is NOT a forward forecast

### 5. Cost must be applied in Monte Carlo AND backtest
- Round-trip 56bp per position
- Each rebalance = 1.12% drag
- Applied BEFORE computing median terminal value

### Pre-flight checklist (must execute before showing user any alpha number)
```
[ ] Random control from same universe run in parallel?
[ ] Benchmark matches universe size tier?
[ ] OHLCV coverage % reported?
[ ] Period bias disclosed (bull-cycle, bear-cycle)?
[ ] Costs applied in all return calculations?
[ ] If all of above pass → then present result.
    Otherwise: investigate before showing user.
```

### When user says "this looks too good":
- Immediately run random control if not done
- Benchmark mismatch is the #1 culprit, check it first
- Second most common: survivorship bias in price cache
