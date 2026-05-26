# omarchy-session

A small Hyprland terminal workspace session helper for Omarchy-style desktops.
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

The installer refreshes `ws` and `restore-workspace` only when they are absent
or already point to `omarchy-session`. If either name is an unrelated existing
file or symlink, it is left untouched with a warning; use `--force` to replace it.

This installs `omarchy-session` and provides these aliases when they are not
skipped for safety:

- `ws`
- `restore-workspace`

## Usage

```bash
ws s [name]       # save current session/profile
ws r [name]       # restore missing windows
ws plan [name]    # dry-run restore plan; no launches, dispatches, writes, or sleeps
ws r --dry-run [name]
ws a              # autosave now
ws as             # list autosaves
ws p              # list profiles and recent autosaves
ws pick           # pick a profile/autosave using a launcher or terminal picker
ws u              # soft undo: restore the pre-restore snapshot
ws uh             # hard undo: close windows launched by the last restore
ws st             # status/health
ws deps           # dependency check
ws -v l           # verbose output with saved paths/restore metadata
```

## Privacy and saved state

Runtime state lives in:

```text
~/.local/state/omarchy-session/
```

Normal command output is summary-first: it shows counts and relative ages like `12m ago`, and avoids full saved-state paths/raw timestamps unless you pass `-v` / `--verbose` or explicitly run `ws path`. Real restores append `restore needs review` when the after-restore audit finds missing targets, singleton/browser limitations, group failures, mismatches, or focus failures.

By default that directory contains the latest save (`last-session.json`), named
profiles (`profiles/*.json`), autosaves (`autosaves/*.json`), the soft-undo
snapshot (`before-last-restore.json`), the last restore launch record
(`last-restore.json`), and the last restore audit record
(`last-restore-audit.json`).

Treat these files as private. They are local JSON, but can include sensitive
workflow details such as `procCmdline`, `procArgv`, `restoreWorkdir`,
`agentSession` IDs/paths, host name, timestamps, window classes, window titles,
workspace/monitor names, process IDs, restore command hints, and before/after
restore audit snapshots. Review and redact them before sharing bug reports,
screenshots, test fixtures, or commits.

## Requirements

- Linux with Hyprland
- Python 3
- `hyprctl`
- Ghostty or Alacritty for the most complete terminal restore behavior
- Optional picker: Walker, wofi, fuzzel, or rofi

See [`docs/workspace-session-restore.md`](docs/workspace-session-restore.md) for
more details.

## License

Copyright (C) 2026 Ben U.

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
