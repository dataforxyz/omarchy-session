import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "omarchy-session"
INSTALLER = REPO_ROOT / "scripts" / "install-omarchy-session.sh"


def load_module():
    loader = importlib.machinery.SourceFileLoader("omarchy_session_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DryRunTests(unittest.TestCase):
    def test_restore_dry_run_reports_plan_without_side_effects(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workdir = tmp_path / "project"
            workdir.mkdir()
            session = tmp_path / "session.json"
            session.write_text(json.dumps({
                "savedAt": "2026-05-13T00:00:00Z",
                "activeWindow": {"address": "0xactive", "workspace": {"id": 1, "name": "1"}},
                "windows": [
                    {
                        "address": "0x1",
                        "class": "firefox",
                        "title": "Already here",
                        "workspace": {"id": 1, "name": "1"},
                        "monitorName": "HDMI-A-1",
                    },
                    {
                        "address": "0x2",
                        "class": "ghostty",
                        "title": "Terminal",
                        "workspace": {"id": 2, "name": "2"},
                        "monitorName": "HDMI-A-1",
                        "restoreWorkdir": str(workdir),
                        "restoreArgv": ["bash"],
                        "grouped": ["0x2", "0x3"],
                    },
                    {
                        "address": "0x3",
                        "class": "mystery-app",
                        "title": "Unknown",
                        "workspace": {"id": 2, "name": "2"},
                        "monitorName": "HDMI-A-1",
                        "grouped": ["0x2", "0x3"],
                    },
                    {
                        "address": "0x4",
                        "class": "obsidian",
                        "title": "Notes",
                        "workspace": {"id": 3, "name": "3"},
                        "monitorName": "HDMI-A-1",
                    },
                ],
            }))

            mod.collect_windows = lambda: [{
                "address": "0xc1",
                "class": "firefox",
                "title": "Already here",
                "workspace": {"id": 1, "name": "1"},
            }]
            mod.raw_monitors = lambda: [{"name": "HDMI-A-1"}]

            def forbidden(*args, **kwargs):
                raise AssertionError("dry-run called a side-effect function")

            mod.hypr = forbidden
            mod.hypr_exec_on_workspace = forbidden
            mod.write_session = forbidden
            mod.write_last_restore = forbidden
            mod.notify = forbidden

            out = io.StringIO()
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "ghostty" else None):
                with mock.patch.object(mod.time, "sleep", forbidden):
                    with contextlib.redirect_stdout(out):
                        mod.restore_dry_run(session)

            text = out.getvalue()
            self.assertIn("already open: workspace 1: firefox", text)
            self.assertIn("would launch: workspace 2: ghostty", text)
            self.assertIn("ghostty --working-directory=", text)
            self.assertIn("skipped: workspace 2: mystery-app", text)
            self.assertIn("skipped: workspace 3: obsidian", text)
            self.assertIn("missing command for obsidian: obsidian", text)
            self.assertIn("Monitor actions:", text)
            self.assertIn("Group actions: would attempt to restore 1 saved group", text)
            self.assertIn("Focus actions: would focus saved active window", text)
            self.assertIn("would launch 1, already open 1, skipped 2", text)

    def test_restore_dry_run_cli_forms(self):
        mod = load_module()
        calls = []
        mod.session_path = lambda name=None: Path(f"/tmp/{name or 'default'}.json")
        mod.restore_dry_run = lambda path: calls.append(path)
        mod.restore = lambda *args, **kwargs: self.fail("real restore should not run")
        for argv in (
            ["ws", "restore", "demo", "--dry-run"],
            ["ws", "r", "--dry-run", "demo"],
            ["ws", "plan", "demo"],
            ["ws", "dry-run", "demo"],
        ):
            with mock.patch.object(sys, "argv", argv):
                mod.main()
        self.assertEqual(calls, [Path("/tmp/demo.json")] * 4)


class RestoreCommandTests(unittest.TestCase):
    def test_alacritty_and_keepassxc_restore_commands(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command({
                    "class": "Alacritty",
                    "workspace": {"id": 2, "name": "2"},
                    "restoreWorkdir": str(workdir),
                    "restoreArgv": ["pi"],
                })
                self.assertEqual(reason, "")
                self.assertEqual(cmd, [
                    "alacritty", f"--working-directory={workdir}",
                    "-e", "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l', "omarchy-session-restore", "pi",
                ])

                cmd, reason = mod.launch_command({"class": "org.keepassxc.KeePassXC"})
                self.assertEqual(reason, "")
                self.assertEqual(cmd, ["keepassxc"])

    def test_claude_alias_detection_and_restore_command(self):
        mod = load_module()
        self.assertEqual(mod.claude_command_from_env({}), "clo")
        self.assertEqual(
            mod.claude_command_from_env({"CLAUDE_CONFIG_DIR": "/home/me/.config/claude-aliases/profiles/deepseek"}),
            "clod",
        )
        self.assertEqual(
            mod.claude_command_from_env({"CLAUDE_CONFIG_DIR": "/home/me/.config/claude-aliases/profiles/cliproxy"}),
            "cloc",
        )
        self.assertEqual(
            mod.terminal_restore_argv({
                "class": "Alacritty",
                "agentSession": {"tool": "claude", "command": "cloc", "id": "abc-123"},
            }),
            ["cloc", "--resume", "abc-123"],
        )

    def test_legacy_alacritty_claude_title_reopens_clo(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command({
                    "class": "Alacritty",
                    "title": "Claude",
                    "restoreWorkdir": str(workdir),
                    "restoreArgv": [],
                })
                self.assertEqual(reason, "")
                self.assertEqual(cmd, [
                    "alacritty", f"--working-directory={workdir}",
                    "-e", "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l', "omarchy-session-restore", "clo",
                ])

    def test_legacy_alacritty_pi_title_reopens_pi(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            session = workdir / "session.jsonl"
            session.write_text("{}\n")
            with mock.patch.object(mod, "legacy_pi_session_candidates", lambda win: [str(session)]):
                win = {
                    "class": "Alacritty",
                    "title": "pi - demo:🚧",
                    "restoreWorkdir": str(workdir),
                    "restoreArgv": [],
                }
                mod.enrich_legacy_terminal_targets([win])
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command(win)
                self.assertEqual(reason, "")
                self.assertEqual(cmd, [
                    "alacritty", f"--working-directory={workdir}",
                    "-e", "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l', "omarchy-session-restore",
                    "pi", "--session", str(session),
                ])

    def test_legacy_pi_session_cwd_replaces_home_workdir(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "project"
            home.mkdir()
            project.mkdir()
            session = Path(tmp) / "session.jsonl"
            session.write_text(json.dumps({"cwd": str(project)}) + "\n")
            win = {
                "class": "Alacritty",
                "title": "pi - project:🚧",
                "restoreWorkdir": str(home),
                "restoreArgv": [],
            }
            with mock.patch.object(mod, "legacy_pi_session_candidates", lambda win: [str(session)]):
                mod.enrich_legacy_terminal_targets([win])
            self.assertEqual(win["restoreWorkdir"], str(project))

    def test_chromium_webapp_recovers_single_string_argv_and_class_url(self):
        mod = load_module()
        win = {
            "class": "chrome-perplexity.ai__-Default",
            "procArgv": [
                "/usr/lib/chromium/chromium --app=https://music.youtube.com/ --profile-directory=Profile 3"
            ],
        }
        self.assertEqual(
            mod.browser_app_args(win),
            ("https://perplexity.ai/", ["--profile-directory=Default"]),
        )


class InstallerSafetyTests(unittest.TestCase):
    def test_installer_refuses_unrelated_alias_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            ws = bin_dir / "ws"
            ws.write_text("do not replace\n")
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(["bash", str(INSTALLER), "--copy"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            self.assertIn("refusing to replace unrelated", result.stderr)
            self.assertEqual(ws.read_text(), "do not replace\n")
            self.assertTrue((bin_dir / "restore-workspace").is_symlink())

            subprocess.run(["bash", str(INSTALLER), "--copy", "--force"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            self.assertTrue(ws.is_symlink())
            self.assertEqual(os.readlink(ws), "omarchy-session")

    def test_installer_preserves_unrelated_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            ws = bin_dir / "ws"
            ws.symlink_to("other-tool")
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(["bash", str(INSTALLER), "--copy"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            self.assertIn("refusing to replace unrelated", result.stderr)
            self.assertTrue(ws.is_symlink())
            self.assertEqual(os.readlink(ws), "other-tool")

    def test_installer_refreshes_existing_managed_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            ws = bin_dir / "ws"
            ws.symlink_to("omarchy-session")
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(["bash", str(INSTALLER), "--copy"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            self.assertIn("Refreshed", result.stdout)
            self.assertTrue(ws.is_symlink())
            self.assertEqual(os.readlink(ws), "omarchy-session")


if __name__ == "__main__":
    unittest.main()
