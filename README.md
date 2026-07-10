# omarchy-session

[![CI](https://github.com/dataforxyz/omarchy-session/actions/workflows/ci.yml/badge.svg)](https://github.com/dataforxyz/omarchy-session/actions/workflows/ci.yml)

Save and restore Hyprland workspaces on Omarchy-style Linux desktops.

`omarchy-session` records open windows, workspace and monitor placement, floating
and fullscreen state, grouped tabs, terminal working directories, and
best-effort resume commands for supported terminal agents. Restore only launches
windows that appear to be missing, then verifies the resulting layout and writes
an audit report.

## Highlights

- Named workspace profiles and rotating autosaves
- Full or partial restore by interactive selection, workspace, group, or item
- Restore plans with a read-only dry-run mode
- Workspace, monitor, scratchpad, floating, and fullscreen restoration
- Best-effort Hyprland group/tab reconstruction
- Terminal working-directory restoration for Ghostty and Alacritty
- Session resume support for Pi, Claude Code, Codex, and OpenCode
- Soft undo for the previous layout and hard undo for newly launched windows
- Post-restore verification with concise failure summaries and a JSON audit
- Walker, wofi, fuzzel, or rofi picker support, with a terminal fallback

## Requirements

Required:

- Linux with Hyprland
- Python 3.10 or newer
- `hyprctl`

Recommended or optional:

- Ghostty or Alacritty for terminal restoration
- `notify-send` for desktop notifications
- Walker, wofi, fuzzel, or rofi for graphical profile selection
- Pi, Claude Code, Codex, or OpenCode if their sessions should be resumed

Check the current machine with:

```bash
omarchy-session deps
```

## Install

```bash
git clone https://github.com/dataforxyz/omarchy-session.git
cd omarchy-session
scripts/install-omarchy-session.sh
```

The installer copies the main script to `~/.local/bin/omarchy-session` and adds
the `ws` and `restore-workspace` command shortcuts. Existing unrelated files or
symlinks with those names are left untouched unless `--force` is supplied.

For development, link the installed command to the checkout:

```bash
scripts/install-omarchy-session.sh --link
```

Install the optional agent integrations for authoritative live-session IDs:

```bash
scripts/install-agent-integrations.py
```

This installs a Pi extension, Claude Code hooks, and an OpenCode plugin. Existing
Claude/OpenCode JSON configuration is preserved and backed up before changes.
Use `--pi`, `--claude`, or `--opencode` to install only one integration.

To uninstall while preserving saved session state:

```bash
scripts/install-agent-integrations.py --uninstall
scripts/install-omarchy-session.sh --uninstall
```

## Quick start

```bash
ws s work          # save the current layout as "work"
ws plan work       # preview a restore without changing anything
ws r work          # restore only missing windows
ws rs work         # choose specific windows to restore
ws pick            # choose a profile or autosave interactively
ws st              # show save, autosave, and restore health
```

## Commands

```text
ws s [name]        Save the current layout
ws r [name]        Restore missing windows from a save/profile
ws plan [name]     Print a read-only restore plan
ws rs [name]       Select windows for a partial restore interactively
ws r --dry-run     Alternate dry-run form
ws r work -w 3     Restore all saved windows on workspace 3
ws r work -i 2,4-6 Restore saved item indexes 2, 4, 5, and 6
ws r work -g 1     Restore every member of saved group 1
ws a               Create an autosave now
ws as              List autosaves
ws p               List named profiles and recent autosaves
ws pick            Select a profile or autosave interactively
ws u               Soft undo: restore the pre-restore snapshot
ws uh              Hard undo: close windows launched by the last restore
ws st              Show status and health information
ws deps            Show required and optional dependency status
ws path [name]     Print a saved session path for scripting
ws -v l            Show verbose saved-session metadata
```

The long command forms are also available, for example:

```bash
omarchy-session save work
omarchy-session restore --dry-run work
omarchy-session restore work
```

## Partial restore

Use `ws rs [name]` (or `ws select [name]`) for a toggle-and-reopen menu. It can
toggle individual windows, whole workspaces, or saved groups before restoring or
printing a plan. Without a profile name, it first opens the normal profile picker.

For scripts, selectors can be repeated or comma-separated, and item/group ranges
are accepted:

```bash
ws plan work --workspace 3
ws r work --item 2,4-7
ws r work --group 1 --workspace 4
```

Selectors are combined as a union. `ws l work` and `ws plan work` show stable
one-based item and group indexes. Selecting a workspace expands to all saved
windows on that workspace. A saved Hyprland group is reconstructed only when all
its members are selected; selected individual members still restore normally.

Partial restore does not alter the saved profile. Verification and the JSON audit
are scoped to selected targets. If the saved active window is not selected, the
current focus is preserved when possible. Hard undo closes only windows launched
by that partial restore.

## What gets restored

The tool saves Hyprland window metadata and compares it with the currently open
windows. A restore attempts to recreate:

- missing application windows;
- saved workspace and monitor placement;
- special workspace/scratchpad placement;
- floating and fullscreen state;
- grouped-window membership and order;
- the saved active workspace/window;
- supported terminal working directories and agent sessions.

Restoration is intentionally best effort. Applications such as browsers may
reuse an existing process, tab, or window rather than create a new Hyprland
window. Unsupported app classes are skipped and recorded for review rather than
executed blindly.

## Terminal agents and custom wrappers

Direct sessions are resumed using their standard commands when local session
metadata is available:

- Pi: `pi --session <path>`
- Claude Code: `claude --resume <id>`
- Codex: `codex resume <id>`
- OpenCode: its saved `ses_*` identifier when supported

Session matching does not guess from cwd, timestamps, or “latest” state. It uses
only authoritative sources:

- an explicit session ID already present in the process arguments;
- the Pi extension's PID-to-session registry;
- Claude Code's hook-provided session ID registry;
- Codex's PID-to-thread records in its local log database;
- the OpenCode plugin's active-session registry.

Registry records include Linux process start ticks so stale files and reused PIDs
are rejected. If no exact mapping exists, Pi, Claude, and Codex open their session
picker; OpenCode opens normally. The tool never silently substitutes a guessed
conversation.

A wrapper that eventually executes an agent can advertise the command that
should be used during restore. Export the corresponding variable before `exec`
so it remains visible in the agent process:

```bash
#!/usr/bin/env bash
export OMARCHY_SESSION_CODEX_COMMAND=my-codex
exec codex "$@"
```

```bash
#!/usr/bin/env bash
export OMARCHY_SESSION_CLAUDE_COMMAND=my-claude
exec claude "$@"
```

Supported variables are `OMARCHY_SESSION_PI_COMMAND`,
`OMARCHY_SESSION_CLAUDE_COMMAND`, `OMARCHY_SESSION_CODEX_COMMAND`, and
`OMARCHY_SESSION_OPENCODE_COMMAND`. The advertised value must be a simple
executable name available on `PATH`. Codex wrappers that set `CODEX_HOME` are
also supported; session lookup follows that home instead of assuming
`~/.codex`.

## Dry-run and verification

Always preview an unfamiliar or old save first:

```bash
ws plan work
```

Dry-run mode does not launch applications, dispatch Hyprland commands, write
undo/restore state, send notifications, or sleep between launches.

A real restore writes `last-restore-audit.json` with the before snapshot,
intended targets, detected launches, after snapshot, group results, placement
mismatches, and focus outcome. If verification is incomplete, the normal output
includes a `restore needs review` summary.

## Saved state and privacy

Runtime state is stored under:

```text
~/.local/state/omarchy-session/
```

This can include:

- `last-session.json`
- `profiles/*.json`
- `autosaves/*.json`
- `before-last-restore.json`
- `last-restore.json`
- `last-restore-audit.json`

Treat these files as private. They may contain window titles, working
directories, process arguments, hostnames, monitor/workspace names, and local
agent session identifiers. Review and redact saved state before posting logs,
screenshots, fixtures, or bug reports.

## More documentation

See [`docs/workspace-session-restore.md`](docs/workspace-session-restore.md) for
implementation details, limitations, undo behavior, and restore verification.

## License

Copyright (C) 2026 Ben U.

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
