import tempfile, unittest, os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import OpenGDSBackend

class BackendTests(unittest.TestCase):
    def test_compile_decompile_roundtrip(self):
        root=Path(__file__).resolve().parents[1]
        backend=OpenGDSBackend(root/"OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"sample.gd"; binary=Path(td)/"sample.gdc"
            original='extends Node\n\nfunc _ready():\n    print("OpenGDS Studio")\n'
            source.write_text(original,encoding="utf-8")
            backend.compile(source,binary,compressed=False,overwrite=True)
            self.assertTrue(binary.is_file()); self.assertTrue(binary.read_bytes().startswith(b"GDSC"))
            recovered=backend.decompile(binary)
            self.assertIn('func _ready()',recovered); self.assertIn('OpenGDS Studio',recovered)
    def test_runtime_debug_dry_run_does_not_launch_engine(self):
        root=Path(__file__).resolve().parents[1]; backend=OpenGDSBackend(root/"OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            project=Path(td)/"game"; project.mkdir(); (project/"project.godot").write_text("config_version=5\n")
            source=project/"player.gd"; source.write_text("extends Node\nfunc _ready():\n    pass\n")
            binary=project/"player.gdc"; backend.compile(source,binary,compressed=False,overwrite=True)
            result=backend.run("dbg",str(binary),"--godot","godot","--project",str(project),"--dry-run","--breakpoint","3")
            self.assertIn("DRY RUN: Godot was not launched",result.stdout)
            self.assertIn("--breakpoints=res://player.gd::3",result.stdout)
    def test_runtime_debug_command_rejects_frame_callbacks_without_interrupt(self):
        root=Path(__file__).resolve().parents[1]
        backend=OpenGDSBackend(root/"OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            project=Path(td)/"game"; project.mkdir()
            binary=project/"player.gdc"; binary.write_bytes(b"GDSC")
            with self.assertRaisesRegex(ValueError, "requires interrupt"):
                backend.runtime_debug_command(binary, "godot", str(project), include_frame_callbacks=True)

    def test_runtime_debug_command_includes_dry_run_flag(self):
        root=Path(__file__).resolve().parents[1]
        backend=OpenGDSBackend(root/"OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            project=Path(td)/"game"; project.mkdir()
            binary=project/"player.gdc"; binary.write_bytes(b"GDSC")
            command=backend.runtime_debug_command(binary,"godot",str(project),dry_run=True)
            self.assertIn("--dry-run",command)

    def test_compiler_errors_are_recorded_with_category_and_traceback(self):
        root=Path(__file__).resolve().parents[1]; backend=OpenGDSBackend(root/"OpenGDS.py")
        previous = os.environ.get("OPENGDS_LOG_DIR")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["OPENGDS_LOG_DIR"] = td
                source=Path(td)/"broken.gd"
                source.write_text('func broken():\n    var value = "unterminated\n', encoding="utf-8")
                with self.assertRaises(Exception):
                    backend.compile(source, source.with_suffix(".gdc"), compressed=False, overwrite=True)
                core_log = (Path(td)/"core.log").read_text(encoding="utf-8")
                self.assertIn("[GDSCRIPT]", core_log)
                self.assertIn("GDScript lexer/compiler failure", core_log)
                self.assertIn("ValueError", core_log)
        finally:
            if previous is None:
                os.environ.pop("OPENGDS_LOG_DIR", None)
            else:
                os.environ["OPENGDS_LOG_DIR"] = previous
    def test_compressed_compile_roundtrip_uses_zstandard_provider(self):
        import ctypes.util
        try:
            import zstandard  # noqa: F401
            available = True
        except ImportError:
            available = bool(ctypes.util.find_library("zstd"))
        if not available:
            self.skipTest("neither Python zstandard nor system libzstd is available")
        root=Path(__file__).resolve().parents[1]
        backend=OpenGDSBackend(root/"OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"compressed.gd"; binary=Path(td)/"compressed.gdc"
            source.write_text('extends Node\nfunc _ready():\n    print("compressed")\n', encoding="utf-8")
            backend.compile(source,binary,compressed=True,overwrite=True)
            self.assertIn("VALIDATION: PASS", backend.inspect("info", binary))
            recovered=backend.decompile(binary)
            self.assertIn('print("compressed")', recovered)

    def test_info_report(self):
        root=Path(__file__).resolve().parents[1]; backend=OpenGDSBackend(root/"OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"a.gd"; out=Path(td)/"a.gdc"; src.write_text('extends Node\nfunc f():\n    pass\n')
            backend.compile(src,out,compressed=False,overwrite=True)
            self.assertIn('VALIDATION: PASS',backend.inspect('info',out))
if __name__=="__main__":unittest.main()
