import json
import sys
import tempfile
import unittest
from pathlib import Path

from project_tasks import discover_project_tasks
from ai_agent import AgentConfig, AgentEngine


class ProjectTaskDiscoveryTests(unittest.TestCase):
    def test_detects_python_and_pytest_without_running_commands(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths=['tests']\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_sample.py").write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
            tasks = discover_project_tasks(root)
            by_id = {task["id"]: task for task in tasks}
            self.assertIn("python-unittest", by_id)
            self.assertIn("python-pytest", by_id)
            self.assertEqual(by_id["python-unittest"]["command"],
                             [sys.executable, "-m", "unittest", "discover", "-v"])

    def test_detects_node_test_script_but_never_copies_or_executes_script_body(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({
                "scripts": {"test": "echo SHOULD_NOT_RUN && rm -rf ."}
            }), encoding="utf-8")
            tasks = discover_project_tasks(root)
            node = next(task for task in tasks if task["id"] == "node-test")
            self.assertEqual(node["command"], ["npm", "test"])
            self.assertNotIn("SHOULD_NOT_RUN", json.dumps(node))

    def test_detects_rust_cmake_and_godot_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("Cargo.toml", "CMakeLists.txt", "project.godot"):
                (root / name).write_text("# manifest\n", encoding="utf-8")
            tasks = {task["id"]: task for task in discover_project_tasks(root)}
            self.assertIn("rust-test", tasks)
            self.assertIn("cmake-configure", tasks)
            self.assertIn("godot-editor-check", tasks)
            self.assertEqual(tasks["cmake-configure"]["command"],
                             ["cmake", "-S", ".", "-B", "build"])

    def test_cmake_offers_only_a_safe_configure_step(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "CMakeLists.txt").write_text("project(sample)\n", encoding="utf-8")
            tasks = {task["id"] for task in discover_project_tasks(root)}
            self.assertIn("cmake-configure", tasks)
            self.assertNotIn("cmake-build", tasks)
            self.assertNotIn("cmake-test", tasks)

    def test_agent_exposes_manifest_discovery_without_running_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text('{"scripts":{"test":"echo test"}}', encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            result = engine._execute_tool("detect_project_tasks", {})
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["tasks"][0]["command"], ["npm", "test"])
            self.assertIn("detect_project_tasks", {tool["function"]["name"] for tool in engine.available_tools()})

    def test_detection_tool_is_available_in_ask_mode_and_does_not_execute(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Cargo.toml").write_text("[package]\nname='sample'\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig(agent_mode="ask"))
            result = engine._execute_tool("detect_project_tasks", {})
            self.assertEqual(result["tasks"][0]["command"], ["cargo", "test"])
            self.assertIn("no command was executed", result["message"].lower())


if __name__ == "__main__":
    unittest.main()
