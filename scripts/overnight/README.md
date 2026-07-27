# Overnight unattended execution

Scripts for running Claude + Codex `/goal` sessions overnight without
permission prompts and with macOS kept awake.

## TL;DR (one-command setup)

```bash
cd ~/jz_code/bili_stock
bash scripts/overnight/launch.sh
# close terminal, walk away
```

In the morning:

```bash
bash scripts/overnight/pulse.sh
```

To stop early:

```bash
bash scripts/overnight/stop.sh
```

## What launch.sh does

1. Verifies you're on `patch/methodology-audit-2026-05-23` and working tree is clean.
2. Creates `logs/overnight_YYYYMMDD_HHMM/` and a `logs/overnight_latest` symlink.
3. Starts **`caffeinate -dimsu`** in the background (prevents display sleep, idle sleep, disk idle sleep, system sleep + declares user active).
4. Starts **`claude -p "/goal until '<cycle_001 condition>'"`** — Claude session. Permissions are already bypassed globally (alias `claude --dangerously-skip-permissions` + `~/.claude/settings.json#skipDangerousModePermissionPrompt: true`).
5. Starts **`codex exec --dangerously-bypass-approvals-and-sandbox --sandbox=workspace-write`** — Codex session running cycle_001 as ATTACKER role per ENGINE_SPEC §10.
6. `disown -a` so all three survive terminal close.

## Goal string (LOCKED per Codex)

The Claude session runs:

```
/goal until 'cycle_001 verdicts committed per ENGINE_SPEC §6, including foundation
self_test 7/7, A1/H2/H3/H4 verdict files, size/liquidity-matched random baselines,
retracted old verdict banner, PR #6 update draft reviewed by both agents, and
cycle_002 proposals spawned from canonical catalog plus any surviving cubes
anti-signal mechanisms; if any hard gate fails, write STOP in _sync/control.md and exit'
```

This is **bounded** (specific verifiable artifacts) and **STOP-on-fail** (any hard
gate writes STOP to `_sync/control.md` and exits).

## Coordination

The two agents coordinate via `research/foundation/_sync/`:
- `PROTOCOL.md` — message-bus spec
- `claude_outbox.md` / `codex_outbox.md` — turn-based message exchange
- `control.md` — shared state machine
- `history.md` — append-only audit log

Each agent rebases before acting and commits after.

## Risk acceptance

`--dangerously-skip-permissions` / `--dangerously-bypass-approvals-and-sandbox` give
the agents Bash/Edit/Write/WebSearch/Agent without prompts. This is intentional for
overnight unattended mode. If you don't want this, use the allowlist alternative
in `~/.claude/settings.json` (see Anthropic docs `permissions.md`).

Sandbox is set to `workspace-write` for Codex (writes confined to the workspace,
not the whole filesystem) for slight safety. Adjust if needed.

## Troubleshooting

- **Agent stuck**: `tail -f logs/overnight_latest/claude.log` (or codex.log)
- **STOP fired**: `grep STOP research/foundation/_sync/control.md`
- **Token budget exceeded**: agents self-report in cycle file; check `research/foundation/_engine/cycles/cycle_001_*.md`
- **Mac slept anyway**: `pmset -g` to verify; ensure plugged into AC power
- **Process died early**: check `logs/overnight_latest/<proc>.log` last 50 lines

## Disable macOS interruptions before launch

Recommended (optional but safer):

```bash
# Wi-Fi sleep off
sudo /usr/libexec/airportd prefs DisconnectOnLogout=NO 2>/dev/null || true

# Do Not Disturb (manual: System Settings → Focus → Do Not Disturb → On Until Tomorrow)

# Time Machine off (manual: System Settings → General → Time Machine → toggle off until morning)
```

These prevent app interruptions but the scripts work without them.
