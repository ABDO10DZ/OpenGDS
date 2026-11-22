import tempfile
import unittest
from pathlib import Path

from project_validation import select_tests


class ProjectValidationTests(unittest.TestCase):
    def test_source_change_selects_matching_unittest_without_running_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ai_agent.py").write_text("def run(): pass\n", encoding="utf-8")
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_ai_agent.py").write_text("from ai_agent import run\n", encoding="utf-8")
            (tests / "test_other.py").write_text("def test_other(): pass\n", encoding="utf-8")
            result = select_tests(root, ["ai_agent.py"])
            self.assertEqual([row["path"] for row in result["selected_tests"]], ["tests/test_ai_agent.py"])
            self.assertEqual(len(result["commands"]), 1)
            self.assertIn("test_ai_agent.py", result["commands"][0]["command"])
            self.assertTrue(result["commands"][0]["approval_required"])
            self.assertFalse(result["full_suite_recommended"])

    def test_test_file_change_selects_itself(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_widget.py").write_text("def test_widget(): pass\n", encoding="utf-8")
            result = select_tests(root, ["tests/test_widget.py"])
            self.assertEqual(result["selected_tests"][0]["path"], "tests/test_widget.py")

    def test_project_configuration_change_recommends_full_suite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_core.py").write_text("def test_core(): pass\n", encoding="utf-8")
            result = select_tests(root, ["pyproject.toml"])
            self.assertTrue(result["full_suite_recommended"])
            self.assertIn("pyproject.toml", result["full_suite_reason"])
            self.assertIsNotNone(result["full_suite_command"])

    def test_unknown_mapping_recommends_full_suite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
            result = select_tests(root, ["unrelated.py"])
            self.assertTrue(result["full_suite_recommended"])
            self.assertEqual(result["selected_tests"], [])

    def test_rejects_windows_absolute_and_secret_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                select_tests(root, ["C:\\Users\\secret\\module.py"])
            with self.assertRaises(PermissionError):
                select_tests(root, [".env"])
            with self.assertRaises(ValueError):
                select_tests(root, ["../outside.py"])

    def test_respects_focus_scope_for_changed_and_test_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_ai_agent.py").write_text("from ai_agent import run\n", encoding="utf-8")
            only_docs = lambda path: path.endswith(".md")
            result = select_tests(root, ["ai_agent.py"], scope_allows=only_docs)
            self.assertEqual(result["selected_tests"], [])
            self.assertFalse(result["full_suite_recommended"])


if __name__ == "__main__":
    unittest.main()
