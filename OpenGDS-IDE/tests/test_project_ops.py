import tempfile
import unittest
from pathlib import Path

from project_ops import compile_project, decompile_project, iter_project_files, godot_check_command
from backend import OpenGDSBackend


class ProjectOpsTests(unittest.TestCase):
    def test_compiled_output_inside_opengds_can_be_decompiled(self):
        root_dir = Path(__file__).resolve().parents[1]
        backend = OpenGDSBackend(root_dir / "OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            scripts = project / "scripts"
            scripts.mkdir(parents=True)
            (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            (scripts / "player.gd").write_text("extends Node\nfunc _ready():\n    pass\n", encoding="utf-8")
            compiled_root = project / ".opengds" / "compiled"
            compiled_root.mkdir(parents=True)
            compile_summary = compile_project(backend, project, compiled_root, compressed=False, overwrite=True)
            self.assertEqual(len(compile_summary.succeeded), 1)
            self.assertEqual(len(iter_project_files(project, ".gdc", include_compiled_output=True)), 1)
            decompiled_root = project / ".opengds" / "decompiled"
            decompile_summary = decompile_project(backend, project, decompiled_root, overwrite=True)
            self.assertEqual(len(decompile_summary.succeeded), 1)
            recovered = decompiled_root / "scripts" / "player.gd"
            self.assertTrue(recovered.is_file())
            self.assertIn("func _ready", recovered.read_text(encoding="utf-8"))

    def test_project_decompile_includes_configured_external_output_folder(self):
        root_dir = Path(__file__).resolve().parents[1]
        backend = OpenGDSBackend(root_dir / "OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            project.mkdir()
            external_compiled = Path(td) / "build-output"
            external_compiled.mkdir()
            source = Path(td) / "external.gd"
            source.write_text("extends Node\nfunc run():\n    pass\n", encoding="utf-8")
            binary = external_compiled / "external.gdc"
            backend.compile(source, binary, compressed=False, overwrite=True)
            summary = decompile_project(backend, project, project / ".opengds" / "decompiled",
                overwrite=True, compiled_root=external_compiled)
            self.assertEqual(len(summary.succeeded), 1)
            self.assertTrue((project / ".opengds" / "decompiled" / "external.gd").is_file())

    def test_godot_check_command_uses_project_relative_resource_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "My Project"
            script = root / "Scripts" / "Player Controller.gd"
            script.parent.mkdir(parents=True)
            script.write_text("extends Node\n", encoding="utf-8")
            command = godot_check_command("godot", root, script)
            self.assertEqual(command, ["godot", "--headless", "--path", str(root.resolve()),
                                       "--check-only", "--script", "res://Scripts/Player Controller.gd"])

    def test_internal_debug_cache_not_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".opengds" / "debug-cache").mkdir(parents=True)
            (root / ".opengds" / "debug-cache" / "x.gdc").write_bytes(b"x")
            self.assertEqual(iter_project_files(root, ".gdc", include_compiled_output=True), [])


if __name__ == "__main__":
    unittest.main()
