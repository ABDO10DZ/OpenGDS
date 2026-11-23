import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcp_server import OpenGDSMCPService, build_server


class FakeBackend:
    def inspect(self, mode, path):
        return f"{mode}:{Path(path).name}"

    def decompile(self, path):
        return "extends Node\n"

    def compile(self, source, output, **kwargs):
        Path(output).write_bytes(b"temporary-gdsc")
        return SimpleNamespace(stdout="compiled")


class OpenGDSMCPServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backend = FakeBackend()
        self.cache = Path(self.temp.name).parent / (Path(self.temp.name).name + "-mcp-cache")
        self.service = OpenGDSMCPService(self.root, self.backend, cache_root=self.cache)
        (self.root / "main.gd").write_text("extends Node\n", encoding="utf-8")
        (self.root / "main.gdc").write_bytes(b"GDSC")
        (self.root / "README.md").write_text("OpenGDS project\n", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.cache, ignore_errors=True)
        self.temp.cleanup()

    def test_list_and_read_workspace_files(self):
        self.assertIn("main.gd", self.service.list_files())
        self.assertEqual(self.service.read_file("README.md")["content"], "OpenGDS project\n")

    def test_blocks_absolute_parent_and_sensitive_paths(self):
        for path in ("../outside.txt", str(self.root / "README.md"), ".env", "private.pem",
                     ".aws/credentials", ".ssh/id_rsa", ".npmrc"):
            with self.subTest(path=path), self.assertRaises((ValueError, PermissionError)):
                self.service.safe_path(path)

    def test_inspection_uses_bundled_backend(self):
        result = self.service.inspect_gdc("main.gdc", "info")
        self.assertEqual(result["report"], "info:main.gdc")

    def test_decompile_is_preview_only(self):
        result = self.service.decompile_preview("main.gdc")
        self.assertFalse(result["written_to_workspace"])
        self.assertFalse((self.root / "main.gd.gd").exists())
        self.assertIn("extends Node", result["source_preview"])

    def test_compile_check_uses_temporary_output(self):
        result = self.service.compile_check("main.gd")
        self.assertTrue(result["compiled"])
        self.assertFalse(result["written_to_workspace"])
        self.assertEqual(result["output_bytes"], len(b"temporary-gdsc"))
        self.assertFalse((self.root / "main.gdc").read_bytes() == b"temporary-gdsc")


    def test_list_files_prunes_excluded_directories(self):
        hidden = self.root / ".venv"
        hidden.mkdir()
        (hidden / "private.gd").write_text("secret", encoding="utf-8")
        cache = self.root / "__pycache__"
        cache.mkdir()
        (cache / "module.pyc").write_bytes(b"bytecode")
        listed = self.service.list_files()
        self.assertIn("main.gd", listed)
        self.assertNotIn(".venv/private.gd", listed)
        self.assertNotIn("__pycache__/module.pyc", listed)

    def test_safe_path_rejects_in_workspace_symlink(self):
        target = self.root / "main.gd"
        alias = self.root / "alias.gd"
        try:
            alias.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks are unavailable")
        with self.assertRaises(PermissionError):
            self.service.safe_path("alias.gd")

    def test_compile_and_gdsc_size_limits_are_enforced(self):
        with patch("mcp_server.MAX_GDSCRIPT_BYTES", 2):
            with self.assertRaises(ValueError):
                self.service.compile_check("main.gd")
        with patch("mcp_server.MAX_GDSC_BYTES", 2):
            with self.assertRaises(ValueError):
                self.service.inspect_gdc("main.gdc")
            with self.assertRaises(ValueError):
                self.service.decompile_preview("main.gdc")

    def test_search_text(self):
        result = self.service.search_text("OpenGDS")
        self.assertEqual(result["matches"][0]["path"], "README.md")


    def test_project_index_and_symbol_analysis_tools(self):
        (self.root / "library.py").write_text(
            "class Widget:\n    def render(self): pass\n", encoding="utf-8"
        )
        (self.root / "client.py").write_text(
            "from library import Widget\ninstance = Widget()\n", encoding="utf-8"
        )
        refreshed = self.service.refresh_project_index()
        self.assertEqual(refreshed["indexed_files"], 4)
        self.assertIn("outside the workspace", refreshed["storage"])
        status = self.service.project_index_status()
        self.assertEqual(status["indexed_files"], 4)
        self.assertNotIn("cache_path", status)
        found = self.service.search_project_symbols("Widget")
        self.assertTrue(any(row["path"] == "library.py" for row in found["results"]))
        summary = self.service.summarize_project_architecture()
        self.assertEqual(summary["indexed_files"], 4)
        traced = self.service.trace_project_symbol("Widget")
        self.assertIn("client.py", traced["files"])
        related = self.service.related_project_files("library.py")
        self.assertIn("client.py", [row["path"] for row in related["related"]])
        impact = self.service.estimate_change_impact("library.py")
        self.assertIn("client.py", impact["symbol_matches"])
        self.assertEqual(impact["risk"], "heuristic")

    def test_review_tools_are_bounded_read_only_and_redact_secrets(self):
        token = "sk-proj-1234567890abcdefghijklmnop"
        (self.root / "danger.py").write_text(
            "eval(user_input)  # " + token + "\n", encoding="utf-8"
        )
        before = (self.root / "danger.py").read_bytes()
        reviewed = self.service.review_source_file("danger.py")
        self.assertEqual(reviewed["counts"]["high"], 1)
        self.assertIn("[REDACTED]", str(reviewed["findings"]))
        self.assertNotIn(token, str(reviewed))
        workspace = self.service.review_workspace(100)
        self.assertIn("danger.py", workspace["reviewed_files"])
        self.assertNotIn(token, str(workspace))
        self.assertEqual((self.root / "danger.py").read_bytes(), before)
        with self.assertRaises((ValueError, PermissionError)):
            self.service.review_source_file("../outside.py")

    def test_task_discovery_and_test_selection_never_execute_commands(self):
        (self.root / "requirements-dev.txt").write_text("pytest>=8\n", encoding="utf-8")
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_widget.py").write_text(
            "from widget import render\n\ndef test_render(): assert render()\n", encoding="utf-8"
        )
        (self.root / "widget.py").write_text("def render(): return True\n", encoding="utf-8")
        tasks = self.service.discover_validation_tasks()
        self.assertFalse(tasks["executed"])
        self.assertIn("python-unittest", [row["id"] for row in tasks["tasks"]])
        self.assertIn("python-pytest", [row["id"] for row in tasks["tasks"]])
        selected = self.service.select_relevant_tests(["widget.py"])
        self.assertFalse(selected["executed"])
        self.assertEqual(selected["runner"], "pytest")
        self.assertEqual(selected["commands"][0]["path"], "tests/test_widget.py")
        with self.assertRaises(ValueError):
            self.service.select_relevant_tests(["../outside.py"])
        with self.assertRaises(ValueError):
            self.service.select_relevant_tests(["safe.py"] * 201)

    def test_error_triage_filters_external_paths_and_redacts_source_and_log_tokens(self):
        token = "sk-proj-1234567890abcdefghijklmnop"
        source = self.root / "main.gd"
        source.write_text('extends Node\nconst TOKEN = "' + token + '"\n', encoding="utf-8")
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.gd"
            external.write_text("extends Node\n", encoding="utf-8")
            log = (
                f"{source}:2: Parse error: raw token {token}\n"
                f"{external}:1: External path should be omitted\n"
            )
            result = self.service.analyze_project_error(log)
        self.assertEqual([row["path"] for row in result["diagnostics"]], ["main.gd"])
        self.assertTrue(all(not Path(row["path"]).is_absolute() for row in result["diagnostics"]))
        self.assertNotIn(str(external), str(result))
        self.assertNotIn(token, str(result))
        self.assertIn("[REDACTED]", str(result))
        with self.assertRaises(ValueError):
            self.service.analyze_project_error("x" * 100_001)

    def test_report_paths_preserve_symlink_checks(self):
        source = self.root / "main.gd"
        source.write_text("extends Node\n", encoding="utf-8")
        alias = self.root / "alias.gd"
        try:
            alias.symlink_to(source)
        except OSError:
            self.skipTest("Symlinks are unavailable")
        self.assertIsNone(self.service._report_path(str(alias)))
        self.assertIsNone(self.service._report_path("../main.gd"))
        self.assertEqual(self.service._report_path(str(source)), "main.gd")

    def test_registers_core_and_project_intelligence_mcp_tools(self):
        import sys
        import types

        class FakeFastMCP:
            def __init__(self, name, instructions=""):
                self.name = name
                self.instructions = instructions
                self.tools = {}

            def tool(self):
                def register(function):
                    self.tools[function.__name__] = function
                    return function
                return register

        mcp_module = types.ModuleType("mcp")
        mcp_module.__path__ = []
        server_module = types.ModuleType("mcp.server")
        server_module.__path__ = []
        fastmcp_module = types.ModuleType("mcp.server.fastmcp")
        fastmcp_module.FastMCP = FakeFastMCP
        with patch.dict(sys.modules, {
            "mcp": mcp_module,
            "mcp.server": server_module,
            "mcp.server.fastmcp": fastmcp_module,
        }):
            server = build_server(self.service)
        expected = {
            "list_project_files", "read_project_file", "search_project_text",
            "inspect_gdsc", "decompile_preview", "compile_check",
            "refresh_project_index", "project_index_status", "search_project_symbols",
            "summarize_project_architecture", "trace_project_symbol", "related_project_files",
            "estimate_change_impact", "review_source_file", "review_workspace",
            "analyze_project_error", "discover_validation_tasks", "select_relevant_tests",
        }
        self.assertEqual(set(server.tools), expected)
        self.assertIn("never edits workspace files", server.instructions)


if __name__ == "__main__":
    unittest.main()
