#!/bin/bash
# SPDX-FileCopyrightText: 2026 Ben U
# SPDX-License-Identifier: GPL-3.0-or-later
# Install the source-controlled Omarchy workspace/session restore helper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/omarchy-session"
BIN_DIR="${HOME}/.local/bin"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="$APPLICATIONS_DIR/omarchy-session.desktop"
ASSETS_DIR="$(cd "$SCRIPT_DIR/../assets" && pwd)"
ICONS_DIR="${HOME}/.local/share/icons/hicolor"
SCALABLE_ICON="$ICONS_DIR/scalable/apps/omarchy-session.svg"
SYMBOLIC_ICON="$ICONS_DIR/symbolic/apps/omarchy-session-symbolic.svg"
MODE="copy"
FORCE=0
UNINSTALL=0

usage() {
    cat <<'USAGE'
Usage: scripts/install-omarchy-session.sh [--copy|--link] [--force|--uninstall]

Installs scripts/omarchy-session to ~/.local/bin/omarchy-session, adds a
"Workspace Sessions" entry and icon to the Super+Space app launcher, and refreshes
short aliases:
  ws -> omarchy-session
  restore-workspace -> omarchy-session

--copy is the default and is safest for restored machines.
--link keeps ~/.local/bin/omarchy-session pointed at this git checkout.
--uninstall removes omarchy-session and only the shortcuts managed by it.

By default, existing ws/restore-workspace aliases are refreshed only when they
are absent or already point to omarchy-session. Unrelated existing files or
symlinks are left untouched with a warning. Use --force to replace them and
preserve the old installer behavior.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --copy) MODE="copy" ;;
        --link) MODE="link" ;;
        --force) FORCE=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ ! -f "$SRC" ]]; then
    echo "Missing source script: $SRC" >&2
    exit 1
fi

alias_points_to_omarchy_session() {
    local dest="$1"
    local target

    [[ -L "$dest" ]] || return 1
    target="$(readlink "$dest")"
    [[ "$target" == "omarchy-session" ]] && return 0
    [[ "$(basename "$target")" == "omarchy-session" ]] && return 0
    return 1
}

binary_is_managed() {
    local dest="$1"
    if [[ -L "$dest" ]]; then
        [[ "$(basename "$(readlink "$dest")")" == "omarchy-session" ]]
        return
    fi
    [[ -f "$dest" ]] && grep -Fq 'SESSION_FILE = STATE_DIR / "last-session.json"' "$dest"
}

icon_is_managed() {
    [[ -f "$SCALABLE_ICON" ]] && grep -Fq 'omarchy-session Saved Grid icon' "$SCALABLE_ICON"
}

install_icons() {
    if [[ -e "$SCALABLE_ICON" ]] && [[ "$FORCE" -ne 1 ]] && ! icon_is_managed; then
        echo "Warning: refusing to replace unrelated existing $SCALABLE_ICON" >&2
        echo "         Re-run with --force to replace it." >&2
        return
    fi
    mkdir -p "$(dirname "$SCALABLE_ICON")" "$(dirname "$SYMBOLIC_ICON")"
    install -m 0644 "$ASSETS_DIR/omarchy-session.svg" "$SCALABLE_ICON"
    install -m 0644 "$ASSETS_DIR/omarchy-session-symbolic.svg" "$SYMBOLIC_ICON"
    for size in 16 24 32 48 64 128 256 512; do
        destination="$ICONS_DIR/${size}x${size}/apps"
        mkdir -p "$destination"
        install -m 0644 "$ASSETS_DIR/icons/png/omarchy-session-${size}.png" "$destination/omarchy-session.png"
    done
    echo "Installed Saved Grid icon set under $ICONS_DIR"
}

desktop_is_managed() {
    [[ -f "$1" ]] && grep -Fq 'X-Omarchy-Session-Managed=true' "$1"
}

install_desktop_launcher() {
    if [[ -e "$DESKTOP_FILE" ]] && [[ "$FORCE" -ne 1 ]] && ! desktop_is_managed "$DESKTOP_FILE"; then
        echo "Warning: refusing to replace unrelated existing $DESKTOP_FILE" >&2
        echo "         Re-run with --force to replace it." >&2
        return
    fi
    mkdir -p "$APPLICATIONS_DIR"
    cat > "$DESKTOP_FILE" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Workspace Sessions
Comment=Save, restore, preview, and undo Hyprland workspace sessions
Exec=omarchy-session menu
Icon=omarchy-session
Terminal=false
Categories=Utility;
Keywords=workspace;session;save;restore;hyprland;
X-Omarchy-Session-Managed=true
DESKTOP
    echo "Installed Super+Space launcher entry: $DESKTOP_FILE"
}

restart_autosave_loop_if_configured() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-session"
    local pid_file="$state_dir/autosave-loop.pid"
    local old_pid=""
    local was_running=0
    local service_file="$HOME/.config/systemd/user/omarchy-session-autosave.service"
    local service_enabled=0

    if [[ -f "$pid_file" ]]; then
        old_pid="$(cat "$pid_file" 2>/dev/null || true)"
        if [[ "$old_pid" =~ ^[0-9]+$ ]] && [[ -r "/proc/$old_pid/cmdline" ]]; then
            if tr '\0' ' ' < "/proc/$old_pid/cmdline" | grep -Fq "$BIN_DIR/omarchy-session autosave-loop"; then
                was_running=1
                kill "$old_pid" 2>/dev/null || true
                rm -f "$pid_file"
            fi
        else
            rm -f "$pid_file"
        fi
    fi

    if [[ -f "$service_file" ]] && command -v systemctl >/dev/null 2>&1 \
            && systemctl --user is-enabled --quiet omarchy-session-autosave.service 2>/dev/null; then
        service_enabled=1
    fi

    if [[ -f "$service_file" ]] && command -v systemctl >/dev/null 2>&1 \
            && [[ "$was_running" -eq 1 || "$service_enabled" -eq 1 ]]; then
        systemctl --user daemon-reload >/dev/null 2>&1 || true
        systemctl --user restart omarchy-session-autosave.service >/dev/null 2>&1 || true
        echo "Restarted omarchy-session-autosave.service with the installed version"
    elif [[ "$was_running" -eq 1 ]]; then
        mkdir -p "$state_dir"
        nohup "$BIN_DIR/omarchy-session" autosave-loop > "$state_dir/autosave-loop.log" 2>&1 &
        echo "Restarted the running autosave loop with the installed version"
    fi
}

install_alias() {
    local name="$1"
    local dest="$BIN_DIR/$name"

    if [[ -e "$dest" || -L "$dest" ]]; then
        if [[ "$FORCE" -eq 1 ]] || alias_points_to_omarchy_session "$dest"; then
            ln -sfn omarchy-session "$dest"
            echo "Refreshed $dest -> omarchy-session"
        else
            echo "Warning: refusing to replace unrelated existing $dest" >&2
            echo "         Re-run with --force to replace it." >&2
        fi
    else
        ln -s omarchy-session "$dest"
        echo "Created $dest -> omarchy-session"
    fi
}

if [[ "$UNINSTALL" -eq 1 ]]; then
    for name in ws restore-workspace; do
        dest="$BIN_DIR/$name"
        if alias_points_to_omarchy_session "$dest"; then
            rm -f "$dest"
            echo "Removed managed shortcut: $dest"
        fi
    done
    if icon_is_managed; then
        rm -f "$SCALABLE_ICON" "$SYMBOLIC_ICON"
        for size in 16 24 32 48 64 128 256 512; do
            rm -f "$ICONS_DIR/${size}x${size}/apps/omarchy-session.png"
        done
        echo "Removed managed Saved Grid icon set"
    fi
    if desktop_is_managed "$DESKTOP_FILE"; then
        rm -f "$DESKTOP_FILE"
        echo "Removed managed launcher entry: $DESKTOP_FILE"
    fi
    if [[ -e "$BIN_DIR/omarchy-session" || -L "$BIN_DIR/omarchy-session" ]]; then
        if binary_is_managed "$BIN_DIR/omarchy-session"; then
            rm -f "$BIN_DIR/omarchy-session"
            echo "Removed $BIN_DIR/omarchy-session"
        else
            echo "Warning: refusing to remove unrelated $BIN_DIR/omarchy-session" >&2
        fi
    fi
    echo "Saved state under ~/.local/state/omarchy-session was left intact."
    exit 0
fi

mkdir -p "$BIN_DIR"
if [[ "$MODE" == "link" ]]; then
    ln -sfn "$SRC" "$BIN_DIR/omarchy-session"
else
    install -m 0755 "$SRC" "$BIN_DIR/omarchy-session"
fi
install_alias ws
install_alias restore-workspace
install_icons
install_desktop_launcher
chmod +x "$BIN_DIR/omarchy-session" 2>/dev/null || true
restart_autosave_loop_if_configured
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICONS_DIR" >/dev/null 2>&1 || true
fi

echo "Installed omarchy-session ($MODE) to $BIN_DIR"
