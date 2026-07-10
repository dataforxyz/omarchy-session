# Workspace/session restore helper

`omarchy-session` is a Hyprland terminal workspace restore helper. It saves open
windows, workspaces, scratchpad placement, Omarchy/Hyprland grouped tabs,
terminal working directories, and best-effort commands for interactive terminal
workflows.

Installed commands:

- `ws s [name]` / `omarchy-session save [name]` — save current windows
- `ws s name --workspace 3` — save only workspace 3 as a named profile
- `ws r [name]` / `omarchy-session restore [name]` — restore only missing windows
- `ws rs [name]` / `ws select [name]` — interactively select windows, workspaces, or groups for a partial restore
- `ws r [name] --workspace 3`, `--item 2,4-7`, or `--group 1` — scriptable partial restore selectors
- `ws plan [name]`, `ws dry-run [name]`, or `ws r --dry-run [name]` — print the restore plan without launches, Hyprland dispatches, undo/last-restore writes, notifications, or sleeps
- `ws a` — write a timestamped autosave
- `ws as` — list autosaves
- `ws p` — list named profiles and recent autosaves
- `ws pick` / `ws pk` — choose a named profile or recent autosave from Walker/wofi/fuzzel/rofi, falling back to a numbered terminal picker
- `ws pick plan` — choose any profile/autosave and print its read-only restore plan
- `ws u` — soft undo: restore the pre-restore undo snapshot
- `ws uh` / `ws undo-hard` — hard undo: close windows launched by the previous restore only
- `ws st` / `ws status` — show autosave health, save ages/counts, install path, shortcuts, and last-restore info
- `ws deps` / `ws doctor` / `ws check` — show required and optional dependency status
- `ws menu` — open the workspace-session action submenu installed as the **Workspace Sessions** Super+Space launcher entry

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

For authoritative live Pi, Claude Code, and OpenCode session IDs, install the
optional integrations:

```bash
scripts/install-agent-integrations.py
```

The integration installer preserves existing JSON configuration and creates
backups before adding Claude hooks or the OpenCode plugin. Remove installed
commands and integrations without deleting saved session state with:

```bash
scripts/install-agent-integrations.py --uninstall
scripts/install-omarchy-session.sh --uninstall
```

The installer does not replace unrelated existing `~/.local/bin/ws`,
`~/.local/bin/restore-workspace`, or
`~/.local/share/applications/omarchy-session.desktop` entries by default. It
refreshes entries that are missing or already managed by `omarchy-session`; pass
`--force` to replace unrelated entries. The desktop entry appears as
**Workspace Sessions** in Omarchy's Super+Space app launcher and opens a submenu
for full-layout save, saving one selected workspace as a named profile, restore,
selective restore, profile/autosave selection, default or picked-save preview, autosave, undo, hard
undo, status, and dependency checks.

## Workspace-only profiles

`ws save name --workspace 3` saves only the windows on workspace 3. Multiple
workspace values can be comma-separated or repeated. The Super+Space
**Workspace Sessions** submenu exposes the same flow as **Save one workspace as
profile…**: select a currently occupied workspace and enter the desired profile
name. Existing profiles are affected only when that exact name is deliberately
reused.

Workspace-only saves remove group metadata if a saved group crosses outside the
selected workspace set. The active window is saved only when it belongs to the
selection; otherwise restore preserves the user's current focus when possible.

## Partial restore

`ws rs [name]` opens a toggle-and-reopen picker using Walker, wofi, fuzzel, rofi,
or the numbered terminal fallback. Individual rows can be toggled directly; the
menu can also toggle every item in a saved workspace or Hyprland group, select
all, clear the selection, restore the selected targets, or print their plan. If
`name` is omitted, the profile/autosave picker opens first. `ws pick select` is an
alternate entry point.

For non-interactive use, restore and plan accept selectors:

```bash
ws plan work --workspace 3
ws r work --item 2,4-7
ws r work --group 1 --workspace 4
```

`--workspace`, `--item`, and `--group` may be repeated; comma-separated values are
accepted, and item/group selectors support inclusive ranges. Selectors are
combined as a union. Stable one-based item and group indexes are printed by
`ws list` and restore plans. Workspace selection expands to all saved windows on
that workspace.

Selecting only part of a saved group restores those windows but deliberately
skips regrouping. Group reconstruction occurs only when every saved member is in
the selected target set. A partial restore never edits the source profile. Its
verification and audit consider only selected targets. Saved focus is restored
only when the saved active window is selected; otherwise current focus is
preserved when possible. The normal undo snapshot is still written, and hard undo
closes only windows launched by the most recent partial restore.

## Dry-run restore plans

Use `ws plan [name]`, `ws pick plan`, `ws dry-run [name]`, `ws r --dry-run [name]`, or
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
- `last-restore.json` — windows launched by the most recent real restore;
- `last-restore-audit.json` — most recent real restore audit with before/after snapshots, intended targets, launched windows, and verification details.

Review those files before sharing them. They can contain window titles, window
classes, workspace and monitor names, host name, timestamps, process IDs,
`procCmdline`, `procArgv`, `procCwd`, `restoreWorkdir`, `restoreArgv`,
`browserProfileArgs`, `agentSession`, `piSession`, and restore command hints. The tool reads local
Hyprland window metadata, `/proc` process command lines/working directories, and
local Pi/Claude/Codex/OpenCode session metadata to make restore more useful; it
does not intentionally collect secrets, but commands, paths, titles, and agent
session IDs can reveal private project names, server names, prompts, URLs, or
other sensitive context. Restore audit records intentionally include before/after
window snapshots and desired-vs-actual comparisons, so treat them as at least as
private as saved sessions. Use synthetic or redacted data for bug reports and test
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
and focus restore failures. If post-restore verification is not clean, normal
output includes `restore needs review` with concise missing/mismatch/group/focus
counts instead of hiding the partial restore in the JSON audit.

Before each restore, the current layout is saved to a soft-undo snapshot used by
`ws u`. Restore also records the addresses of windows it actually launched in
`last-restore.json`; `ws undo-hard` closes only those launched windows that are
still present, leaving pre-existing windows alone. Each real restore also writes
`last-restore-audit.json`, containing the before snapshot, intended targets,
after snapshot, launched window records, per-target restore outcomes, restore
summary counters, and a verification section with matched/missing targets, extra
new windows, workspace/monitor mismatches where detectable, group verification
details, and focus outcome. Normal restore output only notes that the audit was
saved; use `-v` to show the audit path.

Regular Chromium, Chrome, Brave, Firefox, and Zen targets preserve explicit
profile/mode arguments when those arguments are visible in the browser process.
When no profile selector is present, restore can infer one from open profile files
only if there is exactly one candidate (usually Firefox/Zen, or a Chromium process
with only one loaded profile). The Chromium family keeps `--profile-directory`,
`--user-data-dir`, `--incognito`, and `--guest`; Firefox/Zen keep `-P`,
`--profile`/`-profile`, `--no-remote`,
`--new-instance`, and private-window mode. Explicit profile arguments become part
of the restore key, preventing a Work profile from being matched to an open
Personal profile. Chromium web-app URL/profile restoration continues to use its
existing app-window handling.

Browser restoration deliberately does not inspect or guess tab URLs or history,
and it refuses to choose among multiple profile candidates. The selected browser profile's own startup/session
settings may restore previous tabs. Multiple plain windows from the same browser
profile remain a known singleton limitation: launching can reuse an existing
process, window, or tab, so they cannot be recreated as independent Hyprland
windows reliably. Duplicate singleton targets are marked as
`duplicate_singleton_unsupported` in the audit and included in the
`restore needs review` summary.

Terminal restore behavior is best effort:

- direct `nvim`, `vim`, and `vi` processes preserve their command-line arguments
  and working directory. This reopens command-line files such as
  `nvim README.md src/main.py`, but does not independently capture unsaved
  buffers, cursor positions, splits, tabs, or plugin state; use Neovim session
  or persistence tooling when that state must survive;
- direct `pi` sessions restore with `pi --session <jsonl>` when matching Pi
  session files can be found;
- direct or wrapped Claude sessions restore with `claude --resume <session-id>`.
  A wrapper can export `OMARCHY_SESSION_CLAUDE_COMMAND` with its executable name
  so restore uses that wrapper instead of bare `claude`;
- direct or wrapped Codex sessions restore with `codex resume <session-id>`.
  A wrapper can export `OMARCHY_SESSION_CODEX_COMMAND` with its executable name
  so restore uses the same wrapper; session lookup also follows `CODEX_HOME`;
- direct or wrapped OpenCode sessions restore with the saved `ses_*` id when the
  local OpenCode version accepts it, otherwise they fall back to plain `opencode`;
- for all four agents, an explicit session argument in the live process wins.
  Otherwise exact PID-to-session data comes from the optional Pi extension,
  Claude Code hooks, Codex's local log database, or the OpenCode plugin. Runtime
  registry records are validated against Linux process start ticks to reject
  stale files and PID reuse. No cwd/time/latest heuristic is used; without an
  exact mapping, restore opens the agent picker (or plain OpenCode). Wrappers can
  advertise restore commands with `OMARCHY_SESSION_PI_COMMAND`,
  `OMARCHY_SESSION_CLAUDE_COMMAND`, `OMARCHY_SESSION_CODEX_COMMAND`, or
  `OMARCHY_SESSION_OPENCODE_COMMAND`;
- wrapper commands like `make ssh` and remote `make pi N=...` are restored by
  rerunning the original `make` command in the saved working directory;
- unknown terminal workflows fall back to reopening the saved terminal app in the
  saved working directory when supported.
