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
```

## Privacy and saved state

Runtime state lives in:

```text
~/.local/state/omarchy-session/
```

By default that directory contains the latest save (`last-session.json`), named
profiles (`profiles/*.json`), autosaves (`autosaves/*.json`), the soft-undo
snapshot (`before-last-restore.json`), and the last restore launch record
(`last-restore.json`).

Treat these files as private. They are local JSON, but can include sensitive
workflow details such as `procCmdline`, `procArgv`, `restoreWorkdir`,
`agentSession` IDs/paths, host name, timestamps, window classes, window titles,
workspace/monitor names, process IDs, and restore command hints. Review and
redact them before sharing bug reports, screenshots, test fixtures, or commits.

## Requirements

- Linux with Hyprland
- Python 3
- `hyprctl`
- Ghostty for the most complete terminal restore behavior
- Optional picker: Walker, wofi, fuzzel, or rofi

See [`docs/workspace-session-restore.md`](docs/workspace-session-restore.md) for
more details.

## License

Copyright (C) 2026 Ben U.

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
