import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "omarchy-session"
INSTALLER = REPO_ROOT / "scripts" / "install-omarchy-session.sh"
INTEGRATION_INSTALLER = REPO_ROOT / "scripts" / "install-agent-integrations.py"


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


class PartialRestoreTests(unittest.TestCase):
    def sample_data(self):
        group = ["0x2", "0x3"]
        return {
            "activeWindow": {"address": "0x3", "workspace": {"id": 2, "name": "2"}},
            "windows": [
                {"address": "0x1", "class": "firefox", "title": "Web", "workspace": {"id": 1, "name": "1"}, "grouped": []},
                {"address": "0x2", "class": "Alacritty", "title": "One", "workspace": {"id": 2, "name": "2"}, "grouped": group, "groupIndex": 0, "groupSize": 2},
                {"address": "0x3", "class": "Alacritty", "title": "Two", "workspace": {"id": 2, "name": "2"}, "grouped": group, "groupIndex": 1, "groupSize": 2},
                {"address": "0x4", "class": "obsidian", "title": "Notes", "workspace": {"id": 3, "name": "3"}, "grouped": []},
            ],
        }

    def test_item_workspace_and_group_selectors(self):
        mod = load_module()
        data = self.sample_data()

        item_targets, total = mod.select_restore_targets(data, {"items": {2}, "groups": set(), "workspaces": set()})
        self.assertEqual(total, 4)
        self.assertEqual([w["address"] for w in item_targets], ["0x2"])
        self.assertEqual(item_targets[0]["grouped"], [])
        self.assertEqual(item_targets[0]["_restoreItemIndex"], 2)

        group_targets, _ = mod.select_restore_targets(data, {"items": set(), "groups": {1}, "workspaces": set()})
        self.assertEqual([w["address"] for w in group_targets], ["0x2", "0x3"])
        self.assertEqual(group_targets[0]["grouped"], ["0x2", "0x3"])

        workspace_targets, _ = mod.select_restore_targets(data, {"items": set(), "groups": set(), "workspaces": {"2"}})
        self.assertEqual([w["address"] for w in workspace_targets], ["0x2", "0x3"])

    def test_partial_selection_drops_unselected_saved_focus(self):
        mod = load_module()
        data = self.sample_data()
        targets, _ = mod.select_restore_targets(data, {"items": {1}, "groups": set(), "workspaces": set()})
        selected = mod.selected_restore_data(data, targets)
        self.assertEqual(selected["activeWindow"], {})
        self.assertEqual([w["address"] for w in selected["windows"]], ["0x1"])

    def test_cli_parses_partial_restore_selectors(self):
        mod = load_module()
        calls = []
        mod.session_path = lambda name=None: Path(f"/tmp/{name or 'default'}.json")
        mod.restore = lambda path, save_undo=True, selection=None: calls.append((path, selection))
        with mock.patch.object(sys, "argv", [
            "ws", "restore", "demo", "--workspace", "2,3", "--group=1-2", "--item", "4,6-7",
        ]):
            mod.main()
        path, selection = calls[0]
        self.assertEqual(path, Path("/tmp/demo.json"))
        self.assertEqual(selection["workspaces"], {"2", "3"})
        self.assertEqual(selection["groups"], {1, 2})
        self.assertEqual(selection["items"], {4, 6, 7})

    def test_empty_selector_is_rejected_instead_of_restoring_everything(self):
        mod = load_module()
        with mock.patch.object(sys, "argv", ["ws", "restore", "demo", "--item="]), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                mod.main()
        self.assertEqual(raised.exception.code, 2)

    def test_interactive_partial_picker_toggles_items_and_plans(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text(json.dumps(self.sample_data()))
            calls = []
            main_menu_count = 0

            def menu(labels, prompt):
                nonlocal main_menu_count
                if prompt == "Toggle workspace":
                    return next(label for label in labels if label.startswith("workspace 2"))
                main_menu_count += 1
                if main_menu_count == 1:
                    return labels[0]
                if main_menu_count == 2:
                    return "Toggle workspace…"
                return next(label for label in labels if label.startswith("Plan selected"))

            mod.run_menu = menu
            mod.restore_dry_run = lambda selected_path, selection=None: calls.append((selected_path, selection))
            mod.partial_restore_picker(path)
            self.assertEqual(calls[0][0], path)
            self.assertEqual(calls[0][1]["items"], {1, 2, 3})


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

    def test_dry_run_matches_live_terminal_when_session_id_temporarily_changes(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.json"
            saved = {
                "address": "0xsaved", "class": "Alacritty", "title": "⠏ cpmex",
                "workspace": {"id": 4, "name": "4"}, "monitorName": "eDP-1",
                "restoreWorkdir": "/tmp/project",
                "agentSession": {"tool": "codex", "id": "picker", "command": "coi"},
            }
            current = {
                "address": "0xcurrent", "class": "Alacritty", "title": "⠹ cpmex",
                "workspace": {"id": 4, "name": "4"}, "monitorName": "eDP-1",
                "restoreWorkdir": "/tmp/project",
                "agentSession": {"tool": "codex", "id": "exact-id", "command": "coi"},
            }
            session.write_text(json.dumps({"windows": [saved]}))
            mod.collect_windows = lambda: [current]
            mod.raw_monitors = lambda: [{"name": "eDP-1"}]
            mod.launch_command = lambda win: self.fail("matching live terminal must not be planned for launch")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.restore_dry_run(session)

            text = out.getvalue()
            self.assertIn("already open: workspace 4: Alacritty", text)
            self.assertIn("Monitor actions: none", text)
            self.assertIn("would launch 0", text)

    def test_global_matching_reserves_a_spinner_title_match_before_generic_workdir_match(self):
        mod = load_module()
        common = {
            "class": "Alacritty", "workspace": {"id": 7, "name": "7"},
            "restoreWorkdir": "/tmp/project", "agentSession": {"tool": "claude", "id": "picker"},
        }
        generic = dict(common, address="0xgeneric", title="juston")
        watcher = dict(common, address="0xwatcher", title="✳ watcher-status-check")
        live_watcher = dict(common, address="0xlive", title="⠂ watcher-status-check")

        matches = mod.match_existing_windows([generic, watcher], [live_watcher])

        self.assertNotIn("0xgeneric", matches)
        self.assertEqual(matches["0xwatcher"]["address"], "0xlive")

    def test_picker_fallback_is_not_treated_as_an_authoritative_session_id(self):
        mod = load_module()
        win = {
            "class": "Alacritty", "workspace": {"id": 4, "name": "4"},
            "restoreWorkdir": "/tmp/project",
            "agentSession": {"tool": "codex", "id": "picker"},
        }
        self.assertEqual(mod.restore_key(win), "ws:4|class:alacritty|dir:/tmp/project")

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
        mod.hypr_dispatch = lambda lua_expr, *args, **kwargs: calls.append(("dispatch", *args)) or True

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

    def test_partial_restore_audit_and_hard_undo_record_only_selected_launches(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session = tmp_path / "session.json"
            session.write_text(json.dumps({
                "windows": [
                    {"address": "0x1", "class": "alacritty", "title": "One", "workspace": {"id": 1, "name": "1"}},
                    {"address": "0x2", "class": "alacritty", "title": "Two", "workspace": {"id": 2, "name": "2"}},
                ],
            }))
            after = [{
                "address": "0xc2", "class": "alacritty", "title": "Two",
                "workspace": {"id": 2, "name": "2"},
            }]
            collections = iter([[], after])
            mod.collect_windows = lambda: next(collections)
            mod.active_window = lambda: {}
            mod.restore_workspace_monitors = lambda targets: (0, 0)
            mod.launch_result = lambda win: "launched"
            mod.apply_saved_state = lambda win, before_addresses: ("0xc2", 0)
            mod.restore_groups = lambda targets, target_outcomes=None: (0, {})
            mod.verify_saved_groups = lambda targets, assigned: []
            mod.restore_saved_focus = lambda data, targets, assigned, fallback: (False, False)
            mod.notify = lambda title, body="": None
            mod.LAST_RESTORE_FILE = tmp_path / "last-restore.json"
            mod.LAST_RESTORE_AUDIT_FILE = tmp_path / "last-restore-audit.json"

            with contextlib.redirect_stdout(io.StringIO()):
                mod.restore(
                    session, save_undo=False,
                    selection={"items": {2}, "groups": set(), "workspaces": set()},
                )

            launch_record = json.loads(mod.LAST_RESTORE_FILE.read_text())
            audit = json.loads(mod.LAST_RESTORE_AUDIT_FILE.read_text())
            self.assertEqual([item["address"] for item in launch_record["launched"]], ["0xc2"])
            self.assertEqual(audit["summary"]["targetCount"], 1)
            self.assertEqual(audit["summary"]["savedTargetCount"], 2)
            self.assertTrue(audit["summary"]["partialRestore"])
            self.assertEqual([target["address"] for target in audit["intended"]["targets"]], ["0x2"])

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
        mod.restore_dry_run = lambda path, selection=None: calls.append((path, selection))
        mod.restore = lambda *args, **kwargs: self.fail("real restore should not run")
        for argv in (
            ["ws", "restore", "demo", "--dry-run"],
            ["ws", "r", "--dry-run", "demo"],
            ["ws", "plan", "demo"],
            ["ws", "dry-run", "demo"],
        ):
            with mock.patch.object(sys, "argv", argv):
                mod.main()
        self.assertEqual([path for path, _ in calls], [Path("/tmp/demo.json")] * 4)
        self.assertTrue(all(not any(selection.values()) for _, selection in calls))


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
            mod.PI_PRIVATE_LAUNCHER = Path("/nonexistent/pi")

            workdir, restore_argv, agent = mod.terminal_child_state(100, str(cwd), {100: [101], 101: [102]}, {})

            self.assertEqual(workdir, str(cwd))
            self.assertEqual(restore_argv, ["pi", "--session", str(session)])
            self.assertEqual(agent["path"], str(session))
            self.assertEqual(agent["match"], "argv-session")

    def test_terminal_child_state_uses_picker_for_pi_continue_without_registry(self):
        mod = load_module()
        cwd = "/tmp/project"
        mod.read_proc_cwd = lambda pid: cwd
        mod.read_proc_argv = lambda pid: ["pi", "--continue"]
        mod.read_proc_environ = lambda pid: {}
        mod.agent_registry_record = lambda tool, pid, env=None: {}
        mod.PI_PRIVATE_LAUNCHER = Path("/nonexistent/pi")

        workdir, restore_argv, agent = mod.terminal_child_state(100, cwd, {100: [101]}, {})

        self.assertEqual(workdir, cwd)
        self.assertEqual(restore_argv, ["pi", "--resume"])
        self.assertEqual(agent["id"], "picker")
        self.assertEqual(agent["match"], "picker-fallback")

    def test_rpi_is_distinguished_from_pi_after_its_wrapper_execs(self):
        mod = load_module()
        cwd = "/tmp/rpi-project"
        mod.read_proc_cwd = lambda pid: cwd
        mod.read_proc_argv = lambda pid: ["pi"]
        mod.read_proc_environ = lambda pid: {"PI_CODING_AGENT_DIR": str(mod.RPI_AGENT_DIR)}
        mod.agent_registry_record = lambda tool, pid, env=None: {}
        mod.PI_PRIVATE_LAUNCHER = Path("/private/pi")

        _, restore_argv, agent = mod.terminal_child_state(100, cwd, {100: [101]}, {})

        self.assertEqual(restore_argv, ["rpi", "--resume"])
        self.assertEqual(agent["tool"], "rpi")
        self.assertEqual(agent["match"], "picker-fallback")

    def test_pi_continue_flag_must_follow_pi_arg(self):
        mod = load_module()
        self.assertTrue(mod.argv_has_pi_continue(["pi", "-c"]))
        self.assertTrue(mod.argv_has_pi_continue(["bash", "-lc", "script", "restore", "pi", "--continue"]))
        self.assertFalse(mod.argv_has_pi_continue(["bash", "-c", "pi"]))
        self.assertFalse(mod.argv_has_pi_continue(["ssh", "-c", "cipher", "host", "pi"]))

    def test_terminal_child_state_uses_picker_for_plain_pi_without_registry(self):
        mod = load_module()
        cwd = "/tmp/project"
        mod.read_proc_cwd = lambda pid: cwd
        mod.read_proc_argv = lambda pid: ["pi"]
        mod.read_proc_environ = lambda pid: {}
        mod.agent_registry_record = lambda tool, pid, env=None: {}
        mod.PI_PRIVATE_LAUNCHER = Path("/nonexistent/pi")

        _, restore_argv, agent = mod.terminal_child_state(100, cwd, {100: [101]}, {})

        self.assertEqual(restore_argv, ["pi", "--resume"])
        self.assertEqual(agent["match"], "picker-fallback")


class AgentSessionMatchingTests(unittest.TestCase):
    def test_explicit_session_arguments_are_preserved_for_all_agents(self):
        mod = load_module()
        self.assertEqual(mod.explicit_claude_session_from_argv(["claude", "--resume", "claude-id"]), "claude-id")
        self.assertEqual(mod.explicit_claude_session_from_argv(["claude", "--session-id=claude-new"]), "claude-new")
        self.assertEqual(mod.explicit_codex_session_from_argv(["codex", "resume", "codex-id"]), "codex-id")
        self.assertEqual(mod.explicit_opencode_session_from_argv(["opencode", "--session", "ses_exact"]), "ses_exact")

    def test_registry_record_requires_matching_pid_and_process_start(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "pi/123.json"
            path.parent.mkdir()
            path.write_text(json.dumps({
                "tool": "pi", "pid": 123, "processStartTicks": 456,
                "sessionId": "session-id", "sessionFile": "/tmp/session.jsonl",
            }))
            mod.agent_registry_root = lambda env=None: root
            mod.proc_start_ticks = lambda pid: 456
            self.assertEqual(mod.agent_registry_record("pi", 123)["sessionId"], "session-id")
            mod.proc_start_ticks = lambda pid: 999
            self.assertEqual(mod.agent_registry_record("pi", 123), {})

    def test_pid_registry_is_authoritative_for_pi_claude_and_opencode(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            session_file = Path(tmp) / "pi.jsonl"
            session_file.write_text("{}\n")
            cwd = "/tmp/project"
            mod.read_proc_cwd = lambda pid: cwd
            mod.read_proc_argv = lambda pid: ["agent"]
            mod.read_proc_environ = lambda pid: {}

            records = {
                ("pi", 101): {"tool": "pi", "pid": 101, "sessionId": "pi-id", "sessionFile": str(session_file), "cwd": cwd},
                ("claude", 201): {"tool": "claude", "pid": 201, "sessionId": "claude-id", "cwd": cwd},
                ("opencode", 301): {"tool": "opencode", "pid": 301, "sessionId": "ses_exact", "cwd": cwd},
            }
            mod.agent_registry_record = lambda tool, pid, env=None: records.get((tool, pid), {})
            mod.PI_PRIVATE_LAUNCHER = Path("/nonexistent/pi")

            pi_result = mod.terminal_child_state(1, cwd, {1: [101]}, {})
            claude_result = mod.terminal_child_state(2, cwd, {2: [201]}, {})
            opencode_result = mod.terminal_child_state(3, cwd, {3: [301]}, {})

            self.assertEqual(pi_result[1], ["pi", "--session", str(session_file)])
            self.assertEqual(pi_result[2]["match"], "pid-registry")
            self.assertEqual(claude_result[1], ["claude", "--resume", "claude-id"])
            self.assertEqual(claude_result[2]["match"], "pid-registry")
            self.assertIn("opencode --session ses_exact", opencode_result[1][-1])
            self.assertEqual(opencode_result[2]["match"], "pid-registry")

    def test_codex_pid_log_mapping_filters_subagent_threads(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".codex"
            sessions = home / "sessions"
            sessions.mkdir(parents=True)
            cwd = "/tmp/project"

            def write_session(name, session_id, thread_source):
                (sessions / name).write_text(json.dumps({
                    "payload": {
                        "id": session_id, "cwd": cwd,
                        "timestamp": "2026-01-01T00:00:00Z",
                        "thread_source": thread_source,
                        "source": {"subagent": {"depth": 1}} if thread_source == "subagent" else "cli",
                    }
                }) + "\n")

            write_session("main.jsonl", "main-thread", "user")
            write_session("sub.jsonl", "sub-thread", "subagent")
            db = home / "logs_2.sqlite"
            conn = sqlite3.connect(db)
            try:
                conn.execute("create table logs (id integer primary key, thread_id text, process_uuid text)")
                conn.executemany(
                    "insert into logs (thread_id, process_uuid) values (?, ?)",
                    [("main-thread", "pid:123:abc"), ("sub-thread", "pid:123:abc")],
                )
                conn.commit()
            finally:
                conn.close()

            env = {"CODEX_HOME": str(home)}
            self.assertEqual(mod.codex_session_from_process_logs(123, cwd, env), "main-thread")

    def _codex_state_home(self, tmp, rows, version=5):
        home = Path(tmp) / ".codex"
        home.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(home / f"state_{version}.sqlite")
        try:
            conn.execute(
                "create table threads (id text primary key, cwd text, name text,"
                " archived integer default 0, thread_source text)"
            )
            conn.executemany(
                "insert into threads (id, cwd, name, archived, thread_source)"
                " values (?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return home

    def test_codex_thread_index_maps_terminal_title_to_thread(self):
        mod = load_module()
        cwd = "/tmp/project"
        with tempfile.TemporaryDirectory() as tmp:
            home = self._codex_state_home(tmp, [
                ("thread-a", cwd, "Add inline subtitle editing", 0, "cli"),
                ("thread-b", cwd, "github long times", 0, "user"),
            ])
            env = {"CODEX_HOME": str(home)}
            self.assertEqual(
                mod.codex_session_from_thread_index("Add inline subtitle editing | project", cwd, env),
                ("thread-a", "thread-index-cwd"),
            )

    def test_codex_thread_index_falls_back_to_unique_name_across_cwds(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            # The terminal was cd'd away from where the thread was created.
            home = self._codex_state_home(tmp, [
                ("thread-a", "/home/user", "Find watcher system", 0, "cli"),
            ])
            env = {"CODEX_HOME": str(home)}
            self.assertEqual(
                mod.codex_session_from_thread_index("Find watcher system | user", "/tmp/elsewhere", env),
                ("thread-a", "thread-index"),
            )

    def test_codex_thread_index_refuses_ambiguous_or_excluded_threads(self):
        mod = load_module()
        cwd = "/tmp/project"
        with tempfile.TemporaryDirectory() as tmp:
            home = self._codex_state_home(tmp, [
                ("thread-a", cwd, "shared name", 0, "cli"),
                ("thread-b", cwd, "shared name", 0, "cli"),
                ("thread-c", cwd, "archived thread", 1, "cli"),
                ("thread-d", cwd, "spawned thread", 0, "subagent"),
            ])
            env = {"CODEX_HOME": str(home)}
            for title in ("shared name", "archived thread", "spawned thread", "unknown"):
                self.assertEqual(
                    mod.codex_session_from_thread_index(title, cwd, env), ("", ""), title
                )

    def test_codex_state_db_prefers_newest_version(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = self._codex_state_home(tmp, [], version=5)
            (home / "state_12.sqlite").write_text("")
            (home / "state_notanumber.sqlite").write_text("")
            self.assertEqual(
                mod.codex_state_db_from_env({"CODEX_HOME": str(home)}),
                home / "state_12.sqlite",
            )
            self.assertIsNone(mod.codex_state_db_from_env({"CODEX_HOME": str(Path(tmp) / "missing")}))

    def test_codex_falls_back_to_thread_index_when_pid_log_is_empty(self):
        mod = load_module()
        cwd = "/tmp/project"
        with tempfile.TemporaryDirectory() as tmp:
            home = self._codex_state_home(tmp, [("thread-a", cwd, "my work", 0, "cli")])
            mod.read_proc_cwd = lambda pid: cwd
            mod.read_proc_environ = lambda pid: {"CODEX_HOME": str(home)}
            mod.read_proc_argv = lambda pid: ["codex"]
            mod.agent_registry_record = lambda tool, pid, env=None: {}
            # The app-server daemon owns the thread, so the pid mapping is empty.
            mod.codex_session_from_process_logs = lambda pid, seen_cwd, env: ""

            workdir, restore_argv, agent = mod.terminal_child_state(1, cwd, {1: [101]}, {}, "my work | project")
            self.assertEqual(restore_argv, ["codex", "resume", "thread-a"])
            self.assertEqual(agent["match"], "thread-index-cwd")
            self.assertEqual(agent["id"], "thread-a")

    def test_missing_exact_mapping_never_guesses_from_cwd(self):
        mod = load_module()
        cwd = "/tmp/project"
        mod.read_proc_cwd = lambda pid: cwd
        mod.read_proc_environ = lambda pid: {}
        mod.agent_registry_record = lambda tool, pid, env=None: {}
        mod.codex_session_from_process_logs = lambda pid, seen_cwd, env: ""
        mod.PI_PRIVATE_LAUNCHER = Path("/nonexistent/pi")

        expectations = [
            (["pi"], ["pi", "--resume"], "picker-fallback"),
            (["claude"], ["claude", "--resume"], "picker-fallback"),
            (["codex"], ["codex", "resume"], "picker-fallback"),
            (["opencode"], ["opencode"], "plain-fallback"),
        ]
        for index, (argv, expected_argv, expected_match) in enumerate(expectations, start=1):
            mod.read_proc_argv = lambda pid, value=argv: value
            result = mod.terminal_child_state(index, cwd, {index: [1000 + index]}, {})
            self.assertEqual(result[1], expected_argv)
            self.assertEqual(result[2]["match"], expected_match)


class WorkspaceOnlySaveTests(unittest.TestCase):
    def test_workspace_only_save_filters_windows_groups_and_focus(self):
        mod = load_module()
        group = ["0x2", "0x3"]
        windows = [
            {"address": "0x1", "class": "firefox", "workspace": {"id": 1, "name": "1"}, "grouped": []},
            {"address": "0x2", "class": "Alacritty", "workspace": {"id": 3, "name": "3"}, "grouped": group, "groupSize": 2},
            {"address": "0x3", "class": "Alacritty", "workspace": {"id": 4, "name": "4"}, "grouped": group, "groupSize": 2},
        ]
        mod.collect_windows = lambda: windows
        mod.active_window = lambda: {"address": "0x1", "class": "firefox", "workspace": {"id": 1, "name": "1"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace-3.json"
            mod.write_session(path, quiet=True, workspaces={"3"})
            saved = json.loads(path.read_text())
        self.assertEqual([win["address"] for win in saved["windows"]], ["0x2"])
        self.assertEqual(saved["windows"][0]["grouped"], [])
        self.assertEqual(saved["activeWindow"], {})

    def test_cli_saves_named_workspace_profile(self):
        mod = load_module()
        calls = []
        mod.session_path = lambda name=None: Path(f"/tmp/{name}.json")
        mod.write_session = lambda path, quiet=False, workspaces=None: calls.append((path, workspaces))
        with mock.patch.object(sys, "argv", ["ws", "save", "focus", "--workspace", "3"]):
            mod.main()
        self.assertEqual(calls, [(Path("/tmp/focus.json"), {"3"})])


class SessionActionMenuTests(unittest.TestCase):
    def test_super_space_submenu_saves_one_workspace_as_named_profile(self):
        mod = load_module()
        windows = [
            {"address": "0x1", "workspace": {"id": 1, "name": "1"}},
            {"address": "0x2", "workspace": {"id": 3, "name": "3"}},
            {"address": "0x3", "workspace": {"id": 3, "name": "3"}},
        ]
        mod.collect_windows = lambda: windows
        mod.run_menu = lambda labels, prompt: next(label for label in labels if label.startswith("Workspace 3"))
        mod.run_input = lambda prompt: "coding"
        mod.session_path = lambda name=None: Path(f"/tmp/{name}.json")
        calls = []
        mod.write_session = lambda path, quiet=False, workspaces=None: calls.append((path, workspaces))

        mod.save_workspace_picker()

        self.assertEqual(calls, [(Path("/tmp/coding.json"), {"3"})])

    def test_super_space_submenu_previews_a_picked_profile_or_autosave(self):
        mod = load_module()
        selected_path = Path("/tmp/autosaves/selected.json")
        mod.run_menu = lambda labels, prompt: next(
            label for label in labels if "Preview restore plan" in label
        )
        mod.pick_session_path = lambda prompt: selected_path
        calls = []
        mod.open_command_terminal = lambda *args: calls.append(args)

        mod.session_action_menu()

        self.assertEqual(calls, [("plan-path", str(selected_path))])

    def test_menu_terminal_uses_installed_script_path_not_launcher_argv_zero(self):
        mod = load_module()
        calls = []
        mod.shutil.which = lambda command: "/usr/bin/xdg-terminal-exec" if command == "xdg-terminal-exec" else None
        mod.subprocess.Popen = lambda argv, **kwargs: calls.append((argv, kwargs))
        with mock.patch.object(sys, "argv", ["omarchy-session", "menu"]):
            mod.open_command_terminal("plan-path", "/tmp/session.json")

        argv, kwargs = calls[0]
        self.assertEqual(argv[:6], [
            "xdg-terminal-exec", "--title=Omarchy Session", "--",
            "bash", "-lc", '"$@"; status=$?; printf "\\nPress Enter to close…"; read -r _; exit "$status"',
        ])
        self.assertEqual(argv[-3], str(Path(mod.__file__).resolve()))
        self.assertEqual(argv[-2:], ["plan-path", "/tmp/session.json"])
        self.assertTrue(kwargs["start_new_session"])

    def test_pick_plan_runs_a_dry_run_for_the_selected_file(self):
        mod = load_module()
        selected_path = Path("/tmp/profiles/work.json")
        mod.pick_session_path = lambda prompt: selected_path
        calls = []
        mod.restore_dry_run = lambda path, selection=None: calls.append(path)

        mod.pick_session("plan")

        self.assertEqual(calls, [selected_path])

    def test_super_space_submenu_routes_to_partial_restore(self):
        mod = load_module()
        selected_path = Path("/tmp/work.json")
        prompts = []
        mod.run_menu = lambda labels, prompt: prompts.append((labels, prompt)) or next(
            label for label in labels if "Restore selected" in label
        )
        mod.pick_session_path = lambda prompt: selected_path
        calls = []
        mod.partial_restore_picker = lambda path: calls.append(path)

        mod.session_action_menu()

        self.assertEqual(calls, [selected_path])
        self.assertEqual(prompts[0][1], "Workspace sessions")
        self.assertTrue(any("Save current layout" in label for label in prompts[0][0]))
        self.assertTrue(any("Choose profile or autosave" in label for label in prompts[0][0]))


class BrowserProfileRestoreTests(unittest.TestCase):
    def test_chromium_profile_and_mode_args_are_preserved_without_urls(self):
        mod = load_module()
        win = {
            "class": "chromium",
            "procArgv": [
                "/usr/bin/chromium", "--profile-directory=Profile 2",
                "--user-data-dir=/tmp/chromium-data", "--incognito",
                "https://example.com/private",
            ],
        }
        self.assertEqual(mod.browser_profile_args(win), [
            "--profile-directory=Profile 2",
            "--user-data-dir=/tmp/chromium-data",
            "--incognito",
        ])
        self.assertEqual(mod.browser_profile_summary(win), "Profile 2")
        with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
            cmd, reason = mod.launch_command(win)
        self.assertEqual(reason, "")
        self.assertEqual(cmd, [
            "chromium", "--profile-directory=Profile 2",
            "--user-data-dir=/tmp/chromium-data", "--incognito",
        ])

    def test_firefox_and_zen_profile_args_are_preserved(self):
        mod = load_module()
        firefox = {
            "class": "firefox",
            "procArgv": ["firefox", "-P", "Work", "--no-remote", "--new-window", "https://example.com"],
        }
        zen = {
            "class": "zen-browser",
            "procArgv": ["zen-browser", "--profile", "/tmp/zen-profile", "--private-window"],
        }
        self.assertEqual(mod.browser_profile_args(firefox), ["-P", "Work", "--no-remote"])
        self.assertEqual(
            mod.browser_profile_args(zen),
            ["--profile", "/tmp/zen-profile", "--private-window"],
        )
        with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
            firefox_cmd, _ = mod.launch_command(firefox)
            zen_cmd, _ = mod.launch_command(zen)
        self.assertEqual(firefox_cmd, ["firefox", "-P", "Work", "--no-remote"])
        self.assertEqual(
            zen_cmd,
            ["zen-browser", "--profile", "/tmp/zen-profile", "--private-window"],
        )

    def test_explicit_browser_profiles_have_distinct_restore_keys_and_matching(self):
        mod = load_module()
        work = {"address": "0x1", "class": "chromium", "browserProfileArgs": ["--profile-directory=Work"]}
        personal = {"address": "0x2", "class": "chromium", "browserProfileArgs": ["--profile-directory=Personal"]}
        same_work = {"address": "0xc1", "class": "chromium", "browserProfileArgs": ["--profile-directory=Work"]}

        self.assertNotEqual(mod.restore_key(work), mod.restore_key(personal))
        self.assertTrue(mod.compatible_current_window(work, same_work))
        self.assertFalse(mod.compatible_current_window(work, personal))
        self.assertEqual(mod.duplicate_singleton_addresses([work, personal]), set())

    def test_profile_can_be_inferred_from_unambiguous_browser_open_files(self):
        mod = load_module()
        firefox_profile = "/home/demo/.mozilla/firefox/abc.default-release"
        self.assertEqual(
            mod.inferred_browser_profile_args(
                {"class": "firefox"},
                [f"{firefox_profile}/.parentlock", f"{firefox_profile}/places.sqlite"],
            ),
            ["--profile", firefox_profile],
        )

        chromium_root = Path.home() / ".config/chromium"
        self.assertEqual(
            mod.inferred_browser_profile_args(
                {"class": "chromium"},
                [str(chromium_root / "Profile 2/History"), str(chromium_root / "Profile 2/Favicons")],
            ),
            ["--profile-directory=Profile 2"],
        )
        self.assertEqual(
            mod.inferred_browser_profile_args(
                {"class": "chromium"},
                [str(chromium_root / "Profile 2/History"), str(chromium_root / "Profile/History")],
            ),
            [],
        )

    def test_firefox_inferred_profile_path_maps_to_portable_profile_name(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            profile = home / ".mozilla/firefox/abc.default-release"
            profile.mkdir(parents=True)
            (home / ".mozilla/firefox/profiles.ini").write_text(
                "[Profile0]\nName=work\nIsRelative=1\nPath=abc.default-release\n"
            )
            with mock.patch.object(mod.Path, "home", return_value=home):
                self.assertEqual(mod.firefox_profile_name("firefox", str(profile)), "work")

    def test_saved_empty_profile_args_do_not_replay_unfiltered_legacy_argv(self):
        mod = load_module()
        win = {
            "class": "firefox",
            "browserProfileArgs": [],
            "procArgv": ["firefox", "-P", "Other"],
        }
        self.assertEqual(mod.browser_profile_args(win), [])


class RestoreCommandTests(unittest.TestCase):
    def test_terminal_neovim_command_and_working_directory_are_preserved(self):
        mod = load_module()
        project = "/tmp/project"
        mod.read_proc_environ = lambda pid: {}
        mod.agent_registry_record = lambda tool, pid, env=None: {}
        mod.read_proc_cwd = lambda pid: project if pid == 102 else "/tmp"
        mod.read_proc_argv = lambda pid: {
            101: ["bash"],
            102: ["nvim", "README.md", "src/main.py"],
        }.get(pid, [])

        workdir, restore_argv, agent = mod.terminal_child_state(
            100, "/tmp", {100: [101], 101: [102]}, {}
        )

        self.assertEqual(workdir, project)
        self.assertEqual(restore_argv, ["nvim", "README.md", "src/main.py"])
        self.assertEqual(agent, {})

    def test_embedded_neovim_is_restored_as_an_interactive_terminal_editor(self):
        mod = load_module()
        project = "/tmp/project"
        mod.read_proc_environ = lambda pid: {}
        mod.agent_registry_record = lambda tool, pid, env=None: {}
        mod.read_proc_cwd = lambda pid: project if pid == 102 else "/tmp"
        mod.read_proc_argv = lambda pid: {
            101: ["xonsh"],
            102: ["nvim", "--embed", "README.md"],
        }.get(pid, [])

        workdir, restore_argv, agent = mod.terminal_child_state(
            100, "/tmp", {100: [101], 101: [102]}, {}
        )

        self.assertEqual(workdir, project)
        self.assertEqual(restore_argv, ["nvim", "README.md"])
        self.assertEqual(agent, {})

    def test_terminal_capture_prefers_interactive_neovim_parent_over_embedded_backend(self):
        mod = load_module()
        project = "/tmp/project"
        mod.read_proc_environ = lambda pid: {}
        mod.agent_registry_record = lambda tool, pid, env=None: {}
        mod.read_proc_cwd = lambda pid: project if pid in {102, 103} else "/tmp"
        mod.read_proc_argv = lambda pid: {
            101: ["bash"],
            102: ["nvim", "README.md"],
            103: ["nvim", "--embed"],
        }.get(pid, [])

        workdir, restore_argv, agent = mod.terminal_child_state(
            100, "/tmp", {100: [101], 101: [102], 102: [103]}, {}
        )

        self.assertEqual(workdir, project)
        self.assertEqual(restore_argv, ["nvim", "README.md"])
        self.assertEqual(agent, {})

    def test_legacy_saved_embedded_neovim_is_sanitized_at_launch(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command({
                    "class": "Alacritty",
                    "restoreWorkdir": str(workdir),
                    "restoreArgv": ["nvim", "--embed", "README.md"],
                })
            self.assertEqual(reason, "")
            self.assertEqual(cmd, [
                "alacritty", f"--working-directory={workdir}",
                "-e", "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l',
                "omarchy-session-restore", "nvim", "README.md",
            ])

    def test_neovim_restore_argv_is_launched_inside_the_terminal(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command({
                    "class": "Alacritty",
                    "restoreWorkdir": str(workdir),
                    "restoreArgv": ["nvim", "README.md"],
                })
            self.assertEqual(reason, "")
            self.assertEqual(cmd, [
                "alacritty", f"--working-directory={workdir}",
                "-e", "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l',
                "omarchy-session-restore", "nvim", "README.md",
            ])

    def test_codex_launcher_marker_and_custom_session_root(self):
        mod = load_module()
        with mock.patch.object(
            mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "my-codex" else None
        ):
            self.assertEqual(
                mod.codex_command_from_process(
                    ["codex"], {"OMARCHY_SESSION_CODEX_COMMAND": "my-codex"}
                ),
                "my-codex",
            )
            self.assertEqual(
                mod.codex_command_from_process(["codex"], {"CODEX_LAUNCHER": "missing-wrapper"}),
                "codex",
            )
            self.assertEqual(
                mod.codex_session_root_from_env({"CODEX_HOME": "/tmp/custom-codex"}),
                Path("/tmp/custom-codex/sessions"),
            )
            self.assertEqual(
                mod.terminal_restore_argv({"restoreArgv": ["codex", "resume", "abc-123"]}),
                ["codex", "resume", "abc-123"],
            )
            self.assertEqual(
                mod.terminal_restore_argv({
                    "agentSession": {"tool": "codex", "command": "my-codex", "id": "abc-123"},
                }),
                ["my-codex", "resume", "abc-123"],
            )

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

    def test_claude_wrapper_marker_and_restore_command(self):
        mod = load_module()
        self.assertEqual(mod.claude_command_from_env({}), "claude")
        with mock.patch.object(
            mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "my-claude" else None
        ):
            self.assertEqual(
                mod.claude_command_from_env({"OMARCHY_SESSION_CLAUDE_COMMAND": "my-claude"}),
                "my-claude",
            )
        self.assertEqual(
            mod.terminal_restore_argv({
                "class": "Alacritty",
                "agentSession": {"tool": "claude", "command": "my-claude", "id": "abc-123"},
            }),
            ["my-claude", "--resume", "abc-123"],
        )

    def test_pi_private_launcher_prevents_gui_path_collision_and_upgrades_old_saves(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / "pi"
            launcher.write_text("#!/bin/sh\n")
            launcher.chmod(0o700)
            mod.PI_PRIVATE_LAUNCHER = launcher

            self.assertEqual(mod.pi_command_from_env({}), str(launcher))
            with mock.patch.object(
                mod.shutil, "which", lambda command: "/usr/bin/my-pi" if command == "my-pi" else None
            ):
                self.assertEqual(
                    mod.pi_command_from_env({"OMARCHY_SESSION_PI_COMMAND": "my-pi"}),
                    "my-pi",
                )
            self.assertEqual(
                mod.terminal_restore_argv({
                    "restoreArgv": ["pi", "--session", "/tmp/saved.jsonl"],
                    "agentSession": {"tool": "pi", "command": "pi"},
                }),
                [str(launcher), "--session", "/tmp/saved.jsonl"],
            )

    def test_legacy_alacritty_claude_title_reopens_claude(self):
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
                    "-e", "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l', "omarchy-session-restore",
                    "claude", "--resume",
                ])

    def test_legacy_alacritty_pi_title_opens_picker_without_guessing(self):
        mod = load_module()
        mod.PI_PRIVATE_LAUNCHER = Path("/nonexistent/pi")
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            win = {
                "class": "Alacritty",
                "title": "pi - demo:🚧",
                "restoreWorkdir": str(workdir),
                "restoreArgv": [],
            }
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command(win)
                self.assertEqual(reason, "")
                self.assertEqual(cmd, [
                    "alacritty", f"--working-directory={workdir}",
                    "-e", "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l', "omarchy-session-restore",
                    "pi", "--resume",
                ])

    def test_omarchy_agent_class_restores_like_foot_terminal(self):
        mod = load_module()
        self.assertIn("org.omarchy.agent", mod.TERMINAL_CLASSES)
        self.assertIn("foot", mod.TERMINAL_CLASSES)
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            # Old saves without agentSession recover the command from procArgv.
            old = {
                "class": "org.omarchy.agent",
                "title": "OC | Turning bluetooth on",
                "procArgv": ["foot", "--app-id=org.omarchy.agent", "-e", "opencode", "--auto"],
                "procCmdline": "foot --app-id=org.omarchy.agent -e opencode --auto",
                "restoreWorkdir": str(workdir),
                "restoreArgv": [],
                "agentSession": {},
            }
            self.assertEqual(mod.terminal_restore_argv(old), ["opencode", "--auto"])
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command(old)
                self.assertEqual(reason, "")
                self.assertEqual(cmd, [
                    "foot", "--app-id=org.omarchy.agent", f"--working-directory={workdir}",
                    "bash", "-lc", '"$@"; exec "${SHELL:-/bin/bash}" -l', "omarchy-session-restore",
                    "opencode", "--auto",
                ])
            # New saves with an exact opencode session resume it in scratchpad.
            new = {
                "class": "org.omarchy.agent",
                "title": "OC | Turning bluetooth on",
                "workspace": {"id": -98, "name": "special:scratchpad"},
                "restoreWorkdir": str(workdir),
                "restoreArgv": ["sh", "-lc", "opencode --session ses_123 || opencode"],
                "agentSession": {"tool": "opencode", "id": "ses_123", "command": "opencode"},
            }
            with mock.patch.object(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"):
                cmd, reason = mod.launch_command(new)
                self.assertEqual(reason, "")
                self.assertIn("--app-id=org.omarchy.agent", cmd)
                self.assertEqual(mod.workspace_spec(new), "special:scratchpad")

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

    def test_uninstall_removes_managed_files_and_preserves_unrelated_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            env = os.environ.copy()
            env["HOME"] = str(home)
            subprocess.run(["bash", str(INSTALLER), "--copy"], env=env, check=True, capture_output=True, text=True)
            desktop_file = home / ".local/share/applications/omarchy-session.desktop"
            scalable_icon = home / ".local/share/icons/hicolor/scalable/apps/omarchy-session.svg"
            png_icon = home / ".local/share/icons/hicolor/64x64/apps/omarchy-session.png"
            self.assertIn("Exec=omarchy-session menu", desktop_file.read_text())
            self.assertIn("Icon=omarchy-session", desktop_file.read_text())
            self.assertTrue(scalable_icon.exists())
            self.assertTrue(png_icon.exists())
            unrelated = bin_dir / "restore-workspace"
            unrelated.unlink()
            unrelated.symlink_to("other-tool")

            subprocess.run(["bash", str(INSTALLER), "--uninstall"], env=env, check=True, capture_output=True, text=True)

            self.assertFalse((bin_dir / "omarchy-session").exists())
            self.assertFalse(desktop_file.exists())
            self.assertFalse(scalable_icon.exists())
            self.assertFalse(png_icon.exists())
            self.assertFalse((bin_dir / "ws").exists())
            self.assertTrue(unrelated.is_symlink())
            self.assertEqual(os.readlink(unrelated), "other-tool")

    def test_uninstall_preserves_unrelated_main_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            command = bin_dir / "omarchy-session"
            command.write_text("#!/bin/sh\necho unrelated\n")
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(
                ["bash", str(INSTALLER), "--uninstall"], env=env,
                check=True, capture_output=True, text=True,
            )
            self.assertIn("refusing to remove unrelated", result.stderr)
            self.assertTrue(command.exists())

    def test_installer_does_not_kill_pid_from_an_inconsistent_external_state_home(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            home = Path(tmp)
            state = Path(external) / "omarchy-session"
            state.mkdir()
            process = subprocess.Popen(["sleep", "30"])
            try:
                (state / "autosave-loop.pid").write_text(str(process.pid))
                env = os.environ.copy()
                env["HOME"] = str(home)
                env["XDG_STATE_HOME"] = external
                subprocess.run(
                    ["bash", str(INSTALLER), "--copy"], env=env,
                    check=True, capture_output=True, text=True,
                )
                self.assertIsNone(process.poll())
                self.assertEqual((state / "autosave-loop.pid").read_text(), str(process.pid))
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_installer_restarts_enabled_autosave_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            service = home / ".config/systemd/user/omarchy-session-autosave.service"
            service.parent.mkdir(parents=True)
            service.write_text("[Service]\nExecStart=%h/.local/bin/omarchy-session autosave-loop\n")
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            systemctl = fake_bin / "systemctl"
            systemctl.write_text("#!/bin/sh\necho \"$*\" >> \"$HOME/systemctl.log\"\nexit 0\n")
            systemctl.chmod(0o755)
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

            subprocess.run(
                ["bash", str(INSTALLER), "--copy"], env=env,
                check=True, capture_output=True, text=True,
            )

            calls = (home / "systemctl.log").read_text()
            self.assertIn("is-enabled --quiet omarchy-session-autosave.service", calls)
            self.assertIn("restart omarchy-session-autosave.service", calls)

    def test_installer_preserves_unrelated_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            icon = home / ".local/share/icons/hicolor/scalable/apps/omarchy-session.svg"
            icon.parent.mkdir(parents=True)
            icon.write_text("<svg><title>Unrelated</title></svg>\n")
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(
                ["bash", str(INSTALLER), "--copy"], env=env,
                check=True, capture_output=True, text=True,
            )
            self.assertIn("refusing to replace unrelated", result.stderr)
            self.assertEqual(icon.read_text(), "<svg><title>Unrelated</title></svg>\n")

    def test_installer_preserves_unrelated_super_space_launcher_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            desktop_file = home / ".local/share/applications/omarchy-session.desktop"
            desktop_file.parent.mkdir(parents=True)
            desktop_file.write_text("[Desktop Entry]\nName=Unrelated\n")
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(
                ["bash", str(INSTALLER), "--copy"], env=env,
                check=True, capture_output=True, text=True,
            )
            self.assertIn("refusing to replace unrelated", result.stderr)
            self.assertEqual(desktop_file.read_text(), "[Desktop Entry]\nName=Unrelated\n")

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


class IntegrationInstallerTests(unittest.TestCase):
    def test_installer_preserves_existing_claude_and_opencode_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            claude_settings = home / ".claude/settings.json"
            claude_settings.parent.mkdir(parents=True)
            claude_settings.write_text(json.dumps({
                "theme": "dark",
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "existing-hook"}]}]},
            }))
            opencode_config = home / ".config/opencode/opencode.json"
            opencode_config.parent.mkdir(parents=True)
            opencode_config.write_text(json.dumps({"provider": {"demo": {}}, "plugin": ["existing-plugin"]}))
            env = os.environ.copy()
            env["HOME"] = str(home)

            subprocess.run([sys.executable, str(INTEGRATION_INSTALLER)], env=env, check=True, capture_output=True, text=True)
            subprocess.run([sys.executable, str(INTEGRATION_INSTALLER)], env=env, check=True, capture_output=True, text=True)

            claude = json.loads(claude_settings.read_text())
            self.assertEqual(claude["theme"], "dark")
            self.assertEqual(claude["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "existing-hook")
            self.assertEqual(len(claude["hooks"]["SessionStart"]), 1)
            self.assertEqual(len(claude["hooks"]["UserPromptSubmit"]), 1)
            self.assertEqual(len(claude["hooks"]["SessionEnd"]), 1)

            opencode = json.loads(opencode_config.read_text())
            self.assertIn("demo", opencode["provider"])
            self.assertIn("existing-plugin", opencode["plugin"])
            self.assertEqual(
                sum("omarchy-session-registry.ts" in str(plugin) for plugin in opencode["plugin"]),
                1,
            )
            self.assertTrue((home / ".pi/agent/extensions/omarchy-session-registry.ts").exists())
            self.assertTrue((home / ".local/lib/omarchy-session/claude-session-registry.py").exists())
            self.assertTrue((home / ".config/opencode/plugins/omarchy-session-registry.ts").exists())

            subprocess.run(
                [sys.executable, str(INTEGRATION_INSTALLER), "--uninstall"],
                env=env, check=True, capture_output=True, text=True,
            )
            claude = json.loads(claude_settings.read_text())
            self.assertEqual(claude["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "existing-hook")
            self.assertNotIn("SessionStart", claude["hooks"])
            self.assertNotIn("UserPromptSubmit", claude["hooks"])
            self.assertNotIn("SessionEnd", claude["hooks"])
            opencode = json.loads(opencode_config.read_text())
            self.assertEqual(opencode["plugin"], ["existing-plugin"])
            self.assertFalse((home / ".pi/agent/extensions/omarchy-session-registry.ts").exists())
            self.assertFalse((home / ".local/lib/omarchy-session/claude-session-registry.py").exists())
            self.assertFalse((home / ".config/opencode/plugins/omarchy-session-registry.ts").exists())


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

        def hypr_dispatch(lua_expr, *legacy, **kwargs):
            # Production code prefers the Hyprland 0.55+ Lua dispatcher and
            # passes the legacy dispatcher as fallback args. The simulator
            # understands both shapes.
            if legacy:
                return hypr("dispatch", *legacy, **kwargs)
            expr = lua_expr or ""
            if "hl.dsp.focus" in expr:
                addr = expr.split("address:", 1)[1].split('"', 1)[0] if "address:" in expr else ""
                if fail_once.get(addr):
                    fail_once[addr] -= 1
                    return False
                focused["addr"] = addr
                return True
            if "hl.dsp.group.toggle()" in expr:
                a = focused["addr"]
                if a and a not in member_to_group:
                    member_to_group[a] = {a}
                return True
            if "into_group" in expr:
                a = focused["addr"]
                if a is not None:
                    for grp in {id(g): g for g in member_to_group.values()}.values():
                        if a not in grp:
                            grp.add(a)
                            member_to_group[a] = grp
                            break
                return True
            return True

        def hypr_focus_window(address, retries=2):
            addr = address.split("address:", 1)[1] if "address:" in address else address
            if fail_once.get(addr):
                fail_once[addr] -= 1
                return False
            focused["addr"] = addr
            return True

        return member_to_group, window_group, hypr, hypr_dispatch, hypr_focus_window

    def test_group_addresses_groups_all_members(self):
        mod = load_module()
        member_to_group, window_group, hypr, hypr_dispatch, hypr_focus_window = self._simulator(mod)
        with mock.patch.object(mod, "window_group", window_group), \
                mock.patch.object(mod, "hypr", hypr), \
                mock.patch.object(mod, "hypr_dispatch", hypr_dispatch), \
                mock.patch.object(mod, "hypr_focus_window", hypr_focus_window), \
                mock.patch.object(mod.time, "sleep", lambda *_: None):
            self.assertTrue(mod.group_addresses(["0x1", "0x2", "0x3"]))
        self.assertEqual(set(member_to_group["0x1"]), {"0x1", "0x2", "0x3"})

    def test_group_addresses_survives_transient_focus_failure(self):
        mod = load_module()
        # The middle window's first focus is dropped; it must still join on retry
        # instead of aborting the whole group (the old code returned False here).
        member_to_group, window_group, hypr, hypr_dispatch, hypr_focus_window = self._simulator(mod, fail_once={"0x2": 1})
        with mock.patch.object(mod, "window_group", window_group), \
                mock.patch.object(mod, "hypr", hypr), \
                mock.patch.object(mod, "hypr_dispatch", hypr_dispatch), \
                mock.patch.object(mod, "hypr_focus_window", hypr_focus_window), \
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
