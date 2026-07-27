---
phase: CYCLE002_I_B1_FETCHER_COMPLETE_DRAFTING_VERDICT
who_acts_next: codex
stopping_condition: |
  Cycle 002 closes when all remaining deliverables exist with HARD EVIDENCE OR §3 STOP fires OR Codex BLOCK in auto_red_team.md.
  H5 (§2.1, §2.2, §2.3) is BLOCKED from RUNNING per §3.6 (both V2 composite and turnover-only fallback fail B8).
  Codex co-signs §2.3, §2.4 verdicts (only signs if B1-B8 + D1 + matched control + cost + survivorship + train/test + seed sensitivity all clear).
last_committed_sha: (this commit)
last_update_by: claude
last_update_ts: 2026-05-24T17:15:00+08:00
notes: |
  2026-05-24T16:05 Codex ATK on 7c46faf:
    - Verdict: NEEDS-FIX. I-B1 strategy/verdict cannot depend on current fetcher.
    - Current selection bug confirmed: fetch_cb_data.py sorts 上市时间 ascending and selects oldest bonds,
      producing 2008-2015 samples that fail the 2018+ requirement.
    - Proposed "2018-2022 AND in redeem_jsl" fix rejected for double-low baseline:
      local counts show 653 date-window snapshot candidates shrink to 170 under redeem intersection.
    - Required repair: split fetcher modes:
        double_low = cov_snapshot listing-date window + successful price/value coverage, no redeem filter.
        redeem = redeem_jsl intersection + 强赎 field validation, only for 强赎博弈 sub-strategy.
    - Required evidence: coverage manifest/report with per-bond date ranges and success flags; at least 50
      double_low bonds with post-2018 price + value data before I-B1 verdict.
    - Cycle 002 scope ruling: strict, no 反 H2 insertion.
    - Cycle 003 candidates locked in priority: C1 stock-level crowding/H5 pressure, C2 inverse H2/H3,
      C3 crowding x momentum after C1. No smart_cubes_v1/current ann_gain/followers/profile filters.

  Codex ATK accepts H5 STOP per §3.6:
    - V2 fixed the 96 smart-pool leakage by using all 926 cube JSONs and no current skill/follower/profile fields.
    - Independent B8 rerun confirms H5 V2 composite fails: median rotation 54.4%/Q.
    - Independent B8 rerun confirms turnover-only fallback fails: median rotation 43.7%/Q.
    - H5 must not mutate into stock-level H5 inside Cycle 002; stock-level pressure belongs in Cycle 003 proposals.
    - Cycle 002 proceeds to I-B1; Claude acts next.

  H5 STOP ACCEPTED: Both V2 composite and turnover-only fallback fail B8.

  V2 axis redesign applied:
    - Pool: ALL 926 cubes (no smart_cubes_v1, no skill/snapshot inputs, no owner profile).
    - Eligibility: cube has >=8 success events in trailing 180d at week W (point-in-time).
    - 4 behavior features: turnover_count_90d, mean_lag_vs_leader_30d (vs all 926 leaders),
      attention_spike_rate_90d (proxy via stock volume rolling-60d top-decile), concentration_intensity_30d (HHI of trade weight changes).
    - Composite: per-week z-norm, nanmean, rank-pct.

  B8 results (commit db3df2f superseded by this commit):
    - V2 composite (4 features): median rotation 54.4%/Q → BLOCK
    - Turnover-only fallback: median rotation 43.7%/Q → BLOCK
    - Both fail by wide margin (threshold 20%/Q).

  Proposal (accepted by Codex ATK):
    - H5 STOP per §3.6, recorded as L11 (cube cohort fundamentally unstable under any per-cube behavior axis)
      + N2 entry (H5 REJECTED-PRE-RUNNING with B8 evidence).
    - Cycle 002 continues with I-B1 (data fetcher §2.5 → verdict §2.4 → ATK co-sign) + scaffolding (§2.10/11/12/13).
    - Cycle 003 candidate: stock-level reformulation of H5 (not "which cubes" but "which stocks are over-bought by high-turnover cubes").

  IMPL next action: start I-B1 data fetcher (§2.5), then I-B1 verdict path (§2.4).

  2026-05-24T15:50 update:
    - I-B1 fetcher v0 (research/data_prep/fetch_cb_data.py) committed AS-IS with known selection bug.
      Fetched 41/60 value_analysis + 50/60 price CSVs, but selection ranked by 上市时间 ASC →
      picked 2008-2015 bonds (now matured/delisted, fails 2018+ requirement).
    - Snapshot cov_snapshot.csv (1012 bonds) + redeem_jsl.csv (332 强赎 events) cached and clean.
    - Proposed fix in claude_outbox.md: select bonds where 上市时间 ∈ [2018-01-01, 2022-12-31]
      AND code ∈ redeem_jsl pool → ~200-300 mid-generation bonds with 2018+ history.
    - Awaiting Codex sign-off on fix + cycle 002 scope decision (strict vs insert 反 H2 quick test)
      + cycle 003 candidate lock (stock-level crowding + 反 H2/H3 + crowding×momentum).

  2026-05-24T16:25 update:
    - ACK Codex 2acb44f NEEDS-FIX. Refactored fetch_cb_data.py to v1 (mode split + coverage manifest).
    - Script committed this turn; data + manifest in next commit when fetcher finishes.
    - Fetcher running background task b3ma6vufg with --mode both, double_low window 2018-2022.
    - Cycle 002 strict scope + cycle 003 C1/C2/C3 candidates LOCKED per Codex priority.

  2026-05-24T17:15 update:
    - Fetcher b3ma6vufg complete (~70min wall, exit 0). 815 bonds attempted, 782 success.
    - double_low post-2018 BOTH: 608 (vs Codex ≥50 target → 12× satisfied).
    - redeem with 强赎 fields populated: 332 (100%); post-2018 BOTH: 280.
    - Manifest committed at data/bonds_cb/coverage_manifest.csv.
    - Per-bond CSVs NOT committed (~80MB bloat) — fetcher is idempotent, regenerable.
    - Survivorship caveat surfaced: bond_zh_cov() only enumerates currently-listed; double-low
      alpha likely UNDERSTATED because best outcomes already exited universe.
    - IMPL next: draft §2.4 I-B1 verdict for double_low + 强赎博弈 sub-strategies.
    - 4 design questions in outbox awaiting Codex view (ranking method, hold period,
      强赎 direction, benchmark choice) — not blocking but want input before backtest.

  Johnny 15:30 raised: cube research scope. Discussion outcome:
    - A1 matched baseline (+0.57%/Q t=+0.70) shows the 反向 thesis is WEAKLY supported but
      underpowered (net negative after 9.8%/yr cost). Not falsified, just insufficient.
    - H5 was the elaborated reverse-indicator attempt, died on B8 instability.
    - 5 untested 反向 variants identified (A-E in outbox). Stock-level crowding (A) is the
      most viable next test; needs cycle 003 since universe + axis change.

  Locked decisions (from Codex 10:35 + Johnny 13:11 launch + Johnny 14:30 H5 constraint):
    - α dual-brain: Claude IMPL inline, Codex ATK live
    - B8 BLOCKING precondition; both composite and turnover-only ran per fallback rule
    - H5 confirmation proxy = 融资买入 (becomes moot if H5 STOPs)
    - No self_test rerun unless backtest/strategies/data/universe/costs/self_test.py touched
    - H5 must not use smart_cubes_v1.csv / annualized_gain_rate / followers_count / owner_name; ENFORCED in V2 script.
    - "smart cube" terminology removed from H5 code/docs (directory name retained for repo continuity).

  Protocol version: 0.1 (PROTOCOL.md)
---
