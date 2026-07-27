# Multi-Session Sync Protocol (Claude + Codex autonomous mode)

File-based message bus for two `/goal until [...]` sessions sharing this git working tree.

## Files

| File | Owner | Reader | Purpose |
|---|---|---|---|
| `_sync/claude_outbox.md` | Claude session | Codex session | Claude's latest action + ask |
| `_sync/codex_outbox.md` | Codex session | Claude session | Codex's latest action + ask |
| `_sync/control.md` | Both (CAS via git) | Both | Shared state machine: phase, who-acts-next, stop condition, last-committed-sha |
| `_sync/history.md` | Append-only | Both | Audit log of every action + commit |

Outboxes are overwritten on each turn (single-message snapshot, no append). `history.md` is the append-only log if you need archeology.

## Turn cycle (each session, every wake)

```
1. git pull --rebase origin <branch>     # absorb peer's commits
2. cat _sync/control.md                  # who acts next? still in this phase?
3. cat _sync/<peer>_outbox.md            # what did peer just say/do?
4. ... do work ...                       # tests, edits, commits
5. write _sync/<self>_outbox.md          # one-message reply: what I did + what I ask peer to do
6. update _sync/control.md               # advance state machine if appropriate
7. append _sync/history.md               # one line per action
8. git add _sync/* && git commit -m "sync(<self>): <verb>" && git push
9. sleep (handled by /goal validator or /loop interval)
```

## Stopping condition

`/goal until [...]` evaluates the stop condition. When both sessions agree (via control.md `phase: DONE` + both outboxes empty acknowledgement), they exit.

Hard stop overrides (any session can trigger):
- `_sync/control.md` contains `STOP: <reason>` line — both sessions halt next cycle.
- User pushes a commit touching `_sync/control.md` with `STOP:`.

## control.md schema

```yaml
phase: <PHASE_0 | PHASE_1 | PHASE_2 | DONE | STOP>
who_acts_next: <claude | codex | either>
stopping_condition: <text predicate>
last_committed_sha: <git rev-parse HEAD>
last_update_by: <claude | codex>
last_update_ts: <ISO 8601>
notes: |
  Multi-line notes about current state.
```

## Anti-thrash rules

1. **No silent merge** (per `codex_collaboration` memory): if Claude's outbox disagrees with Codex's, write a `RECONCILIATION` block in own outbox, don't just overwrite.
2. **No empty turns**: if there's nothing to say, advance phase or trigger STOP. Don't poll-spin.
3. **Commit per turn**: every wake must result in either a commit (real work) or a `noop: <reason>` line in history.md. Three consecutive noops in a row → automatic STOP.
4. **Rebase, don't merge** during sync to keep linear history.
5. **Long-running tasks**: if work exceeds a single wake (e.g., a 30-min Backtest), launch it in background via `run_in_background` and write the bg task ID to control.md, then exit. Next wake, peek the bg output.

## Channel hook (optional)

Wire `_sync/control.md` `STOP:` lines to a Telegram channel via Claude Code's Channels feature, so user (Johnny) gets pinged when either session halts.

## Backward compat

`PROTOCOL.md` is version 0.1, 2026-05-24. Any breaking change → bump to v0.2 + write upgrade note in `history.md`. Sessions on different versions MUST refuse to act until manually reconciled.
