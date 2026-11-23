import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QAbstractSocket
from types import SimpleNamespace

from ide_control import IDEControlBridge


class FakeProblem:
    def __init__(self, text, data):
        self._text = text
        self._data = data

    def text(self):
        return self._text

    def data(self, role):
        if role == Qt.ItemDataRole.UserRole:
            return self._data
        return None


class FakeProblems:
    def __init__(self, rows):
        self.rows = rows

    def count(self):
        return len(self.rows)

    def item(self, index):
        return self.rows[index]


class FakeWindow:
    def __init__(self, root, rows, stack_rows=None, breakpoint_rows=None, dap=None):
        self._root = root
        self.problems = FakeProblems(rows)
        self.call_stack_view = FakeProblems(stack_rows or [])
        self.breakpoints_view = FakeProblems(breakpoint_rows or [])
        self.dap = dap

    def project_root(self):
        return self._root


class IDEControlDiagnosticsTests(unittest.TestCase):
    def test_reads_structured_in_workspace_diagnostics_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "player.gd"
            source.write_text("extends Node\n", encoding="utf-8")
            rows = [
                FakeProblem("Parse Error: secret=private-value Bearer abcdefghijklmnop raw sk-proj-1234567890abcdefghijklmnop ghp_1234567890abcdefghijklmnop AKIA1234567890ABCDEF eyJabcdefghijk.klmnopqrst.uvwxyzABCDE",
                            (str(source), 4, 2)),
            ]
            bridge = IDEControlBridge(FakeWindow(root, rows))
            result = bridge.call("ide_get_diagnostics")
            self.assertEqual(result["count"], 1)
            row = result["diagnostics"][0]
            self.assertEqual(row["path"], "player.gd")
            self.assertEqual((row["line"], row["column"]), (4, 2))
            self.assertNotIn("private-value", row["message"])
            self.assertNotIn("abcdefghijklmnop", row["message"])
            self.assertIn("[REDACTED]", row["message"])
            for token in ("sk-proj-1234567890abcdefghijklmnop", "ghp_1234567890abcdefghijklmnop", "AKIA1234567890ABCDEF", "eyJabcdefghijk.klmnopqrst.uvwxyzABCDE"):
                self.assertNotIn(token, row["message"])
            self.assertIn("structured diagnostics only", result["source"])

    def test_excludes_external_sensitive_and_symlink_paths(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            external = Path(outside) / "outside.gd"
            external.write_text("extends Node\n", encoding="utf-8")
            (root / ".env").write_text("SECRET=private", encoding="utf-8")
            virtual_env = root / ".venv"
            virtual_env.mkdir()
            (virtual_env / "library.gd").write_text("extends Node\\n", encoding="utf-8")
            valid = root / "safe.gd"
            valid.write_text("extends Node\n", encoding="utf-8")
            rows = [
                FakeProblem("external", (str(external), 1, 0)),
                FakeProblem("secret", (str(root / ".env"), 1, 0)),
                FakeProblem("generated", (str(virtual_env / "library.gd"), 1, 0)),
                FakeProblem("safe", (str(valid), 2, 0)),
            ]
            try:
                (root / "linked.gd").symlink_to(external)
                rows.append(FakeProblem("external symlink", (str(root / "linked.gd"), 1, 0)))
                (root / "alias.gd").symlink_to(valid)
                rows.append(FakeProblem("in-workspace symlink", (str(root / "alias.gd"), 1, 0)))
            except OSError:
                pass
            result = IDEControlBridge(FakeWindow(root, rows)).call("ide_get_diagnostics")
            self.assertEqual([row["path"] for row in result["diagnostics"]], ["safe.gd"])


    def test_debug_state_exposes_stack_and_breakpoints_but_not_variable_values(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            frame = root / "player.gd"
            breakpoint = root / "enemy.gd"
            frame.write_text("extends Node\n", encoding="utf-8")
            breakpoint.write_text("extends Node\n", encoding="utf-8")
            external = Path(outside) / "external.gd"
            external.write_text("extends Node\n", encoding="utf-8")
            virtual_env = root / ".venv"
            virtual_env.mkdir()
            generated = virtual_env / "library.gd"
            generated.write_text("extends Node\n", encoding="utf-8")
            stack_rows = [
                FakeProblem("move_player  —  player.gd:7", (str(frame), 7, 2)),
                FakeProblem("external  —  external.gd:2", (str(external), 2, 0)),
                FakeProblem("generated  —  library.gd:4", (str(generated), 4, 0)),
            ]
            try:
                linked_frame = root / "linked_player.gd"
                linked_frame.symlink_to(frame)
                stack_rows.append(FakeProblem("linked  —  linked_player.gd:9", (str(linked_frame), 9, 0)))
            except OSError:
                pass
            breakpoint_rows = [FakeProblem("enemy.gd:5", (str(breakpoint), 5))]
            dap = SimpleNamespace(
                socket=SimpleNamespace(state=lambda: QAbstractSocket.SocketState.ConnectedState),
                frame_id=42, thread_id=3, pending={1: "stackTrace"},
                variables={"password": "never expose"},
            )
            window = FakeWindow(root, [], stack_rows, breakpoint_rows, dap)
            result = IDEControlBridge(window).call("ide_get_debug_state")
            self.assertEqual(result["state"], "paused")
            self.assertTrue(result["connected"])
            self.assertEqual(result["thread_id"], 3)
            self.assertEqual(result["call_stack"], [{
                "function": "move_player", "path": "player.gd", "line": 7, "column": 2
            }])
            self.assertEqual(result["breakpoints"], [{"path": "enemy.gd", "line": 5, "column": 0}])
            self.assertNotIn("variables", result)
            self.assertNotIn("password", str(result))
            running_dap = SimpleNamespace(
                socket=SimpleNamespace(state=lambda: QAbstractSocket.SocketState.ConnectedState),
                frame_id=None, thread_id=3, pending={},
            )
            running = IDEControlBridge(FakeWindow(root, [], stack_rows, breakpoint_rows, running_dap)).call("ide_get_debug_state")
            self.assertEqual(running["state"], "running")
            self.assertEqual(running["call_stack"], [])
            disconnected_dap = SimpleNamespace(
                socket=SimpleNamespace(state=lambda: QAbstractSocket.SocketState.UnconnectedState),
                frame_id=42, thread_id=3, pending={},
            )
            disconnected = IDEControlBridge(FakeWindow(root, [], stack_rows, breakpoint_rows, disconnected_dap)).call("ide_get_debug_state")
            self.assertEqual(disconnected["state"], "disconnected")
            self.assertFalse(disconnected["connected"])
            self.assertEqual(disconnected["call_stack"], [])

    def test_ide_action_checks_expected_workspace_before_navigation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "main.gd"
            source.write_text("extends Node\\n", encoding="utf-8")
            window = FakeWindow(root, [])
            opened = []
            window.open_path = lambda path: opened.append(path)
            bridge = IDEControlBridge(window)

            with self.assertRaisesRegex(RuntimeError, "Workspace identity mismatch"):
                bridge.call("ide_open_file", {
                    "path": "main.gd",
                    "_expected_workspace_id": "0" * 64,
                })
            self.assertEqual(opened, [])

            expected = hashlib.sha256(
                os.path.normcase(str(root.resolve())).encode("utf-8")
            ).hexdigest()
            result = bridge.call("ide_open_file", {
                "path": "main.gd",
                "_expected_workspace_id": expected,
            })
            self.assertEqual(result["opened"], "main.gd")
            self.assertEqual(len(opened), 1)

    def test_ide_state_omits_sensitive_and_symlink_open_editor_paths(self):
        class Cursor:
            def blockNumber(self):
                return 2
            def positionInBlock(self):
                return 4

        class Editor:
            def __init__(self, path):
                self.file_path = path
            def textCursor(self):
                return Cursor()

        class Tabs:
            def __init__(self, widgets):
                self.widgets = widgets
            def count(self):
                return len(self.widgets)
            def widget(self, index):
                return self.widgets[index]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            safe = root / "main.gd"
            secret = root / "credentials.json"
            safe.write_text("extends Node\\n", encoding="utf-8")
            secret.write_text("{}", encoding="utf-8")
            linked = root / "linked.gd"
            try:
                linked.symlink_to(safe)
            except OSError:
                pass

            window = FakeWindow(root, [])
            window.current_editor = lambda: Editor(secret)
            window.tabs = Tabs([Editor(safe), Editor(secret), Editor(linked)])
            result = IDEControlBridge(window).call("ide_get_state")

            self.assertIsNone(result["active_file"])
            self.assertEqual(result["open_files"], ["main.gd"])
            self.assertNotIn("credentials.json", str(result))
            self.assertNotIn("linked.gd", str(result))

    def test_caps_returned_diagnostics_to_one_hundred(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "main.gd"
            source.write_text("extends Node\n", encoding="utf-8")
            rows = [FakeProblem("warning", (str(source), number + 1, 0)) for number in range(105)]
            result = IDEControlBridge(FakeWindow(root, rows)).call("ide_get_diagnostics")
            self.assertEqual(result["count"], 100)
            self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
