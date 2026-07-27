# Alpha Discovery Engine — Master Spec v0

**Authors**: Claude (Opus 4.7) + Codex (GPT-5.5), bridged by Johnny Zhang.
**Birth date**: 2026-05-24.
**Mission statement** (per Johnny 2026-05-24):

> 在 bili_stock 中完成 A1 家族的最终方法学裁决,并把研究流程升级成可复用、可审计、可扩展的 alpha 发现引擎。

This is NOT a one-shot verdict exercise. It is a **long-running engine** whose external state (registries, logs, benchmark suite) accumulates across cycles. Two AI agents co-evolve by feeding the engine, not by being trained.

---

## 1. Vision

The 9-month single-hypothesis-at-a-time approach to A1 produced one numerically impressive verdict that turned out to be 4 stacked CRITICAL bugs. The diagnosis is structural: **the workflow had no immune system**. There was no attack-registry that would have caught the mask bug. There was no kill-criterion library that would have hard-stopped at "weekly IC mask is on rank.pct = all-non-NaN". There was no negative-log to remember that "+22pp test-period delta with no size control = strong prior on size beta".

This engine fixes that. Each cycle leaves behind durable artifacts so the next cycle starts smarter. **The model doesn't get smarter; the repo does.**

---

## 2. Architecture

```
research/foundation/_engine/
├── ENGINE_SPEC.md              ← this document (the constitution)
├── hypothesis_registry.yaml    ← all hypotheses ever proposed, status, score
├── attack_registry.yaml        ← all methodology pitfalls ever identified
├── negative_log.md             ← REJECTED verdicts with root-cause attribution
├── lessons_learned.md          ← cross-cycle methodology insights
├── next_cycle_proposals.md     ← candidates for the cycle after current
├── proposer.py                 ← future quarantined machine-factor proposal runner
├── paper_book/                 ← paper-trading logs for backtest-VALIDATED hypotheses
├── cycles/
│   ├── cycle_001_2026-05-24.md ← cycle plan + verdicts + retrospective
│   ├── cycle_002_<date>.md     ← next
│   └── ...
├── benchmark_baselines/
│   ├── null_factor.json        ← canonical NULL baseline numbers
│   ├── random_factor.json      ← canonical RANDOM baseline
│   └── ...                     ← every cycle adds its baselines
└── data_extensions/
    └── <pull-task>.md          ← when current data inadequate, define pull task
```

All files are git-tracked. State evolves through commits. Two-agent coordination uses `_sync/PROTOCOL.md` (separate).

---

## 3. Hypothesis lifecycle

States in `hypothesis_registry.yaml`:

```
PROPOSED       → just suggested by an agent (Claude / Codex / Johnny / external)
QUEUED         → on deck for next cycle
RUNNING        → in current cycle, partial results
VALIDATED      → passed all 4 kill criteria + survived attack registry
REJECTED       → failed one or more criteria; root-cause documented in negative_log
DEFERRED       → blocked on data/method; awaiting data_extension task
ARCHIVED       → superseded by a stronger formulation
PAPER          → backtest-VALIDATED, now logging real-time paper trades
DEPLOYABLE     → PAPER realized >= 50% of backtest expectation after 3 months
FAILED_LIVE    → PAPER realized < 50%; demote and root-cause in negative_log
```

Each entry minimum schema:
```yaml
- id: A1
  status: RUNNING
  thesis: "smart cubes 重仓股下周跑输大盘"
  type: cross_sectional
  proposer: johnny
  proposed_date: 2025-08
  prior_pr_alpha: ~25%       # subjective estimate at propose time
  posterior_status: under-audit-2026-05-24
  dependencies: [cubes_data, panel_quarterly]
  attacks_resolved: [B1, B2, B3-i, B3-ii, B5-i, B7]
  attacks_pending: [B3-iii, B5-ii]
  verdict: null              # null until VALIDATED/REJECTED
  archive_link: null
```

Promotion rules:
- PROPOSED → QUEUED requires: thesis is testable, data exists or pull task defined, at least one prior probability estimate from each agent.
- QUEUED → RUNNING requires: in current cycle's selection, kill criteria explicit.
- RUNNING → VALIDATED/REJECTED requires: meets §6 hard gates AND both agents agree.
- Disagreement freezes status as RUNNING; escalates to Johnny.

---

## 4. Attack registry

`attack_registry.yaml` is the engine's immune memory. Every methodology pitfall ever discovered lives here forever. New hypotheses MUST run against the full attack registry before VALIDATE.

Schema:
```yaml
- id: B3-i
  name: "rank-pct mask bug"
  discovered: 2026-05-23
  discovered_by: claude
  cycle: 001
  description: |
    `mask = f_row > 0` on a rank-pct frame evaluates to all-non-NaN.
    IC then tests selection effect not rank skill.
  test: |
    For any factor that involves cross-sectional ranking + mask, verify
    that mask is on RAW factor value not rank. Replicate IC with mask
    flipped and confirm meaningful change.
  prevented_examples: []     # filled as future cycles report "B3-i caught this"
```

Initial population (this cycle's audit findings):

```yaml
- id: B1
  name: "snapshot-based smart-cube selection (forward-look)"
- id: B2
  name: "event timestamp backdating"
- id: B3-i
  name: "rank-pct mask bug"
- id: B3-ii
  name: "CB/STAR/北交所 universe contamination"
- id: B3-iii
  name: "random-control not size/liq matched"
- id: B4
  name: "row-shuffle random control with cross-shuffle std underestimation"
- id: B5-i
  name: "delisted stock fwd_ret = 0 instead of NaN"
- id: B5-ii
  name: "delisted stock OHLCV under-coverage"
- id: B7
  name: "CrossSectionalStrategy tie-order bias when factor returns are tied"
- id: D1
  name: "akshare panel includes 北交所/B-shares that baostock OHLCV doesn't cover"
```

---

## 5. Cycle protocol

A cycle is a closed loop of: select → implement → attack → verdict → accumulate.

```
1. SELECT: pull top-K hypotheses from QUEUED, write to cycles/cycle_NNN.md.
   K determined by token/time budget; default K=4.
2. IMPLEMENT (Claude lead):
   - Write strategy code in research/foundation/strategies_<id>.py
   - Wire into foundation.Backtest with random_control=True + OOS split
   - Commit + document in cycle file
3. ATTACK (Codex lead):
   - Run full attack registry against each strategy
   - Run ablation: each fixed bug isolated, confirm collapse direction
   - Run sensitivity: parameter perturbation, time-period robustness
   - File findings in cycle file
4. VERDICT (both):
   - Apply §6 kill criteria
   - Both agents independently grade: VALIDATE/REJECT/INCONCLUSIVE
   - If disagreement → escalate to Johnny + freeze
   - If REJECTED → negative_log.md entry with root-cause
5. ACCUMULATE:
   - Update hypothesis_registry.yaml (status + verdict + attacks)
   - If any new pitfall surfaced → add to attack_registry.yaml
   - If any cross-cycle insight → lessons_learned.md
   - Spawn next cycle proposals → next_cycle_proposals.md
6. RETROSPECTIVE: short cycle wrap-up in cycle file, signed by both agents.
```

---

## 6. Hard kill criteria (per hypothesis)

These are NOT subjective. Any one fires → REJECT, no override:

1. **Foundation self_test 7/7 not passing for the data/framework state used** → STOP. Fix infrastructure first.
2. **Train and Test alpha disagree in sign** (one positive one negative significant) → REJECT. Not stable.
3. **alpha_mean ablated against any single attack in registry returns ≥ 80% to baseline** (e.g., remove B3-i and IC goes from -4.97 back to -0.5) → REJECT. The "alpha" was the bug.
4. **Survivorship-discounted + cost-applied annualized net alpha < 0** → REJECT. Real net negative.

Plus 1 soft criterion that triggers human review (not auto-reject):
- Annualized alpha > 10% after all fixes → MORE bug suspicion, demand additional ablation before VALIDATE.

### Deployment gate

`VALIDATED` means **backtest-validated**, not capital-ready. No hypothesis may be called deployable until it passes a paper tier:

1. Promote VALIDATED → PAPER.
2. Log paper entries/exits in `_engine/paper_book/<id>/` for 3 months using real-time executable prices.
3. Compare realized paper alpha to backtest expectation after costs.
4. Promote PAPER → DEPLOYABLE only if realized paper alpha is at least 50% of backtest expectation and no new attack-registry issue appears.
5. Otherwise demote PAPER → FAILED_LIVE and record the root cause in `negative_log.md`.

Machine-generated factors from future `proposer.py` are quarantined: they may enter `hypothesis_registry.yaml` only as low-prior PROPOSED items and cannot skip any attack, matched-control, self-test, OOS, or paper-tier requirement.

---

## 7. Cycle budget + engine-level kill switches

- **Token budget per cycle**: tracked; default ceiling 5M total across both agents per cycle. Soft warn at 80%, hard stop at 100%. (Engine cannot know token usage directly; agents self-report in cycle file.)
- **Time budget per cycle**: 24 wall hours default.
- **Engine-level kill switch**: if 5 cycles in a row all REJECT → escalate to Johnny "core data source may be dry; consider data extension or pivot".
- **Hypothesis ban**: if same id rejected 3 times across cycles with different attempts → ARCHIVE permanently.

---

## 8. Data extension protocol + leverageable infrastructure

The engine does NOT live in isolation. Johnny's `~/jz_code/` already contains:

### Tier 0 — primary canonical alpha catalog (highest priority for cycle seeding)
- **`~/jz_code/research_log/inefficiency_hunting.md`** — 6 graded canonical inefficiencies (A1 国债逆回购, A2 打新, B1 可转债套利, B2 ETF 折溢价, B3 funding rate, C1 期权 VRP). Higher prior probability than any experimental cubes hypothesis because evidence is ✓✓/✓. Cycle 002+ should pre-load from this. Already imported into `hypothesis_registry.yaml#canonical_inefficiencies`.
- **`~/jz_code/research_log/methodology.md`** — Johnny's 3-phase workflow (low-eff identify → GitHub infra scout → strategy write). Engine cycles map onto Phase 3 (verify via foundation). Don't reinvent.
- **`~/jz_code/research_log/studied_repos.md`** — third-party repo registry. Reference before re-cloning.
- **`~/jz_code/research_log/repo_scout.py`** — automated GitHub survey tool. Engine can shell out to this for cycle 002+ external-feed.
- **`~/jz_code/research_log/domains/`** — per-domain working dirs (打新, bonds_t0, etf_premium, funding_rate, options_vol, treasury_repo, _2week_replay, _cross_pollination).

### Tier 1 — alpha generation / ML backbones (ready to compose)
- **`~/jz_code/qlib/`** (1.3G INTEGRATED) — Microsoft Qlib with CSI300 data preloaded. Use for: Alpha158 reference factors, ML model integration, train/test pipeline.
- **`~/jz_code/AlphaForge/`** (DulyHao, RL/symbolic factor mining). Use for: cycle 002+ systematic factor generation.
- **`~/jz_code/QuantaAlpha/`** — alternative framework, useful for cross-validation.

### Tier 2 — existing strategies / pre-foundation code
- **`~/jz_code/bili_stock/core/`** — `factor_miner.py`, `bayesian_scorer.py`, `backtest_engine.py`, `data_provider.py` (pre-foundation; useful as reference + as legacy alpha sources to re-audit).
- **`~/jz_code/bili_stock/*.docx`** — `2026_年_A_股主流量化因子全景.docx`, `A股三类量化因子.docx`, `投资要点.docx` (Johnny's factor surveys). Hypothesis-bank import target for cycle 002+. NOTE: docx requires conversion (`textract` or `unzip + xml extract`) — add to engine tooling.

### Tier 3 — cross-domain methodology learning
- **`~/jz_code/Crypto_Research_Agent/`** (WW-shan) — already inspired `Literal[False]` execution-mode + `train/test gap_days` in foundation (per AUDIT_FINDINGS 2026-05-18). Mine for further methodology patches.
- **`~/jz_code/meme/`** (WW-shan) — `pipeline/train_hybrid.py` inspired `_split_lifecycle_files_three_way`.
- **`~/jz_code/Atlas20/`**, **`~/jz_code/LTT_Strategy/`**, **`~/jz_code/poly_strategy/`** — alternative-market methodology to back-port.
- **`~/jz_code/fundingRate/`** — actual deployable system for I-B3 catalog entry.

### Tier 4 — point monitors / alert infra (data feed candidates)
- **`~/jz_code/options_vol_lab/`** — options data + vol surface (for I-C1).
- **`~/jz_code/etf_premium_alert/`** — ETF IOPV monitor (for I-B2).
- **`~/jz_code/funding_rate_monitor/`** — already running for I-B3.
- **`~/jz_code/treasury_repo_alert/`** — for I-A1.
- **`~/jz_code/打新_alert/`** — for I-A2.
- **`~/jz_code/morning_briefing/`** — daily news/data summarizer.

### Tier 5 — wholesale data sources
- baostock (current OHLCV, free)
- akshare (current fundamentals, free)
- Tushare (paid, deeper history + minute data)
- Wind (paid, institutional)
- 雪球 cubes API (the cubes data this audit is built on)
- Tanglaoye historical OHLCV (PR #4 / #5)
- 网络/arxiv/SSRN/Quantopian (paper-mining for new hypothesis classes)

### Cycle data-extension protocol

When the current data is insufficient for a queued hypothesis:

```
hypothesis.status = DEFERRED
write data_extensions/<id>_<dataset>.md with:
  - what hypothesis needs
  - what data source candidates (with URLs, mapped to Tier 0-5 above)
  - cost/time estimate
  - sanity check command
On approval from Johnny, agent pulls data + reruns sanity → hypothesis unblocks to QUEUED.
```

The engine SHALL prefer existing local resources (Tier 0-4) before pulling new data (Tier 5).

---

## 9. Co-evolution mechanism

How the engine gets smarter without retraining models:

- **External-state-only evolution**: agents read registries at the start of every cycle, so what one cycle learned, the next applies.
- **Adversarial pressure**: Codex's attack role grows the attack registry; Claude's implementation role exercises it. They co-evolve through opposition.
- **Knowledge transfer**: when a new factor type is proposed, the attack registry tests it against ALL known pitfalls in one cycle. Without the registry, the same pitfalls would be re-discovered per hypothesis.
- **Negative-log mining**: end of each cycle, the negative_log accumulates "this hypothesis died because X". Patterns across N negative entries inspire new positive hypotheses (e.g., "after 5 size-beta-contaminated rejects, propose a size-neutral version of cube signal").
- **External feed-in**: web/arxiv/Quantopian survey at the end of each cycle adds external hypothesis to next_cycle_proposals. Cycle 2+ should pull at least 3 external candidates per cycle.

---

## 10. Roles (fixed)

| Agent | Role | What they write | What they CANNOT do |
|---|---|---|---|
| Claude (Opus 4.7) | **Implementer + replicator** | Strategy code, foundation wrappers, drivers, retraction notices, PR comments, infrastructure | Cannot single-handedly decide VERDICT |
| Codex (GPT-5.5) | **Attacker + auditor** | Ablation scripts, attack registry entries, sensitivity tests, independent verdict, methodology challenges | Cannot single-handedly decide VERDICT |
| Johnny | **Arbitrator + scope-setter** | Cycle budget, kill criteria amendments, data extension approval, disagreement resolution | — |

**Conclusions come from evidence + agreement, not consensus alone.** If both agents agree but evidence is thin → still REJECT/INCONCLUSIVE. If one agent disagrees with evidence → freeze and escalate.

---

## 11. Stopping conditions

- **Per-hypothesis**: §6 kill criteria.
- **Per-cycle**: hypothesis verdicts all reached OR §7 budget exhausted OR engine-level kill fired.
- **Engine-level (NEVER PLANNED)**: only stops when (a) one hypothesis VALIDATES with net annualized alpha > 3% after all discounts, repeatable across cycles AND (b) Johnny explicitly closes the engine. **The engine does not stop just because a cycle fails.**

This last point matters: Johnny said *不允许失败*. That doesn't mean every hypothesis succeeds; it means **the engine doesn't quit**. A cycle full of REJECTs is fuel for the next cycle.

---

## 12. Cycle 001 — A1 family

The current work (PHASE_1_PLAN.md v1 at e87f9df) becomes **Cycle 001**. Its 4 hypotheses (A1 + H2 + H3 + H4) are this cycle's selection. The plan's §2/§6/§9 fold into this engine's framework:
- §2 thresholds = §6 kill criteria (this engine).
- §9 4 hypothesis = `cycles/cycle_001_2026-05-24.md` selection.
- Cycle's negative_log entries go into `negative_log.md` (engine-wide).

After Cycle 001 verdicts, Cycle 002 spawns from:
- A1-family pivots if any VALIDATEd (e.g., size-neutral A1, A1 with industry-neutralization).
- External feed (arxiv / Quantopian / GitHub repo_scout — already memory-noted at `~/jz_code/research_log/`).
- Negative-log patterns (e.g., if H2/H3 both die on "event clustering not informative", propose alternative cube-data dimension).

---

## 13. Sign-off + launch protocol

This ENGINE_SPEC needs sign-off from all three:

- [ ] **Claude**: I've written it; I commit my agreement by being the implementer signed onto §10.
- [x] **Codex**: review §6 kill criteria (your domain) + §10 attacker role + §11 stopping conditions; sign-off granted. Guardrail: size/liquidity-matched random must be a required baseline in every cycle artifact, not just a sensitivity.
- [ ] **Johnny**: spec matches your stated ambition; budget + data sources approved.

After sign-off:
1. Commit `cycles/cycle_001_2026-05-24.md` (subsumes PHASE_1_PLAN.md v1).
2. Launch `/goal until 'cycle_001 verdicts committed per ENGINE_SPEC §6 kill criteria + spawn cycle_002 proposals'`.
3. The engine runs.

**Do NOT launch /goal before all three sign-offs are recorded in this file.**
