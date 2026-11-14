from pathlib import Path
import re
import subprocess
import sys
import unittest
import importlib.util


ROOT = Path(__file__).resolve().parents[1]


class WindowsStartupTests(unittest.TestCase):
    def test_launcher_uses_label_flow_instead_of_nested_cmd_blocks(self):
        launcher = (ROOT / "launch_windows.bat").read_text(encoding="utf-8")
        self.assertIn(":dependencies_ready", launcher)
        self.assertIn(":setup_complete", launcher)
        self.assertNotRegex(launcher, r"(?im)^\s*if\b.*\(\s*$")
        self.assertNotRegex(launcher, r"(?im)^\s*\)\s*else\s*\(")

    def test_launcher_does_not_embed_parentheses_in_echo_commands(self):
        launcher = (ROOT / "launch_windows.bat").read_text(encoding="utf-8")
        echo_lines = [line for line in launcher.splitlines() if re.match(r"\s*echo\b", line, re.I)]
        self.assertFalse([line for line in echo_lines if "(" in line or ")" in line])

    def test_launcher_runs_the_project_virtual_environment(self):
        launcher = (ROOT / "launch_windows.bat").read_text(encoding="utf-8")
        self.assertIn('".venv\\Scripts\\python.exe" main.py %*', launcher)
        self.assertIn('".venv\\Scripts\\python.exe" -m pip install', launcher)

    def test_setup_script_calls_launcher_in_setup_only_mode(self):
        setup = (ROOT / "setup_windows.bat").read_text(encoding="utf-8")
        self.assertIn("call launch_windows.bat --setup-only", setup)

    def test_direct_startup_reports_missing_pyside_instead_of_exiting_silently(self):
        if importlib.util.find_spec("PySide6") is not None:
            self.skipTest("PySide6 is installed; this test covers the missing-dependency path")
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot start because PySide6 is not installed", result.stderr)
        self.assertIn("launch_windows.bat", result.stderr)


    def test_ai_chat_wrap_option_uses_supported_qtextoption_api(self):
        source = (ROOT / "ai_panel.py").read_text(encoding="utf-8")
        self.assertIn("chat_text_option = QTextOption()", source)
        self.assertIn(
            "chat_text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)",
            source,
        )
        self.assertNotIn(
            "QTextOption(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)",
            source,
        )

    def test_startup_failure_report_is_wired_into_main(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("def _report_startup_failure", source)
        self.assertIn('"startup-crash.log"', source)
        self.assertIn("_report_startup_failure(exc)", source)
        self.assertIn("return int(app.exec())", source)


if __name__ == "__main__":
    unittest.main()
