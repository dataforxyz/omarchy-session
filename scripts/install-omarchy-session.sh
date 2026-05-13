#!/bin/bash
# SPDX-FileCopyrightText: 2026 Ben U
# SPDX-License-Identifier: GPL-3.0-or-later
# Install the source-controlled Omarchy workspace/session restore helper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/omarchy-session"
BIN_DIR="${HOME}/.local/bin"
MODE="copy"
FORCE=0

usage() {
    cat <<'USAGE'
Usage: scripts/install-omarchy-session.sh [--copy|--link] [--force]

Installs scripts/omarchy-session to ~/.local/bin/omarchy-session and refreshes
short aliases:
  ws -> omarchy-session
  restore-workspace -> omarchy-session

--copy is the default and is safest for restored machines.
--link keeps ~/.local/bin/omarchy-session pointed at this git checkout.

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

mkdir -p "$BIN_DIR"
if [[ "$MODE" == "link" ]]; then
    ln -sfn "$SRC" "$BIN_DIR/omarchy-session"
else
    install -m 0755 "$SRC" "$BIN_DIR/omarchy-session"
fi
install_alias ws
install_alias restore-workspace
chmod +x "$BIN_DIR/omarchy-session" 2>/dev/null || true

echo "Installed omarchy-session ($MODE) to $BIN_DIR"
