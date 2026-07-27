# Cycle 002 Proposals (spawned from Cycle 001)

Generated 2026-05-24 after Cycle 001 verdict (A1+H2+H3+H4 all REJECT). The skill axis on cubes data is exhausted; cycle 002 opens two parallel new directions.

---

## Locked default selection (per Codex 03:20 + Claude 03:30 alignment)

### Track A — H5 Behavioral Adverse Selection (cubes resurrection)

**Owner**: Codex (he proposed; behavior axis design is his domain)
**Spec**: hypothesis_registry.yaml#H5
**Thesis**: 历史高换手 / 晚入场行为模式的 cubes 在某只股出现异常 attention (价格 + 成交量 spike) 后买入,该股下 N 日跑输严格 matched controls。
**Critical changes from cycle 001**:
- ABANDONS skill axis entirely (this was the L9 lesson from cycle 001 negative_log)
- Selector = behavioral pattern (turnover percentile / lag vs lead cubes / entry timing relative to abnormal attention)
- Matched control includes board + liq decile + size decile + 20d momentum decile + industry
- Cycle 002 H5 = cubes + **1 additional A-share proxy** (Codex's phased D1 counter-spec). 4-proxy version deferred to cycle 003.
**Confirmation proxy candidate**: 融资买入 (margin trading buy-in) by stock if stock-day coverage is stable; otherwise 龙虎榜 (top-5 broker disclosure) if event sparsity acceptable.
**Decision rule**: H5 not VALIDATED unless mechanism survives at least 2 proxies, OR single-proxy result is labeled INCONCLUSIVE_PENDING_CONFIRMATION.

### Track B — I-B1 可转债套利 (canonical catalog kickoff)

**Owner**: Claude (转债 infrastructure code-heavy)
**Source**: `~/jz_code/research_log/inefficiency_hunting.md` I-B1 catalog entry
**Catalog rank**: 🥈 主菜首选 (Johnny's evidence ✓✓ mechanism, ✓ sub-strategies)
**Expected yield range**: 2022-2024 精细策略 5-15%/yr (per catalog)
**Sub-strategies in scope for cycle 002 verification**:
- 双低策略 (low conversion premium + low absolute price)
- 强赎博弈 (anti-callaway anticipation)
- (defer 折价套利 + 下修博弈 to cycle 003 if 002 hits budget)
**Data sources**: akshare 转债 listing/info + 集思录 history + 巨潮 公告 抓取
**Infrastructure scout**: per inefficiency_hunting Phase 2 commands:
```bash
cd ~/jz_code/research_log
python3 repo_scout.py search "可转债 akshare tushare 数据" --limit 15 --out domains/bonds_t0/infra_data
python3 repo_scout.py search "巨潮 公告 爬虫" --limit 15 --out domains/bonds_t0/infra_news
python3 repo_scout.py search "可转债 回测 backtrader vnpy" --limit 15 --out domains/bonds_t0/infra_backtest
```
**Attack registry to clear**: B5-i (NaN for halt / 违约 转债, not 0), B5-ii (违约转债 historical inclusion), and a new attack candidate "强赎事件公告抓取时延 (1-3 day decay window)".

---

## Cycle 002 cross-cutting work

### Track C — Cross-market data-contract scout (Codex D3 partial accept)

**NOT** a cycle 002 verdict track. Codex's D3 ruling: cross-market H5 needs data-contract docs first before becoming a verdict family.

**Deliverable**: `research/foundation/_engine/data_extensions/cross_market_late_chasing.md` — define:
- How does "late chasing after attention" map to (funding rate, Polymarket open interest)?
- Data contracts: timestamp granularity, signal object, holding horizon, cost model per market
- Sanity check command for each data source

**Owner**: Claude (design only); DeepSeek consultant **available for design review** but not for live track ownership (Codex D3 explicit).

After Track C deliverable passes both agents' design review → cycle 003 owns the cross-market H5 verdict family.

---

## Cycle 003+ preview (not selected yet)

### Already QUEUED but not in cycle 002 selection
- I-A1 国债逆回购 (catalog 🥇 起手必做) — easy verify, low priority because already deployable
- I-A2 打新 — easy verify
- I-B2 ETF 折溢价套利
- I-C1 期权 VRP (blocked on 50万门槛 for live; backtest OK)

### Already PROPOSED, not yet QUEUED
- H5 expansion: 北上资金 + 龙虎榜 (after H5 cycle 002 success)
- H6 dumb-cube anti-signal (still skill axis — likely dies same as A1)
- H7 cube portfolio concentration (Herfindahl)

### Future-cycle infrastructure work
- `proposer.py` ML factor mining via AlphaForge + qlib Alpha158 (Codex D2 accepted with guardrails: PROPOSED-only, prior 0.05, lineage logged, max 10/epoch, future-field auto-REJECT). Suggested cycle 003 if Tracks A/B leave budget.
- `_engine/paper_book/` paper-trading tier implementation (Codex D4 accepted). Suggested cycle 003+ once any VALIDATE produces a candidate.
- `fetch_fundamentals.py` upstream fix to pre-filter panel A-share only (D1 attack)

---

## Cycle 002 budget plan

- Wall time: 24 hours from cycle 002 launch.
- Token budget: 5M total across both agents.
- Soft stop at 80%, hard stop at 100%.
- Mandatory checkpoints: 
  - end of Track A H5-cubes baseline (single proxy) backtest
  - end of Track A H5-confirmation proxy backtest
  - end of Track B I-B1 双低 baseline backtest
  - end of Track B I-B1 强赎 baseline backtest

---

## External proposals queue (not in cycle 002, but stocked for future)

WebSearch / arxiv / research_log/repo_scout pulls to be done at cycle 002 retrospective:
- "Chinese mutual fund herding alpha" (arxiv)
- "social copytrade anti-signal" (SSRN)
- "A-share margin trading attention spike" (CFA 等)
- Quantopian community archived strategies for retail-microstructure inspirations

Track these in `external_proposals_inbox` of hypothesis_registry.yaml.

## H5 Design Priors — Literature (ingested 2026-05-24)

Pre-cycle-002 WebSearch surfaced concrete academic priors that directly inform H5 (Behavioral Adverse Selection):

### Primary references

1. **Barber & Odean (2008)** — "All That Glitters: The Effect of Attention and News on the Buying Behavior of Individual and Institutional Investors" — the canonical paper establishing attention-driven retail buying. Retail investors disproportionately buy stocks that catch their attention (extreme returns, high volume, news mentions). The buying creates short-term price impact that reverses.
   - H5 implication: late chasing after price+volume spikes is a documented phenomenon, not a speculative hypothesis.

2. **"Does social media information affect individual investor disposition effect? Evidence from Xueqiu"** — PLOS One 2025-07-28 (DOI: 10.1371/journal.pone.0328547) — **direct empirical study on Xueqiu** (our data source). Examines how Xueqiu social media exposure changes investor disposition behavior.
   - H5 implication: there is a published-2025 baseline for Xueqiu-specific behavioral effects we can compare H5 results against.

3. **"Active attention, retail investor base, and stock returns"** (Research in International Business and Finance, 2024) — formalizes how retail attention drives stock-level demand and return.
   - H5 implication: attention spikes (price + volume + news) are operational proxies for the mechanism H5 targets.

4. **"Herding Behavior in Chinese Stock Markets" — Demirer & Kutan (SSRN 2148613)** — A-share-specific herding is empirically stronger than Western markets, driven by retail dominance and sensitivity to informal information.
   - H5 implication: A-share is one of the cleanest markets to test attention-chasing anti-signal.

5. **"Coevolution of Trader Networks and Follower Dynamics in Social Trading"** — Liu, Yang, Tan (SSRN 4528456) — model of how follower networks amplify lead-trader signals with lag.
   - H5 implication: the lag-vs-lead-cube selector candidate from H5's hypothesis_registry entry has theoretical backing.

### What this changes for H5 design

- The "abnormal price + volume after which cube buys" threshold is no longer a guess. Barber & Odean use **top decile of past-week return + volume**. Adopt that as H5's primary trigger (top decile, not 2σ).
- The PLOS One 2025 Xueqiu paper provides a **direct baseline** for "social media info effect on Xueqiu investors". If H5 finds an effect with magnitude similar to that paper's published numbers, that's external corroboration. If we find none, our null is consistent with theirs.
- Lag-vs-lead cube feature is THEORETICALLY motivated (Liu et al.); not just a fishing expedition.
- A-share retail attention-anti-signal effect is well-documented (Demirer & Kutan); we are reproducing in a sub-population (cubes), not discovering.

### Implication for H5 prior_pr_alpha

Previously written as 0.30. With these priors (canonical mechanism + 2025 Xueqiu paper + lag-network theory), revising upward to **0.40** for the cubes proxy specifically. Multi-proxy confirmation (Codex's phased D1) gates whether it promotes to VALIDATED.

### What this does NOT change

- H5 still must pass **B8 axis-stability audit** on its behavioral selector (turnover percentile / lag) before running. The skill axis failed B8 (33.7%/Q rotation); the behavioral axis must be independently checked.
- Matched control (board + liq + size + momentum + industry) still required.
- 1-3%/yr survivorship discount still applies.
- Codex's phased "cubes + 1 confirmation proxy" requirement (NOT all 4 proxies at once) stands.
