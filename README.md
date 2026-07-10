# omarchy-session

Save and restore Hyprland workspaces on Omarchy-style Linux desktops.

`omarchy-session` records open windows, workspace and monitor placement, floating
and fullscreen state, grouped tabs, terminal working directories, and
best-effort resume commands for supported terminal agents. Restore only launches
windows that appear to be missing, then verifies the resulting layout and writes
an audit report.

## Highlights

- Named workspace profiles and rotating autosaves
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
- Python 3
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

## Quick start

```bash
ws s work          # save the current layout as "work"
ws plan work       # preview a restore without changing anything
ws r work          # restore only missing windows
ws pick            # choose a profile or autosave interactively
ws st              # show save, autosave, and restore health
```

## Commands

```text
ws s [name]        Save the current layout
ws r [name]        Restore missing windows from a save/profile
ws plan [name]     Print a read-only restore plan
ws r --dry-run     Alternate dry-run form
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

A wrapper that eventually executes Claude Code or Codex can advertise the
command that should be used during restore. Export the variable before `exec` so
it remains visible in the agent process:

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

The advertised value must be a simple executable name available on `PATH`.
Codex wrappers that set `CODEX_HOME` are also supported; session lookup follows
that home instead of assuming `~/.codex`.

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
