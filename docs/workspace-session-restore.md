# Workspace/session restore helper

`omarchy-session` is a Hyprland/Ghostty workspace restore helper. It saves open
windows, workspaces, scratchpad placement, Omarchy/Hyprland grouped tabs,
Ghostty working directories, and best-effort commands for interactive terminal
workflows.

Installed commands:

- `ws s [name]` / `omarchy-session save [name]` — save current windows
- `ws r [name]` / `omarchy-session restore [name]` — restore only missing windows
- `ws a` — write a timestamped autosave
- `ws as` — list autosaves
- `ws p` — list named profiles and recent autosaves
- `ws pick` / `ws pk` — choose a named profile or recent autosave from Walker/wofi/fuzzel/rofi, falling back to a numbered terminal picker
- `ws u` — soft undo: restore the pre-restore undo snapshot
- `ws uh` / `ws undo-hard` — hard undo: close windows launched by the previous restore only
- `ws st` / `ws status` — show autosave health, save ages/counts, install path, shortcuts, and last-restore info
- `ws deps` / `ws doctor` / `ws check` — show required and optional dependency status

The script is source-controlled at `scripts/omarchy-session`. Install it with:

```bash
scripts/install-omarchy-session.sh
```

For development, linking keeps `~/.local/bin/omarchy-session` pointed at this
repo copy:

```bash
scripts/install-omarchy-session.sh --link
```

Runtime state lives in `~/.local/state/omarchy-session/` and includes autosaves,
named profiles, and the undo snapshot. Review those files before sharing them;
they can contain window titles, working directories, command lines, and local
session IDs.

Hyprland grouped tabs created with `Super+G` are saved from Hyprland's `grouped`
metadata. Restore recreates those groups best-effort after windows are relaunched
or matched to already-open windows. Tab order is preserved when Hyprland accepts
the regrouping commands. New saves also record the active workspace/window, so
restore returns to the saved workspace and active grouped tab when possible.

Window records include Hyprland monitor IDs and names. Restore moves saved
workspaces back to their saved monitor when that monitor still exists, falling
back safely when monitor names changed after a reinstall, dock change, or laptop
undock.

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
- unknown terminal workflows fall back to reopening Ghostty in the saved working
  directory.
