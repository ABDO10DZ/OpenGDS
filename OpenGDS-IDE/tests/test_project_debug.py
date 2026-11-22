import tempfile
import unittest
from pathlib import Path

from project_debug import parse_diagnostics, parse_stack_trace, source_context, triage_error


class ProjectDebugTests(unittest.TestCase):
    def test_parse_diagnostic_and_stack(self):
        text = "main.py:15:2: SyntaxError: invalid syntax\n  File \"main.py\", line 15, in <module>"
        errors = parse_diagnostics(text)
        self.assertEqual(errors[0]["line"], 15)
        self.assertEqual(errors[0]["column"], 2)
        self.assertEqual(parse_stack_trace(text)[0]["line"], 15)

    def test_triage_maps_error_to_workspace_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "main.py").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
            result = triage_error(root, "main.py:3:1: SyntaxError: unexpected token")
            self.assertEqual(len(result["source_contexts"]), 1)
            self.assertEqual(result["source_contexts"][0]["context"]["excerpt"][2]["line"], 3)

    def test_context_blocks_outside_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
            root, outside = Path(td), Path(other)
            (outside / "secret.py").write_text("secret\n", encoding="utf-8")
            (root / ".env").write_text("secret", encoding="utf-8")
            self.assertIn("error", source_context(root, ".env", 1))
            self.assertIn("error", source_context(root, str(outside / "secret.py"), 1))
            try:
                (root / "linked.py").symlink_to(outside / "secret.py")
            except OSError:
                self.skipTest("Symlinks are unavailable")
            self.assertIn("error", source_context(root, "linked.py", 1))


if __name__ == "__main__":
    unittest.main()
