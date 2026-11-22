import tempfile
import unittest
from pathlib import Path

from project_index import ProjectIndex


class ProjectIndexTests(unittest.TestCase):
    def test_refresh_search_related_and_incremental(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            cache = Path(td) / "cache"
            root.mkdir()
            (root / "a.py").write_text("class Widget:\n    def render(self):\n        return 1\n", encoding="utf-8")
            (root / "b.py").write_text("from a import Widget\nobj = Widget()\n", encoding="utf-8")
            idx = ProjectIndex(root, cache_root=cache)
            result = idx.refresh()
            self.assertEqual(result["updated"], 2)
            hits = idx.search("Widget")
            self.assertTrue(any(h["path"] == "a.py" and h["kind"] == "class" for h in hits))
            self.assertIn("b.py", [r["path"] for r in idx.related_files("a.py")])
            unchanged = idx.refresh()
            self.assertEqual(unchanged["updated"], 0)
            (root / "a.py").write_text("class Gadget:\n pass\n", encoding="utf-8")
            self.assertEqual(idx.refresh()["updated"], 1)
            self.assertFalse(idx.search("Widget"))
            (root / "b.py").unlink()
            self.assertEqual(idx.refresh()["removed"], 1)

    def test_secrets_and_symlinks_excluded_and_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            cache = Path(td) / "cache"
            root.mkdir()
            (root / "safe.py").write_text("def public_api(): pass\n", encoding="utf-8")
            (root / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
            (root / "credentials.json").write_text('{"secret":"x"}', encoding="utf-8")
            (root / ".secrets").mkdir()
            (root / ".secrets" / "private.py").write_text("def hidden(): pass", encoding="utf-8")
            idx = ProjectIndex(root, cache_root=cache)
            idx.refresh()
            self.assertEqual(idx.status()["indexed_files"], 1)
            idx2 = ProjectIndex(root, cache_root=cache)
            self.assertEqual(idx2.search("public_api")[0]["path"], "safe.py")

    def test_file_size_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "huge.py").write_bytes(b"x" * 200001)
            idx = ProjectIndex(root, cache_root=root / "cache")
            self.assertEqual(idx.refresh()["indexed_files"], 0)


if __name__ == "__main__":
    unittest.main()
