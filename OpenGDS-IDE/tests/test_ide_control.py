import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject, Qt

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
    def __init__(self, root, rows):
        super().__init__()
        self._root = root
        self.problems = FakeProblems(rows)

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
            valid = root / "safe.gd"
            valid.write_text("extends Node\n", encoding="utf-8")
            rows = [
                FakeProblem("external", (str(external), 1, 0)),
                FakeProblem("secret", (str(root / ".env"), 1, 0)),
                FakeProblem("safe", (str(valid), 2, 0)),
            ]
            try:
                (root / "linked.gd").symlink_to(external)
                rows.append(FakeProblem("symlink", (str(root / "linked.gd"), 1, 0)))
            except OSError:
                pass
            result = IDEControlBridge(FakeWindow(root, rows)).call("ide_get_diagnostics")
            self.assertEqual([row["path"] for row in result["diagnostics"]], ["safe.gd"])

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
