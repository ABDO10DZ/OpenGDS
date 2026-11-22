import tempfile
import unittest
from pathlib import Path

from ai_agent import AgentConfig, AgentEngine
from task_planner import build_task_plan


class TaskPlannerTests(unittest.TestCase):
    def test_builds_ordered_plan_linked_to_detected_tasks(self):
        available = [{"id": "python-unittest"}, {"id": "node-test"}]
        plan = build_task_plan("Fix regression", [
            {"title": "Inspect failing code", "description": "Read relevant files"},
            {"title": "Run tests", "task_id": "python-unittest"},
        ], available)
        self.assertEqual(plan["goal"], "Fix regression")
        self.assertEqual([step["number"] for step in plan["steps"]], [1, 2])
        self.assertEqual(plan["steps"][1]["task_id"], "python-unittest")
        self.assertEqual(plan["status"], "awaiting_user_review")
        self.assertIn("separate explicit user approval", plan["execution_policy"])

    def test_rejects_unknown_task_ids(self):
        with self.assertRaisesRegex(ValueError, "Unknown project task id"):
            build_task_plan("Test", [{"title": "Run", "task_id": "missing"}], [])

    def test_enforces_plan_size_and_text_limits(self):
        with self.assertRaises(ValueError):
            build_task_plan("Test", [], [])
        with self.assertRaises(ValueError):
            build_task_plan("Test", [{"title": "x"}] * 9, [])
        with self.assertRaises(ValueError):
            build_task_plan("Test", [{"title": "x" * 161}], [])

    def test_agent_creates_visible_plan_without_queuing_actions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            result = engine._execute_tool("create_task_plan", {
                "goal": "Validate the project",
                "steps": [
                    {"title": "Inspect source"},
                    {"title": "Run Python tests", "task_id": "python-unittest"},
                ],
            })
            self.assertIn("plan", result)
            self.assertEqual(engine.task_plan["steps"][1]["task_id"], "python-unittest")
            self.assertEqual(engine.pending_actions(), [])
            self.assertIn("create_task_plan", {tool["function"]["name"] for tool in engine.available_tools()})

    def test_plan_tool_is_available_in_ask_mode(self):
        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(agent_mode="ask"))
            self.assertIn("create_task_plan", {tool["function"]["name"] for tool in engine.available_tools()})


if __name__ == "__main__":
    unittest.main()
