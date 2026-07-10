#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install exact agent-session registry integrations without replacing user config."""
import argparse
import json
import os
import shlex
import shutil
import stat
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATIONS = REPO_ROOT / "integrations"


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak.omarchy-session.{int(time.time())}"))


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def integration_paths(home: Path) -> tuple[Path, Path, Path]:
    return (
        home / ".pi/agent/extensions/omarchy-session-registry.ts",
        home / ".local/lib/omarchy-session/claude-session-registry.py",
        home / ".config/opencode/plugins/omarchy-session-registry.ts",
    )


def install_pi(home: Path) -> None:
    destination, _, _ = integration_paths(home)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INTEGRATIONS / "pi-session-registry.ts", destination)
    print(f"Installed Pi extension: {destination}")


def ensure_claude_hook(settings: dict, event: str, command: str) -> bool:
    hooks = settings.setdefault("hooks", {})
    entries = hooks.setdefault(event, [])
    for entry in entries:
        for hook in entry.get("hooks", []):
            if hook.get("type") == "command" and hook.get("command") == command:
                return False
    entries.append({"hooks": [{"type": "command", "command": command}]})
    return True


def install_claude(home: Path) -> None:
    _, hook, _ = integration_paths(home)
    hook.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INTEGRATIONS / "claude-session-registry.py", hook)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    settings_path = home / ".claude/settings.json"
    settings = load_json(settings_path)
    hook_command = shlex.quote(str(hook))
    changed = ensure_claude_hook(settings, "SessionStart", hook_command)
    changed |= ensure_claude_hook(settings, "UserPromptSubmit", hook_command)
    changed |= ensure_claude_hook(settings, "SessionEnd", f"{hook_command} --remove")
    if changed:
        backup(settings_path)
        write_json(settings_path, settings)
    print(f"Installed Claude hook: {hook}")
    print(f"Claude settings: {settings_path} ({'updated' if changed else 'already configured'})")


def install_opencode(home: Path) -> None:
    _, _, plugin = integration_paths(home)
    plugin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INTEGRATIONS / "opencode-session-registry.ts", plugin)

    config_path = home / ".config/opencode/opencode.json"
    config = load_json(config_path)
    plugins = config.setdefault("plugin", [])
    plugin_path = str(plugin)
    normalized = [entry[0] if isinstance(entry, list) and entry else entry for entry in plugins]
    if plugin_path not in normalized:
        plugins.append(plugin_path)
        backup(config_path)
        write_json(config_path, config)
    print(f"Installed OpenCode plugin: {plugin}")
    print(f"OpenCode config: {config_path} ({'updated' if plugin_path not in normalized else 'already configured'})")


def remove_claude_hooks(settings: dict, commands: set[str]) -> bool:
    changed = False
    hooks = settings.get("hooks") or {}
    for event in list(hooks):
        entries = hooks.get(event) or []
        kept_entries = []
        for entry in entries:
            entry_hooks = entry.get("hooks") or []
            if not entry_hooks:
                kept_entries.append(entry)
                continue
            kept_hooks = [
                hook for hook in entry_hooks
                if not (hook.get("type") == "command" and hook.get("command") in commands)
            ]
            if len(kept_hooks) != len(entry_hooks):
                changed = True
            if kept_hooks:
                copied = dict(entry)
                copied["hooks"] = kept_hooks
                kept_entries.append(copied)
        if kept_entries:
            hooks[event] = kept_entries
        elif entries:
            hooks.pop(event, None)
    if not hooks and "hooks" in settings:
        settings.pop("hooks", None)
    return changed


def uninstall_integrations(home: Path, *, pi: bool, claude: bool, opencode: bool) -> None:
    pi_extension, claude_hook, opencode_plugin = integration_paths(home)
    if pi:
        pi_extension.unlink(missing_ok=True)
        print(f"Removed Pi extension: {pi_extension}")
    if claude:
        settings_path = home / ".claude/settings.json"
        settings = load_json(settings_path)
        hook_command = shlex.quote(str(claude_hook))
        commands = {hook_command, f"{hook_command} --remove"}
        if remove_claude_hooks(settings, commands):
            backup(settings_path)
            write_json(settings_path, settings)
        claude_hook.unlink(missing_ok=True)
        print(f"Removed Claude hook: {claude_hook}")
    if opencode:
        config_path = home / ".config/opencode/opencode.json"
        config = load_json(config_path)
        plugins = config.get("plugin") or []
        plugin_path = str(opencode_plugin)
        kept = [entry for entry in plugins if (entry[0] if isinstance(entry, list) and entry else entry) != plugin_path]
        if len(kept) != len(plugins):
            backup(config_path)
            if kept:
                config["plugin"] = kept
            else:
                config.pop("plugin", None)
            write_json(config_path, config)
        opencode_plugin.unlink(missing_ok=True)
        print(f"Removed OpenCode plugin: {opencode_plugin}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi", action="store_true")
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--opencode", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    selected = args.all or not (args.pi or args.claude or args.opencode)
    home = Path.home()
    use_pi = selected or args.pi
    use_claude = selected or args.claude
    use_opencode = selected or args.opencode
    if args.uninstall:
        uninstall_integrations(home, pi=use_pi, claude=use_claude, opencode=use_opencode)
        return 0
    if use_pi:
        install_pi(home)
    if use_claude:
        install_claude(home)
    if use_opencode:
        install_opencode(home)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
