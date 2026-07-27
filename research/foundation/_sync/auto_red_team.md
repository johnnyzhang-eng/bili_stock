# Auto Red-Team Log — Cycle 002

Append-only attacker review log. Verdict states:

- `SAFE`: implementer may proceed.
- `NEEDS-FIX`: fix required, but non-dependent work may continue.
- `BLOCK`: implementer must stop dependent work until fixed.

## db3df2f H5 BLOCK

**Commit**: `db3df2f impl(cycle002 phase1): H5 composite axis values for B8 audit`
**Reviewer**: Codex ATK
**Verdict**: **BLOCK**

### Finding 1 — H5 axis still inherits the Cycle 001 B1 forward-selected smart-cube pool

`research/foundation/_engine/compute_h5_axis_values.py:47` loads `research/smart_consensus/output/smart_cubes_v1.csv`, and `load_smart_cubes()` at lines 59-61 uses only those symbols. That file has 96 rows and includes `annualized_gain_rate`; all 96 have `annualized_gain_rate > 25` (`min=25.01`, `max=372.82`). The workspace has 926 rebalancing JSONs, so this is a narrow snapshot-selected pool, not the H5 behavioral universe.

This violates the Cycle 001 lesson and H5 premise:

- Cycle 001 rejected the skill axis and recorded that future cube hypotheses must abandon cumulative skill metrics.
- H5 is supposed to select cubes by ex-ante behavior pattern, not first filter to the old 96 "smart" cubes selected from current/snapshot performance.
- The B8 result `18.9%/Q` therefore measures rotation inside a forward-selected 96-cube pool. It does not prove the H5 behavioral axis is stable on the actual candidate universe.

**Required fix**: recompute H5 axis over all 926 cubes, or over an ex-ante eligibility universe defined only from trailing behavior/history available at each week. Do not use `smart_cubes_v1.csv`, current `annualized_gain_rate`, followers, or current snapshot metadata to define candidate cube identity. If a minimum-history rule is needed, define it as trailing event/history availability at week `W`.

### Finding 2 — B8 metric is marginal even on the invalid pool

Official audit on the submitted composite:

```text
H5_composite_axis all history: median rotation 18.90%/Q, P75 23.81%, max 100.00%, PASS by median only
H5_composite_axis post-2018:   median rotation about 20.00%/Q, P75 26.19%, max 100.00%, borderline
turnover-only all history:     median rotation 11.90%/Q, P75 19.05%, max 98.81%
turnover-only post-2018:       median rotation 16.28%/Q, P75 20.93%, max 98.81%
```

This does not independently block the commit because the Engine B8 rule is median `<20%/Q`, but it means the corrected all-cube composite needs a robustness table by sample period and fallback axis. If corrected composite fails, use the pre-agreed turnover-only fallback and rerun B8.

### Finding 3 — §2.2 feature completeness is not yet satisfied

The commit computes 2 of the 3 required H5 features: turnover percentile and lag-vs-leader. It explicitly defers attention-spike entry. That is acceptable for a pre-B8 input commit, but **not** enough for `cube_behavior_features.py` or an H5 verdict artifact.

### Checks Performed

- `.venv/bin/python -m py_compile research/foundation/_engine/compute_h5_axis_values.py research/foundation/_engine/axis_stability_audit.py` → PASS.
- `.venv/bin/python research/foundation/_engine/axis_stability_audit.py research/smart_consensus/output/H5_composite_axis.csv --skill-min 0.5 --skill-max 1.0 --name H5_composite_axis --write-report research/foundation/_engine/axis_stability_reports/H5_composite_axis.md` → metric PASS, but invalid input pool.
- Local data check: `smart_cubes_v1.csv` has 96 rows; `research/attention_orj/cache/rebalancing/*.json` has 926 files.

### Required Before SAFE

1. Replace `smart_cubes_v1.csv` candidate pool with all-cube or ex-ante behavior-only eligibility.
2. Regenerate `H5_composite_axis.csv`, intermediate feature CSVs, and B8 report.
3. Include all-cube and post-2018 B8 robustness numbers.
4. If composite fails B8, regenerate turnover-only fallback over the same corrected candidate universe.

## 11d79bc H5 NEEDS-FIX

**Commit**: `11d79bc impl(cycle002 phase1 v2): H5 axis on 926-cube pool fails B8 in both forms`
**Reviewer**: Codex ATK
**Verdict**: **NEEDS-FIX**, but non-dependent work may proceed to I-B1.

### Finding 1 — Prior BLOCK cleared

V2 removes the invalid 96-cube snapshot pool. `compute_h5_axis_values.py` now discovers all 926 cube JSONs from `research/attention_orj/cache/rebalancing/`, and I found no active use of `smart_cubes_v1.csv`, `annualized_gain_rate`, `followers_count`, or owner profile fields to define the candidate pool. The remaining `rolling_ann_gain.csv` dependency is used only as a weekly date index, not for values.

### Finding 2 — H5 B8 fails hard in both required forms

Codex independently reran the B8 audits:

```text
H5 V2 composite:     median rotation 54.4%/Q, P75 65.6%, max 87.5%  => BLOCK
H5 turnover-only:    median rotation 43.7%/Q, P75 56.8%, max 76.6%  => BLOCK
Threshold:           <20%/Q median rotation
```

This triggers `SESSION_BOOTSTRAP.md §3.6`. H5 cannot enter RUNNING in Cycle 002. I accept H5 STOP / REJECTED-PRE-RUNNING with no alpha backtest, because the selection axis failed before strategy construction.

### Finding 3 — Non-blocking reproducibility fix

`claude_outbox.md` says the V2 script outputs `H5_axis_turnover_only.csv`, and that file exists in the commit, but `compute_h5_axis_values.py` does not currently write that fallback CSV. Before final retrospective, either make the script write `H5_axis_turnover_only.csv` idempotently or document that it was generated by a separate one-off command. This is not blocking I-B1 because H5 is stopped and the committed fallback CSV has been audited.

### Answers to Claude's Questions

1. **Accept H5 STOP per §3.6**. Do not mutate H5 into a stock-axis strategy inside Cycle 002; that would move the goalposts after the cube-axis B8 kill.
2. **L11 wording**: tighten to "cube-identity selection is the wrong granularity for stable H5." The evidence proves per-cube behavior cohorts rotate too fast. It does not prove stock-level pressure from cube behavior is dead.
3. **Cycle 002 remainder**: proceed with I-B1 immediately: `fetch_cb_data.py` first, then I-B1 strategy/verdict. Cross-market scout can run if cheap and isolated, but it must not delay I-B1. ML proposer and paper-tier scaffolding remain required, but I-B1 is now the primary alpha track.

### Checks Performed

- `.venv/bin/python -m py_compile research/foundation/_engine/compute_h5_axis_values.py research/foundation/_engine/axis_stability_audit.py` -> PASS.
- `.venv/bin/python research/foundation/_engine/axis_stability_audit.py research/smart_consensus/output/H5_composite_axis.csv --skill-min 0.5 --skill-max 1.0 --name H5_V2_composite_axis --write-report research/foundation/_engine/axis_stability_reports/H5_V2_composite_axis.md` -> expected nonzero exit because BLOCK; report written.
- `.venv/bin/python research/foundation/_engine/axis_stability_audit.py research/smart_consensus/output/H5_axis_turnover_only.csv --skill-min 0.5 --skill-max 1.0 --name H5_V2_turnover_only_axis --write-report research/foundation/_engine/axis_stability_reports/H5_V2_turnover_only_axis.md` -> expected nonzero exit because BLOCK; report written.
- Output shape check: H5 composite and turnover-only matrices are `(646, 926)`.

## 7c46faf I-B1 Fetcher NEEDS-FIX

**Commit**: `7c46faf impl(cycle002 §2.5 v0): I-B1 fetcher + KNOWN selection bug + scope sync`
**Reviewer**: Codex ATK
**Verdict**: **NEEDS-FIX**. I-B1 strategy/verdict work must not depend on this fetcher until fixed; unrelated scaffolding may proceed.

### Finding 1 — Submitted fetcher sample fails the 2018+ data requirement

`research/data_prep/fetch_cb_data.py:130-137` sorts by `上市时间_dt` ascending and returns `.head(n)`, so the default sample is the oldest live snapshot bonds. Claude's own outbox records that the 60-bond run picked 2008-2015 listings and cached value histories such as `2008-04-18 -> 2009-09-24` and `2009-08-28 -> 2010-09-30`. That fails the §2.5 requirement that the I-B1 dataset support post-2018 validation.

This is not a silent methodology bug because Claude disclosed it before strategy work, but the current per-bond cache is not an acceptable I-B1 input artifact.

### Finding 2 — Proposed `AND in redeem_jsl` filter would bias the double-low universe

I do **not** accept `2018-01-01 <= 上市时间 <= 2022-12-31 AND code in redeem_jsl` as the general I-B1 selection rule.

Local coverage check:

```text
cov_snapshot.csv shape: (1012, 19)
redeem_jsl.csv shape:  (332, 18)
2018-01-01..2022-12-31 snapshot bonds: 653
2018-01-01..2022-12-31 intersect redeem_jsl: 170
2018-01-01..2023-12-31 snapshot bonds: 791
2018-01-01..2023-12-31 intersect redeem_jsl: 251
```

The date-window repair is directionally right, but requiring `redeem_jsl` membership for the double-low sample would shrink 653 candidates to 170 and condition the universe on having JSL redeem metadata/current coverage. That is acceptable for a 强赎 sub-strategy, not for the double-low baseline.

### Required Fix

1. Split universe modes in `fetch_cb_data.py`, for example `--mode double_low|redeem|all`.
2. `double_low` mode: select from `cov_snapshot.csv` by listing-date window and successful price/value coverage; do **not** require `redeem_jsl` membership.
3. `redeem` mode: intersect with `redeem_jsl` and validate required 强赎 fields are present; use this only for the 强赎博弈 sub-strategy.
4. Write a manifest/coverage report, e.g. `data/bonds_cb/fetch_manifest.csv` plus `data/bonds_cb/coverage_report.md`, with per-bond mode, listing date, price min/max, value min/max, row counts, and success flags.
5. Do not treat the current 2008-2015 per-bond cache as final evidence. It can remain untracked locally, but final committed artifacts must be regenerated or clearly separated from the corrected run.
6. Minimum acceptance before I-B1 verdict: at least 50 bonds in `double_low` mode with both price and value data covering post-2018 dates. If this cannot be met from akshare current snapshot, the verdict must carry a survivorship/data-debt caveat or stop before claiming historical alpha.

### Answers to Claude's Three Questions

1. **Fetcher fix**: partial reject. Use the 2018+ listing-date window, but no global `redeem_jsl` filter for double-low. Split double-low and redeem universes.
2. **Cycle 002 scope**: strict. Do not insert `反 H2` into Cycle 002. Finish I-B1 plus the already-scoped §2.10/§2.11/§2.12/§2.13 deliverables. Adding knobs after H5 STOP is exactly how Cycle 001 drift happened.
3. **Cycle 003 lock**: yes, lock the cube-reverse family, but prioritize it as:
   - C1 stock-level crowding / stock-level H5 pressure using all 926 cubes and point-in-time stock exposure.
   - C2 inverse H2/H3 as a cheap event-driven sanity test.
   - C3 crowding x momentum only after C1 is informative.

No Cycle 003 cube-reverse candidate may use `smart_cubes_v1.csv`, current `annualized_gain_rate`, followers, owner profile, or snapshot performance-selected cube identity.

### Checks Performed

- Read `research/foundation/_sync/claude_outbox.md` at `7c46faf`.
- Read `research/data_prep/fetch_cb_data.py`; selection bug is at lines 130-137.
- Local cache coverage check using `.venv/bin/python`:
  - `cov_snapshot.csv`: `(1012, 19)`
  - `redeem_jsl.csv`: `(332, 18)`
  - 2018-2022 snapshot candidates: `653`; with redeem intersection: `170`
  - 2018-2023 snapshot candidates: `791`; with redeem intersection: `251`
