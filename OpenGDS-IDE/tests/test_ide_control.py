import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject, Qt
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


class FakeWindow(QObject):
    def __init__(self, root, rows, stack_rows=None, breakpoint_rows=None, dap=None):
        super().__init__()
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
                FakeProblem("Parse Error: secret=private-value Bearer abcdefghijklmnop",
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
                rows.append(FakeProblem("symlink", (str(root / "linked.gd"), 1, 0)))
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
