import tempfile, unittest
from pathlib import Path
from project_manager import create_project, load_project, save_project, History, workspace_from_directory

class ProjectTests(unittest.TestCase):
    def test_project_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"game"; root.mkdir(); descriptor=create_project(root,"Demo")
            data=load_project(descriptor); self.assertEqual(data["name"],"Demo"); self.assertEqual(Path(data["root"]),root.resolve())
            data["compile"]["tab_size"]=2; save_project(data); self.assertEqual(load_project(descriptor)["compile"]["tab_size"],2)
    def test_plain_directory_is_a_valid_workspace_without_descriptors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "plain-folder"
            root.mkdir()
            data = load_project(root)
            self.assertEqual(Path(data["root"]), root.resolve())
            self.assertFalse(data["godot_project"])
            self.assertFalse(data["descriptor"])

    def test_project_godot_opens_as_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "game"
            root.mkdir()
            (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            data = load_project(root / "project.godot")
            self.assertEqual(Path(data["root"]), root.resolve())
            self.assertEqual(data["godot_project"], "project.godot")

    def test_history_deduplicates_and_removes(self):
        with tempfile.TemporaryDirectory() as td:
            h=History(Path(td)/"history.json"); p=Path(td)/"project"; p.mkdir(); h.add(p); h.add(p)
            self.assertEqual(len(h.entries()),1); h.remove(str(p.resolve())); self.assertEqual(h.entries(),[])
if __name__=="__main__":unittest.main()
