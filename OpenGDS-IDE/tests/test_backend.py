import tempfile, unittest, os, threading, sys, subprocess
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import OpenGDSBackend, BackendError

class BackendTests(unittest.TestCase):

    def test_standalone_cli_executable_is_invoked_without_python(self):
        with tempfile.TemporaryDirectory() as td:
            cli = Path(td) / "opengds-cli.exe"
            cli.write_text("#!/usr/bin/env python3\nimport sys\nprint('standalone:' + ' '.join(sys.argv[1:]))\n", encoding="utf-8")
            cli.chmod(0o755)
            backend = OpenGDSBackend(cli)
            self.assertFalse(backend.embedded)
            self.assertTrue(backend.standalone_executable)
            self.assertTrue(os.path.samefile(backend.command("info", "sample.gdc")[0], cli))
            # A text file named .exe is not a runnable Windows PE executable.
            # Verify the backend dispatches directly to the selected executable
            # without invoking Python; mock process creation instead of trying to
            # execute an invalid fixture (which raises WinError 216 on Windows).
            from unittest.mock import patch
            with patch("backend.subprocess.run") as run_process:
                run_process.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(
                    command, 0, "standalone:info sample.gdc", ""
                )
                result = backend.run("info", "sample.gdc")
            invoked_command = run_process.call_args.args[0]
            self.assertTrue(os.path.samefile(invoked_command[0], cli))
            self.assertNotIn("python", " ".join(invoked_command).lower())
            self.assertIn("standalone:info sample.gdc", result.stdout)

    def test_frozen_backend_can_use_explicit_standalone_cli(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            cli = Path(td) / "opengds-cli.exe"
            cli.write_text("#!/usr/bin/env python3\nprint('external cli')\n", encoding="utf-8")
            cli.chmod(0o755)
            with patch("backend.is_frozen_app", return_value=True):
                backend = OpenGDSBackend(cli)
            self.assertFalse(backend.embedded)
            self.assertTrue(backend.standalone_executable)
            self.assertTrue(os.path.samefile(backend.command("--help")[0], cli))

    def test_frozen_default_backend_still_uses_embedded_dispatcher(self):
        from unittest.mock import patch
        with patch("backend.is_frozen_app", return_value=True):
            backend = OpenGDSBackend()
        self.assertTrue(backend.embedded)
        self.assertIn("--opengds-cli", backend.command("info", "sample.gdc"))


    def test_frozen_python_core_requires_real_interpreter(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            core = Path(td) / "OpenGDS.py"
            core.write_text("print('core')\n", encoding="utf-8")
            with patch("backend.is_frozen_app", return_value=True), patch("backend.shutil.which", return_value=None):
                with self.assertRaisesRegex(BackendError, "Select opengds-cli.exe"):
                    OpenGDSBackend(core)

    def test_compile_decompile_roundtrip(self):
        root=Path(__file__).resolve().parents[1]
        backend=OpenGDSBackend(root/"OpenGDS.py")
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"sample.gd"; binary=Path(td)/"sample.gdc"
            original='extends Node\n\nfunc _ready():\n    print("OpenGDS-IDE")\n'
            source.write_text(original,encoding="utf-8")
            backend.compile(source,binary,compressed=False,overwrite=True)
            self.assertTrue(binary.is_file()); self.assertTrue(binary.read_bytes().startswith(b"GDSC"))
            recovered=backend.decompile(binary)
            self.assertIn('func _ready()',recovered); self.assertIn('OpenGDS-IDE',recovered)
    def test_run_cancels_long_running_open_gds_subprocess(self):
        root = Path(__file__).resolve().parents[1]
        backend = OpenGDSBackend(root / "OpenGDS.py")
        backend.command = lambda *args: [sys.executable, "-c", "import time; time.sleep(10)"]
        cancellation = threading.Event()
        timer = threading.Timer(0.2, cancellation.set)
        timer.start()
        try:
            with self.assertRaisesRegex(BackendError, "cancelled by user"):
                backend.run("test-cancel", timeout=5, cancel_event=cancellation)
        finally:
            timer.cancel()
            timer.join(timeout=1)

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
