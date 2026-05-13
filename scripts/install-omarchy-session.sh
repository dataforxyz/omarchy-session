#!/bin/bash
# Install the source-controlled Omarchy workspace/session restore helper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/omarchy-session"
BIN_DIR="${HOME}/.local/bin"
MODE="copy"

usage() {
    cat <<'USAGE'
Usage: scripts/install-omarchy-session.sh [--copy|--link]

Installs scripts/omarchy-session to ~/.local/bin/omarchy-session and refreshes
short aliases:
  ws -> omarchy-session
  restore-workspace -> omarchy-session

--copy is the default and is safest for restored machines.
--link keeps ~/.local/bin/omarchy-session pointed at this git checkout.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --copy) MODE="copy" ;;
        --link) MODE="link" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ ! -f "$SRC" ]]; then
    echo "Missing source script: $SRC" >&2
    exit 1
fi

mkdir -p "$BIN_DIR"
if [[ "$MODE" == "link" ]]; then
    ln -sfn "$SRC" "$BIN_DIR/omarchy-session"
else
    install -m 0755 "$SRC" "$BIN_DIR/omarchy-session"
fi
ln -sfn omarchy-session "$BIN_DIR/ws"
ln -sfn omarchy-session "$BIN_DIR/restore-workspace"
chmod +x "$BIN_DIR/omarchy-session" 2>/dev/null || true

echo "Installed omarchy-session ($MODE) to $BIN_DIR"
