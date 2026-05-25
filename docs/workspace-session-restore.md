# Workspace/session restore helper

`omarchy-session` is a Hyprland terminal workspace restore helper. It saves open
windows, workspaces, scratchpad placement, Omarchy/Hyprland grouped tabs,
terminal working directories, and best-effort commands for interactive terminal
workflows.

Installed commands:

- `ws s [name]` / `omarchy-session save [name]` — save current windows
- `ws r [name]` / `omarchy-session restore [name]` — restore only missing windows
- `ws plan [name]`, `ws dry-run [name]`, or `ws r --dry-run [name]` — print the restore plan without launches, Hyprland dispatches, undo/last-restore writes, notifications, or sleeps
- `ws a` — write a timestamped autosave
- `ws as` — list autosaves
- `ws p` — list named profiles and recent autosaves
- `ws pick` / `ws pk` — choose a named profile or recent autosave from Walker/wofi/fuzzel/rofi, falling back to a numbered terminal picker
- `ws u` — soft undo: restore the pre-restore undo snapshot
- `ws uh` / `ws undo-hard` — hard undo: close windows launched by the previous restore only
- `ws st` / `ws status` — show autosave health, save ages/counts, install path, shortcuts, and last-restore info
- `ws deps` / `ws doctor` / `ws check` — show required and optional dependency status

Default output is summary-first: saves/autosaves report window/workspace counts, terminal resumes, groups, and relative ages like `12m ago` instead of full state-file paths or raw timestamps. Use `-v` / `--verbose` (for example, `ws -v l`) when you need saved paths, raw timestamps, and restore metadata; `ws path [name]` still prints just the path for scripting.

The script is source-controlled at `scripts/omarchy-session`. Install it with:

```bash
scripts/install-omarchy-session.sh
```

For development, linking keeps `~/.local/bin/omarchy-session` pointed at this
repo copy:

```bash
scripts/install-omarchy-session.sh --link
```

The installer does not replace unrelated existing `~/.local/bin/ws` or
`~/.local/bin/restore-workspace` entries by default. It refreshes aliases that
are missing or already point to `omarchy-session`; pass `--force` to replace
unrelated aliases and keep the historical clobbering behavior.

## Dry-run restore plans

Use `ws plan [name]`, `ws dry-run [name]`, `ws r --dry-run [name]`, or
`omarchy-session restore --dry-run [name]` to inspect what restore would do. The
plan loads the saved session and compares it with the current Hyprland windows.
It reports windows that are already open, windows that would be launched, windows
that would be skipped because the app class or optional command is unavailable,
and monitor/group/focus actions. Group reporting distinguishes groups that are
already correct, would need regrouping, have partial/missing members, or cannot
be assessed; `-v` adds per-group member detail.

Dry-run mode is intentionally read-only: it does not call Hyprland dispatch,
launch apps, write the undo snapshot, write `last-restore.json`, send desktop
notifications, or sleep between launches. Missing or corrupt session files still
fail; skipped optional apps are reported in the plan without making dry-run fail.

## Privacy and saved state

Runtime state lives in `~/.local/state/omarchy-session/` and includes:

- `last-session.json` — default save;
- `profiles/*.json` — named profiles;
- `autosaves/*.json` and `autosaves/latest.json` — autosave history;
- `before-last-restore.json` — soft-undo snapshot;
- `last-restore.json` — windows launched by the most recent real restore.

Review those files before sharing them. They can contain window titles, window
classes, workspace and monitor names, host name, timestamps, process IDs,
`procCmdline`, `procArgv`, `procCwd`, `restoreWorkdir`, `restoreArgv`,
`agentSession`, `piSession`, and restore command hints. The tool reads local
Hyprland window metadata, `/proc` process command lines/working directories, and
local Pi/Claude/Codex/OpenCode session metadata to make restore more useful; it
does not intentionally collect secrets, but commands, paths, titles, and agent
session IDs can reveal private project names, server names, prompts, URLs, or
other sensitive context. Use synthetic or redacted data for bug reports and test
fixtures.

Hyprland grouped tabs created with `Super+G` are saved from Hyprland's `grouped`
metadata. Restore recreates those groups best-effort after windows are relaunched
or matched to already-open windows, then verifies saved groups again so the final
summary separates groups that were actively restored from groups that are correct,
partial/missing, failed, or could not be assessed. Tab order is preserved when
Hyprland accepts the regrouping commands. New saves also record the active
workspace/window, so restore returns to the saved workspace and active grouped tab
when possible.

Window records include Hyprland monitor IDs and names. Restore moves saved
workspaces back to their saved monitor when that monitor still exists, falling
back safely when monitor names changed after a reinstall, dock change, or laptop
undock. Restore-time Hyprland dispatches are retried briefly when possible, and
the final summary reports detectable launch dispatch failures, launched windows
that were not observed, saved-state dispatch failures, monitor placement failures,
and focus restore failures.

Before each restore, the current layout is saved to a soft-undo snapshot used by
`ws u`. Restore also records the addresses of windows it actually launched in
`last-restore.json`; `ws undo-hard` closes only those launched windows that are
still present, leaving pre-existing windows alone.

Terminal restore behavior is best effort:

- direct `pi` sessions restore with `pi --session <jsonl>` when matching Pi
  session files can be found. If multiple Pi windows share the same cwd, the
  newest unused session for that cwd is assigned to each window to reduce
  duplicate-session collisions;
- direct or wrapped Claude sessions restore with `claude --resume <session-id>`
  when a matching Claude session can be found, otherwise `claude --continue`;
- direct or wrapped Codex sessions restore with `codex resume <session-id>` when
  a matching Codex session can be found, otherwise `codex resume --last`;
- direct or wrapped OpenCode sessions restore with the saved `ses_*` id when the
  local OpenCode version accepts it, otherwise they fall back to plain `opencode`;
- wrapper commands like `make ssh` and remote `make pi N=...` are restored by
  rerunning the original `make` command in the saved working directory;
- unknown terminal workflows fall back to reopening the saved terminal app in the
  saved working directory when supported.
