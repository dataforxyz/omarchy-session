# omarchy-session

<p align="center">
  <img src="assets/omarchy-session.svg" width="144" height="144" alt="omarchy-session Saved Grid logo">
</p>

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
- Neovim/Vim relaunch with the saved working directory and command-line arguments
- Chromium, Chrome, Brave, Firefox, and Zen profile/mode restoration when explicitly detectable
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

The installer copies the main script to `~/.local/bin/omarchy-session`, adds
the `ws` and `restore-workspace` command shortcuts, and installs a **Workspace
Sessions** launcher entry. On a standard Omarchy setup, open it with
**Super+Space**; selecting it opens a session-actions submenu, including an
action to save one selected workspace as any named profile. Existing unrelated
files, symlinks, or desktop entries with those names are left untouched unless
`--force` is supplied.

If an autosave loop is already configured or running, reinstalling automatically
restarts it so future autosaves use the newly installed matching logic rather
than an older in-memory copy of the script.

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
ws s coding -w 3   # save only workspace 3 as the "coding" profile
ws plan work       # preview a restore without changing anything
ws r work          # restore only missing windows
ws rs work         # choose specific windows to restore
ws pick            # choose a profile or autosave interactively
ws pick plan       # choose a profile/autosave and preview its restore plan
ws menu            # open the session-actions submenu
ws st              # show save, autosave, and restore health
```

## Commands

```text
ws s [name]        Save the current layout
ws s name -w 3     Save only workspace 3 as a named profile
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
ws pick plan       Select a profile/autosave and preview it without restoring
ws u               Soft undo: restore the pre-restore snapshot
ws uh              Hard undo: close windows launched by the last restore
ws st              Show status and health information
ws deps            Show required and optional dependency status
ws menu            Open the same submenu exposed in the Super+Space launcher
ws path [name]     Print a saved session path for scripting
ws -v l            Show verbose saved-session metadata
```

The long command forms are also available, for example:

```bash
omarchy-session save work
omarchy-session restore --dry-run work
omarchy-session restore work
```

## Workspace-only profiles

Save only the windows on one or more workspaces without changing another profile:

```bash
ws s coding --workspace 3
ws s browser-set --workspace 4,5
```

The Super+Space **Workspace Sessions** submenu provides a friendly version: pick
**Save one workspace as profile…**, choose the workspace (for example the one
opened with Super+3), then enter any profile name. Cross-workspace group metadata
is removed when only part of a group is included, and saved focus is included
only when the active window belongs to the selected workspace.

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

## Browser profiles and basic browser state

For regular Chromium, Chrome, Brave, Firefox, and Zen windows, the tool preserves
profile and private/guest mode arguments when they are explicitly visible in the
browser process. It can also infer a profile from the process's open files when
there is exactly one unambiguous candidate—commonly Firefox/Zen, and Chromium
when that browser process has only one profile loaded. Supported basics include:

- Chromium family: `--profile-directory`, `--user-data-dir`, `--incognito`, and
  `--guest`;
- Firefox/Zen family: `-P`, `--profile`/`-profile`, `--no-remote`,
  `--new-instance`, and private-window mode;
- Chromium web apps: app URL plus their profile/user-data/class flags, as before.

Explicit profiles become part of the restore key, so a saved Work profile is not
silently matched to an open Personal profile. The launch reopens the detected
profile and lets the browser's own startup/session settings decide whether its
previous tabs return.

The tool does not inspect or guess active URLs, tab lists, or browser history. It
also refuses to choose among multiple profile candidates exposed by one browser
process. Multiple plain windows
from the same browser profile remain a browser-controlled singleton limitation:
the browser may reuse an existing process/window rather than create every saved
Hyprland window.

## Terminal editors

When Neovim or Vim is running directly inside Ghostty or Alacritty, the saved
terminal restore command preserves its argv and working directory. For example,
`nvim README.md src/main.py` is relaunched with those files in the same project
directory. This also supports `vim` and `vi`.

This is command-level restoration, not an editor-state snapshot. Neovim session
state that was not represented by its command line—unsaved buffers, cursor
positions, tabs, splits, and plugin state—requires Neovim's own session or
persistence tooling. A Neovim instance running inside a persistent tmux session
can instead be recovered when the saved tmux command reconnects successfully.

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

From the Super+Space **Workspace Sessions** submenu, use **Preview restore
plan…** to choose default, any named profile, or an autosave before opening its
plan. The terminal equivalent is `ws pick plan`.

Dry-run mode does not launch applications, dispatch Hyprland commands, write
undo/restore state, send notifications, or sleep between launches. Plans match
live windows using exact session IDs when available, then compatible title and
working-directory evidence; non-authoritative `picker` markers are never treated
as real session IDs. Already-correct monitor placements are omitted rather than
reported as changes.

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

## Icon and branding

The **Saved Grid** mark combines a four-window workspace layout with a mint
bookmark for saved session state. Vector, symbolic, preview, and launcher-size
PNG assets are available under [`assets/`](assets/). The installer registers the
icon in the user's hicolor icon theme and uses it for the Super+Space
**Workspace Sessions** launcher entry.

## More documentation

See [`docs/workspace-session-restore.md`](docs/workspace-session-restore.md) for
implementation details, limitations, undo behavior, and restore verification.

## License

Copyright (C) 2026 Ben U.

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
