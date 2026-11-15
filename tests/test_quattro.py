"""Quattro dispatch safety and native-picker acceptance checks."""
import subprocess
import unittest
from unittest import mock
from tests.test_omarchy_session import load_module


class QuattroTests(unittest.TestCase):
    def test_window_selector_cannot_escape_lua_string(self):
        mod = load_module()
        value = 'address:0x1";bad()\n'
        expression = mod.session_dispatch_expression("focuswindow", value)
        self.assertIn('\\";bad()\\010', expression)
        self.assertEqual(expression.count("\n"), 0)

    def test_invalid_geometry_is_rejected_without_dispatch(self):
        mod = load_module()
        with mock.patch.object(mod.subprocess, "run") as run:
            self.assertFalse(mod.hypr("dispatch", "resizewindowpixel", "exact bad 10,address:0x1"))
        run.assert_not_called()

    def test_workspace_launch_quotes_command_and_stays_silent(self):
        mod = load_module()
        with mock.patch.object(mod, "hypr", return_value=True) as hypr, mock.patch.object(mod, "uwsm_cmd", side_effect=lambda command: command):
            self.assertTrue(mod.hypr_exec_on_workspace(["echo", "a b"], "special:test"))
        expression = hypr.call_args.args[1]
        self.assertTrue(expression.startswith("hl.dsp.exec_cmd("))
        self.assertIn('workspace = "special:test silent"', expression)
        self.assertIn("'a b'", expression)

    def test_native_picker_cancellation_does_not_launch_another_menu(self):
        mod = load_module()
        with mock.patch.object(mod.shutil, "which", return_value="/mock/menu"), mock.patch.object(mod.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "")) as run:
            self.assertEqual(mod.run_menu(["Saved session"], "Restore"), "")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][0], "omarchy-menu-select")

    def test_unknown_picker_result_cannot_select_a_session(self):
        mod = load_module()
        with mock.patch.object(mod.shutil, "which", return_value="/mock/menu"), mock.patch.object(mod.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "unknown\n")):
            self.assertEqual(mod.run_menu(["Saved session"], "Restore"), "")
