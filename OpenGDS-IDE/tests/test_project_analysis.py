import tempfile
import unittest
from pathlib import Path

from project_index import ProjectIndex
from project_analysis import architecture_summary, trace_symbol, change_impact


class ProjectAnalysisTests(unittest.TestCase):
    def test_architecture_trace_and_impact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "core.py").write_text("class Service:\n    def run(self): pass\n", encoding="utf-8")
            (root / "client.py").write_text("from core import Service\nsvc = Service()\n", encoding="utf-8")
            idx = ProjectIndex(root, cache_root=root / "cache")
            idx.refresh()
            arch = architecture_summary(idx)
            self.assertEqual(arch["indexed_files"], 2)
            self.assertGreaterEqual(arch["declaration_count"], 2)
            trace = trace_symbol(idx, "Service")
            self.assertIn("core.py", trace["files"])
            impact = change_impact(idx, "core.py")
            self.assertIn("client.py", impact["symbol_matches"])
            self.assertEqual(impact["risk"], "heuristic")

    def test_ai_tools_exposed_and_callable(self):
        from ai_agent import AgentConfig, AgentEngine
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "lib.py").write_text("def helper(): pass\n", encoding="utf-8")
            (root / "app.py").write_text("from lib import helper\nhelper()\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig(scope="all", agent_mode="ask"))
            names = [t["function"]["name"] for t in engine.available_tools()]
            for name in ("project_architecture_summary", "project_trace_symbol", "project_change_impact"):
                self.assertIn(name, names)
            engine._execute_tool("project_index_refresh", {})
            summary = engine._execute_tool("project_architecture_summary", {})
            self.assertEqual(summary["indexed_files"], 2)
            trace = engine._execute_tool("project_trace_symbol", {"query": "helper"})
            self.assertIn("lib.py", trace["files"])
            impact = engine._execute_tool("project_change_impact", {"path": "lib.py"})
            self.assertIn("app.py", impact["symbol_matches"])


if __name__ == "__main__":
    unittest.main()
