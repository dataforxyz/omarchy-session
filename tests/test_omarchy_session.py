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


class PickerTests(unittest.TestCase):
    def test_picker_labels_include_compact_session_counts_and_sort_by_recent(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            older = Path(tmp) / "older.json"
            newer = Path(tmp) / "newer.json"
            older.write_text(json.dumps({
                "windows": [
                    {"class": "firefox", "workspace": {"id": 1, "name": "1"}},
                    {"class": "ghostty", "workspace": {"id": 2, "name": "2"}, "restoreArgv": ["bash"], "grouped": ["0x1", "0x2"]},
                    {"class": "ghostty", "workspace": {"id": 2, "name": "2"}, "grouped": ["0x1", "0x2"]},
                ],
            }))
            newer.write_text(json.dumps({"windows": [{"class": "firefox", "workspace": {"id": 3, "name": "3"}}]}))
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))
            seen = {}
            mod.session_choices = lambda: [("older", older), ("newer", newer)]

            def pick_first(labels, prompt):
                seen["labels"] = labels
                return labels[0]

            mod.run_menu = pick_first
            mod.restore = lambda path, save_undo=True: seen.setdefault("path", path)

            mod.pick_session("restore")

            self.assertEqual(seen["path"], newer)
            self.assertIn("newer — w1 ws1 g0,", seen["labels"][0])
            self.assertIn("older — w3 ws2 g1 t1,", seen["labels"][1])


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
            self.assertIn("Group actions: 1 saved group(s):", text)
            self.assertIn("partial/missing 1", text)
            self.assertIn("Focus actions: would focus saved active window", text)
            self.assertIn("would launch 1, already open 1, skipped 2", text)
            self.assertIn("saved groups 1", text)

    def test_group_verification_reports_correct_partial_failed_and_unassessable(self):
        mod = load_module()
        targets = [
            {"address": "0x1", "class": "ghostty", "title": "A", "workspace": {"id": 1, "name": "1"}, "grouped": ["0x1", "0x2"]},
            {"address": "0x2", "class": "ghostty", "title": "B", "workspace": {"id": 1, "name": "1"}, "grouped": ["0x1", "0x2"]},
            {"address": "0x3", "class": "ghostty", "title": "C", "workspace": {"id": 2, "name": "2"}, "grouped": ["0x3", "0x4"]},
            {"address": "0x4", "class": "ghostty", "title": "D", "workspace": {"id": 2, "name": "2"}, "grouped": ["0x3", "0x4"]},
            {"address": "0x5", "class": "ghostty", "title": "E", "workspace": {"id": 3, "name": "3"}, "grouped": ["0x5", "0x6"]},
            {"address": "0x6", "class": "ghostty", "title": "F", "workspace": {"id": 3, "name": "3"}, "grouped": ["0x5", "0x6"]},
            {"address": "0x7", "class": "ghostty", "title": "G", "workspace": {"id": 4, "name": "4"}, "grouped": ["0x7", "0x8"]},
        ]
        assigned = {
            "0x1": "0xc1",
            "0x2": "0xc2",
            "0x3": "0xc3",
            "0x4": "0xc4",
            "0x5": "0xc5",
            "0x7": "0xc7",
        }
        mod.raw_clients = lambda: [
            {"address": "0xc1", "grouped": ["0xc1", "0xc2"]},
            {"address": "0xc2", "grouped": ["0xc1", "0xc2"]},
            {"address": "0xc3", "grouped": ["0xc3"]},
            {"address": "0xc4", "grouped": ["0xc4"]},
            {"address": "0xc5", "grouped": ["0xc5"]},
            {"address": "0xc7", "grouped": ["0xc7"]},
        ]

        assessments = mod.verify_saved_groups(targets, assigned)
        counts = mod.group_status_counts(assessments, ["correct", "partial_missing", "failed", "cannot_assess"])

        self.assertEqual(counts["correct"], 1)
        self.assertEqual(counts["partial_missing"], 1)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["cannot_assess"], 1)
        failed = next(a for a in assessments if a["status"] == "failed")
        self.assertEqual(failed["presentButNotGrouped"], ["0xc3", "0xc4"])
        partial = next(a for a in assessments if a["status"] == "partial_missing")
        self.assertEqual(partial["missingSavedAddresses"], ["0x6"])

    def test_hypr_retries_transient_dispatch_failure(self):
        mod = load_module()
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0 if len(calls) == 2 else 1)

        with mock.patch.object(mod.subprocess, "run", fake_run):
            with mock.patch.object(mod.time, "sleep", lambda delay: None):
                self.assertTrue(mod.hypr("dispatch", "workspace", "1", retries=1))

        self.assertEqual(len(calls), 2)

    def test_restore_summary_reports_launch_detection_and_dispatch_failures(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.json"
            session.write_text(json.dumps({
                "windows": [
                    {"address": "0x1", "class": "alacritty", "workspace": {"id": 1, "name": "1"}},
                    {"address": "0x2", "class": "alacritty", "workspace": {"id": 2, "name": "2"}},
                ],
            }))
            launch_statuses = iter(["launched", "dispatch_failed"])
            mod.collect_windows = lambda: []
            mod.active_window = lambda: {}
            mod.restore_workspace_monitors = lambda targets: (0, 1)
            mod.launch_result = lambda win: next(launch_statuses)
            mod.apply_saved_state = lambda win, before_addresses: ("", 1)
            mod.restore_groups = lambda targets, target_outcomes=None: (0, {})
            mod.verify_saved_groups = lambda targets, assigned: []
            mod.restore_saved_focus = lambda data, targets, assigned, fallback: (False, True)
            mod.write_last_restore = lambda path, launched: None
            mod.write_restore_audit = lambda *args, **kwargs: None
            mod.notify = lambda title, body="": None

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.restore(session, save_undo=False)

            text = out.getvalue()
            self.assertIn("launched 1", text)
            self.assertIn("launch dispatch failed 1", text)
            self.assertIn("launched undetected 1", text)
            self.assertIn("state dispatch failures 1", text)
            self.assertIn("monitor placement failures 1", text)
            self.assertIn("focus restore failed", text)

    def test_assign_current_addresses_prefers_detected_address_over_reused_saved_address(self):
        mod = load_module()
        targets = [{
            "address": "0xsaved",
            "class": "firefox",
            "title": "Pull requests",
            "workspace": {"id": 2, "name": "2"},
        }]
        current = [
            {
                "address": "0xsaved",
                "class": "Alacritty",
                "title": "Terminal",
                "workspace": {"id": 3, "name": "3"},
            },
            {
                "address": "0xactual",
                "class": "firefox",
                "title": "Pull requests",
                "workspace": {"id": 2, "name": "2"},
            },
        ]

        assigned = mod.assign_current_addresses(targets, current, preferred={"0xsaved": "0xactual"})

        self.assertEqual(assigned, {"0xsaved": "0xactual"})

    def test_apply_saved_state_moves_detected_window_to_saved_workspace(self):
        mod = load_module()
        target = {
            "address": "0xsaved",
            "class": "Alacritty",
            "title": "Terminal",
            "workspace": {"id": 4, "name": "4"},
            "floating": False,
        }
        calls = []
        mod.find_new_window = lambda target, before_addresses: {"address": "0xnew"}
        mod.hypr = lambda *args, **kwargs: calls.append(args) or True

        address, failures = mod.apply_saved_state(target, set())

        self.assertEqual(address, "0xnew")
        self.assertEqual(failures, 0)
        self.assertIn(("dispatch", "movetoworkspacesilent", "4,address:0xnew"), calls)

    def test_restore_logs_unknown_app_classes_grouped_by_class(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session = tmp_path / "session.json"
            session.write_text(json.dumps({
                "windows": [
                    {
                        "address": "0x1",
                        "class": "mystery-app",
                        "title": "One",
                        "workspace": {"id": 2, "name": "2"},
                    },
                    {
                        "address": "0x2",
                        "class": "Mystery-App",
                        "title": "Two",
                        "workspace": {"id": 3, "name": "3"},
                    },
                ],
            }))
            collections = iter([[], []])
            mod.collect_windows = lambda: next(collections)
            mod.active_window = lambda: {}
            mod.restore_workspace_monitors = lambda targets: (0, 0)
            mod.restore_groups = lambda targets, target_outcomes=None: (0, {})
            mod.verify_saved_groups = lambda targets, assigned: []
            mod.restore_saved_focus = lambda data, targets, assigned, fallback: (False, False)
            mod.notify = lambda title, body="": None
            mod.LAST_RESTORE_FILE = tmp_path / "last-restore.json"
            mod.LAST_RESTORE_AUDIT_FILE = tmp_path / "last-restore-audit.json"
            mod.UNKNOWN_CLASSES_FILE = tmp_path / "unknown-classes.json"

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                mod.restore(session, save_undo=False)

            data = json.loads(mod.UNKNOWN_CLASSES_FILE.read_text())
            group = data["classes"]["mystery-app"]
            self.assertEqual(group["count"], 2)
            self.assertEqual(group["class"], "mystery-app")
            self.assertEqual([example["title"] for example in group["examples"]], ["Two", "One"])
            self.assertEqual({example["source"] for example in group["examples"]}, {str(session)})

    def test_restore_writes_audit_with_before_after_and_verification(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session = tmp_path / "session.json"
            session.write_text(json.dumps({
                "activeWindow": {"address": "0x2", "workspace": {"id": 2, "name": "2"}},
                "windows": [
                    {
                        "address": "0x1",
                        "class": "firefox",
                        "title": "Already",
                        "workspace": {"id": 1, "name": "1"},
                        "monitorName": "HDMI-A-1",
                    },
                    {
                        "address": "0x2",
                        "class": "alacritty",
                        "title": "Terminal",
                        "workspace": {"id": 2, "name": "2"},
                        "monitorName": "HDMI-A-1",
                    },
                ],
            }))
            before_windows = [{
                "address": "0xc1",
                "class": "firefox",
                "title": "Already",
                "workspace": {"id": 1, "name": "1"},
                "monitorName": "HDMI-A-1",
            }]
            after_windows = [
                before_windows[0],
                {
                    "address": "0xc2",
                    "class": "alacritty",
                    "title": "Terminal",
                    "workspace": {"id": 2, "name": "2"},
                    "monitorName": "HDMI-A-1",
                },
                {
                    "address": "0xextra",
                    "class": "notes",
                    "title": "Extra",
                    "workspace": {"id": 9, "name": "9"},
                    "monitorName": "HDMI-A-1",
                },
            ]
            collections = iter([before_windows, after_windows])
            mod.collect_windows = lambda: next(collections)
            mod.active_window = lambda: {"address": "0xc2", "workspace": {"id": 2, "name": "2"}}
            mod.restore_workspace_monitors = lambda targets: (1, 0)
            mod.launch_result = lambda win: "launched"
            mod.apply_saved_state = lambda win, before_addresses: ("0xc2", 0)
            mod.restore_groups = lambda targets, target_outcomes=None: (0, {})
            mod.verify_saved_groups = lambda targets, assigned: []
            mod.restore_saved_focus = lambda data, targets, assigned, fallback: (True, True)
            mod.notify = lambda title, body="": None
            mod.LAST_RESTORE_FILE = tmp_path / "last-restore.json"
            mod.LAST_RESTORE_AUDIT_FILE = tmp_path / "last-restore-audit.json"

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.restore(session, save_undo=False)

            text = out.getvalue()
            self.assertIn("audit saved", text)
            self.assertTrue(mod.LAST_RESTORE_FILE.exists())
            self.assertTrue(mod.LAST_RESTORE_AUDIT_FILE.exists())
            audit = json.loads(mod.LAST_RESTORE_AUDIT_FILE.read_text())
            self.assertEqual(audit["source"], str(session))
            self.assertEqual(audit["before"]["windowCount"], 1)
            self.assertEqual(audit["after"]["windowCount"], 3)
            self.assertEqual(audit["summary"]["launched"], 1)
            self.assertEqual(audit["verification"]["matchedCount"], 2)
            self.assertEqual(audit["verification"]["missingCount"], 0)
            self.assertEqual(audit["verification"]["extraNewWindowCount"], 1)
            self.assertTrue(audit["verification"]["matchedWellEnough"])
            self.assertEqual(audit["launched"][0]["address"], "0xc2")
            self.assertEqual([o["status"] for o in audit["targetOutcomes"]], ["already_open", "launched_detected"])
            self.assertEqual(audit["targetOutcomes"][1]["currentAddress"], "0xc2")

    def test_duplicate_singleton_targets_are_reported_as_restore_limitations(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session = tmp_path / "session.json"
            session.write_text(json.dumps({
                "windows": [
                    {"address": "0x1", "class": "firefox", "title": "First", "workspace": {"id": 1, "name": "1"}},
                    {"address": "0x2", "class": "firefox", "title": "Second", "workspace": {"id": 2, "name": "2"}},
                ],
            }))
            before_windows = [{"address": "0xc1", "class": "firefox", "title": "First", "workspace": {"id": 1, "name": "1"}}]
            collections = iter([before_windows, before_windows])
            mod.collect_windows = lambda: next(collections)
            mod.active_window = lambda: {}
            mod.restore_workspace_monitors = lambda targets: (0, 0)
            mod.launch_result = lambda win: self.fail("duplicate singleton should not launch")
            mod.restore_groups = lambda targets, target_outcomes=None: (0, {})
            mod.verify_saved_groups = lambda targets, assigned: []
            mod.restore_saved_focus = lambda data, targets, assigned, fallback: (False, False)
            mod.notify = lambda title, body="": None
            mod.LAST_RESTORE_FILE = tmp_path / "last-restore.json"
            mod.LAST_RESTORE_AUDIT_FILE = tmp_path / "last-restore-audit.json"

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.restore(session, save_undo=False)

            text = out.getvalue()
            self.assertIn("duplicate singleton unsupported 1", text)
            self.assertIn("restore needs review", text)
            audit = json.loads(mod.LAST_RESTORE_AUDIT_FILE.read_text())
            self.assertEqual([o["status"] for o in audit["targetOutcomes"]], ["already_open", "duplicate_singleton_unsupported"])
            self.assertEqual(audit["summary"]["duplicateSingletonUnsupported"], 1)
            self.assertEqual(audit["verification"]["missingCount"], 0)
            self.assertEqual(audit["verification"]["unsupportedDuplicateSingletonCount"], 1)
            self.assertFalse(audit["verification"]["matchedWellEnough"])

    def test_restore_review_note_reports_verification_failures(self):
        mod = load_module()
        note = mod.restore_review_note({
            "matchedWellEnough": False,
            "missingCount": 1,
            "unsupportedDuplicateSingletonCount": 2,
            "workspaceMismatchCount": 0,
            "monitorMismatchCount": 1,
            "groups": {"counts": {"partial_missing": 1, "failed": 2, "cannot_assess": 0}},
            "focus": {"failed": True},
        })
        self.assertIn("restore needs review", note)
        self.assertIn("missing 1", note)
        self.assertIn("duplicate singleton unsupported 2", note)
        self.assertIn("monitor mismatches 1", note)
        self.assertIn("group failed 2", note)
        self.assertIn("focus failed", note)

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


class PiSessionDetectionTests(unittest.TestCase):
    def test_terminal_child_state_preserves_explicit_pi_session_arg(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            session = Path(tmp) / "saved.jsonl"
            session.write_text(json.dumps({"type": "session", "id": "saved", "cwd": str(cwd)}) + "\n")
            newer = Path(tmp) / "newer.jsonl"
            newer.write_text(json.dumps({"type": "session", "id": "newer", "cwd": str(cwd)}) + "\n")

            def fake_cwd(pid):
                return str(cwd) if pid in {101, 102} else ""

            def fake_argv(pid):
                if pid == 101:
                    return ["bash", "-lc", '"$@"; exec "$SHELL" -l', "omarchy-session-restore", "pi", "--session", str(session)]
                if pid == 102:
                    return ["pi"]
                return []

            mod.read_proc_cwd = fake_cwd
            mod.read_proc_argv = fake_argv
            mod.pi_sessions_for_process = lambda seen_cwd, pid: [str(newer), str(session)]

            workdir, restore_argv, agent = mod.terminal_child_state(100, str(cwd), {100: [101], 101: [102]}, {})

            self.assertEqual(workdir, str(cwd))
            self.assertEqual(restore_argv, ["pi", "--session", str(session)])
            self.assertEqual(agent["path"], str(session))
            self.assertEqual(agent["match"], "argv-session")

    def test_terminal_child_state_preserves_pi_continue_arg(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()

            def fake_cwd(pid):
                return str(cwd) if pid in {101, 102} else ""

            def fake_argv(pid):
                if pid == 101:
                    return ["bash", "-lc", '"$@"; exec "$SHELL" -l', "omarchy-session-restore", "pi", "--continue"]
                if pid == 102:
                    return ["pi"]
                return []

            mod.read_proc_cwd = fake_cwd
            mod.read_proc_argv = fake_argv
            mod.pi_sessions_for_process = lambda seen_cwd, pid: self.fail("--continue should not use process-start scoring")

            workdir, restore_argv, agent = mod.terminal_child_state(100, str(cwd), {100: [101], 101: [102]}, {})

            self.assertEqual(workdir, str(cwd))
            self.assertEqual(restore_argv, ["pi", "--continue"])
            self.assertEqual(agent["id"], "latest")
            self.assertEqual(agent["match"], "argv-continue")

    def test_pi_continue_flag_must_follow_pi_arg(self):
        mod = load_module()
        self.assertTrue(mod.argv_has_pi_continue(["pi", "-c"]))
        self.assertTrue(mod.argv_has_pi_continue(["bash", "-lc", "script", "restore", "pi", "--continue"]))
        self.assertFalse(mod.argv_has_pi_continue(["bash", "-c", "pi"]))
        self.assertFalse(mod.argv_has_pi_continue(["ssh", "-c", "cipher", "host", "pi"]))

    def test_terminal_child_state_matches_plain_pi_by_process_start_time(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            mod.PI_SESSION_ROOT = Path(tmp) / "sessions"
            session_dir = mod.pi_session_dir_for_cwd(str(cwd))
            session_dir.mkdir(parents=True)
            older = session_dir / "2026-01-01T00-00-00-000Z_older.jsonl"
            current = session_dir / "2026-02-01T00-00-00-000Z_current.jsonl"
            older.write_text(json.dumps({"type": "session", "id": "older", "cwd": str(cwd)}) + "\n")
            current.write_text(json.dumps({"type": "session", "id": "current", "cwd": str(cwd)}) + "\n")
            os.utime(older, (200, 200))
            os.utime(current, (100, 100))

            mod.read_proc_cwd = lambda pid: str(cwd) if pid == 101 else ""
            mod.read_proc_argv = lambda pid: ["pi"] if pid == 101 else []
            mod.proc_start_time = lambda pid: mod.pi_session_created_at(str(current)) + 2

            workdir, restore_argv, agent = mod.terminal_child_state(100, str(cwd), {100: [101]}, {})

            self.assertEqual(workdir, str(cwd))
            self.assertEqual(restore_argv, ["pi", "--session", str(current)])
            self.assertEqual(agent["path"], str(current))
            self.assertEqual(agent["match"], "cwd-process-start")


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

                cmd, reason = mod.launch_command({"class": "org.telegram.desktop"})
                self.assertEqual(reason, "")
                self.assertEqual(cmd, ["Telegram"])

    def test_zen_browser_restores_as_singleton_app(self):
        mod = load_module()
        win = {"class": "zen", "title": "Dashboard — Zen Browser",
               "workspace": {"id": -98, "name": "special:scratchpad"}}
        # Zen is a single-process Firefox fork: keyed like firefox, not skipped.
        self.assertTrue(mod.is_singleton(win))
        self.assertEqual(mod.restore_key(win), "app:zen")
        with mock.patch.object(mod.shutil, "which",
                               lambda cmd: "/usr/bin/zen-browser" if cmd == "zen-browser" else None):
            cmd, reason = mod.launch_command(win)
            self.assertEqual(reason, "")
            self.assertEqual(cmd, ["zen-browser"])

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


class GroupRestoreTests(unittest.TestCase):
    """Exercise group_addresses against a tiny in-memory Hyprland simulator.

    Hyprland grouping is asynchronous and adjacency-dependent, so the real value
    is in surviving dropped dispatches and re-trying members that did not join on
    the first pass.
    """

    def _simulator(self, mod, fail_once=None):
        fail_once = dict(fail_once or {})
        member_to_group: dict[str, set] = {}
        focused = {"addr": None}

        def window_group(address):
            grp = member_to_group.get(address)
            return list(grp) if grp else []

        def hypr(*args, **kwargs):
            cmd = args[1] if len(args) >= 2 else ""
            if cmd == "focuswindow":
                addr = args[2].split("address:", 1)[1]
                if fail_once.get(addr):
                    fail_once[addr] -= 1
                    return False
                focused["addr"] = addr
                return True
            if cmd == "togglegroup":
                a = focused["addr"]
                if a and a not in member_to_group:
                    member_to_group[a] = {a}
                return True
            if cmd == "moveintogroup":
                a = focused["addr"]
                if a is not None:
                    for grp in {id(g): g for g in member_to_group.values()}.values():
                        if a not in grp:
                            grp.add(a)
                            member_to_group[a] = grp
                            break
                return True
            return True

        return member_to_group, window_group, hypr

    def test_group_addresses_groups_all_members(self):
        mod = load_module()
        member_to_group, window_group, hypr = self._simulator(mod)
        with mock.patch.object(mod, "window_group", window_group), \
                mock.patch.object(mod, "hypr", hypr), \
                mock.patch.object(mod.time, "sleep", lambda *_: None):
            self.assertTrue(mod.group_addresses(["0x1", "0x2", "0x3"]))
        self.assertEqual(set(member_to_group["0x1"]), {"0x1", "0x2", "0x3"})

    def test_group_addresses_survives_transient_focus_failure(self):
        mod = load_module()
        # The middle window's first focus is dropped; it must still join on retry
        # instead of aborting the whole group (the old code returned False here).
        member_to_group, window_group, hypr = self._simulator(mod, fail_once={"0x2": 1})
        with mock.patch.object(mod, "window_group", window_group), \
                mock.patch.object(mod, "hypr", hypr), \
                mock.patch.object(mod.time, "sleep", lambda *_: None):
            self.assertTrue(mod.group_addresses(["0x1", "0x2", "0x3"]))
        self.assertEqual(set(member_to_group["0x1"]), {"0x1", "0x2", "0x3"})

    def test_group_addresses_noops_when_already_grouped(self):
        mod = load_module()
        shared = {"0x1", "0x2"}
        member_to_group = {"0x1": shared, "0x2": shared}

        def window_group(address):
            grp = member_to_group.get(address)
            return list(grp) if grp else []

        calls = []

        def hypr(*args, **kwargs):
            calls.append(args)
            return True

        with mock.patch.object(mod, "window_group", window_group), \
                mock.patch.object(mod, "hypr", hypr), \
                mock.patch.object(mod.time, "sleep", lambda *_: None):
            self.assertTrue(mod.group_addresses(["0x1", "0x2"]))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
