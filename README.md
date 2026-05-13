# omarchy-session

A small Hyprland/Ghostty workspace session helper for Omarchy-style desktops.
It saves open windows, workspaces, scratchpad placement, grouped tabs, monitor
placement, and best-effort restore commands for terminal workflows.

## Install

```bash
scripts/install-omarchy-session.sh
```

For development, link the command to this checkout instead of copying it:

```bash
scripts/install-omarchy-session.sh --link
```

This installs:

- `omarchy-session`
- `ws`
- `restore-workspace`

## Usage

```bash
ws s [name]       # save current session/profile
ws r [name]       # restore missing windows
ws a              # autosave now
ws as             # list autosaves
ws p              # list profiles and recent autosaves
ws pick           # pick a profile/autosave using a launcher or terminal picker
ws u              # soft undo: restore the pre-restore snapshot
ws uh             # hard undo: close windows launched by the last restore
ws st             # status/health
```

Runtime state lives in:

```text
~/.local/state/omarchy-session/
```

Do not publish runtime state files unless you have reviewed them. They can
contain window titles, working directories, command lines, and local session IDs.

## Requirements

- Linux with Hyprland
- Python 3
- `hyprctl`
- `jq`
- Ghostty for the most complete terminal restore behavior
- Optional picker: Walker, wofi, fuzzel, or rofi

See [`docs/workspace-session-restore.md`](docs/workspace-session-restore.md) for
more details.
