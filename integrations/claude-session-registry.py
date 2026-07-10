#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude Code hook that publishes the active session for omarchy-session."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

TOOL = "claude"


def proc_argv(pid: int) -> list[str]:
    try:
        return [part.decode(errors="replace") for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part]
    except Exception:
        return []


def proc_parent(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(errors="ignore").splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except Exception:
        pass
    return 0


def process_start_ticks(pid: int) -> int:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text(errors="ignore").rsplit(") ", 1)[1].split()[19])
    except Exception:
        return 0


def claude_pid() -> int:
    pid = os.getppid()
    for _ in range(12):
        argv = proc_argv(pid)
        names = {Path(arg).name.lower() for arg in argv}
        if any(name == "claude" or name.startswith("claude.") for name in names):
            return pid
        pid = proc_parent(pid)
        if pid <= 1:
            break
    return 0


def registry_path(pid: int) -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime_dir) / "omarchy-session/agents" / TOOL / f"{pid}.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    try:
        payload = json.load(os.sys.stdin)
    except Exception:
        payload = {}

    pid = claude_pid()
    if not pid:
        return 0
    path = registry_path(pid)
    session_id = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    if args.remove:
        try:
            current = json.loads(path.read_text())
            if not session_id or current.get("sessionId") == session_id:
                path.unlink(missing_ok=True)
        except Exception:
            pass
        return 0

    session_file = payload.get("transcript_path") or ""
    cwd = payload.get("cwd") or os.getcwd()
    if not session_id:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {
        "version": 1,
        "tool": TOOL,
        "registrationId": f"{pid}:{session_id}",
        "pid": pid,
        "processStartTicks": process_start_ticks(pid),
        "sessionId": session_id,
        "sessionFile": session_file,
        "cwd": cwd,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "claude-hook",
    }
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(record) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
