import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mcp_server import OpenGDSMCPService


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
        self.service = OpenGDSMCPService(self.root, self.backend)
        (self.root / "main.gd").write_text("extends Node\n", encoding="utf-8")
        (self.root / "main.gdc").write_bytes(b"GDSC")
        (self.root / "README.md").write_text("OpenGDS project\n", encoding="utf-8")

    def tearDown(self):
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

    def test_search_text(self):
        result = self.service.search_text("OpenGDS")
        self.assertEqual(result["matches"][0]["path"], "README.md")


if __name__ == "__main__":
    unittest.main()
