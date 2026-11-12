import importlib.util
import pathlib
import sys
import tempfile
import unittest

BACKEND = pathlib.Path(__file__).parents[1] / "app/src/main/assets/OpenGDS.py"
spec = importlib.util.spec_from_file_location("opengds_backend_test", BACKEND)
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)


class NativeDebuggerTests(unittest.TestCase):
    def make_gdc(self, source):
        return backend.compile_gd(source, compress=True)

    def test_valid_script_and_breakpoint_mapping(self):
        source = (
            "extends RefCounted\n"
            "func calculate(values: Array[int]) -> int:\n"
            "    if values.size() > 0:\n"
            "        return values[0]\n"
            "    return 0\n"
        )
        data = self.make_gdc(source)
        decoded = backend.decode_gdsc(data)
        self.assertEqual([], [x for x in backend.validate_gdc_structure(decoded) if x[0] == "ERROR"])
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "valid.gdc"
            path.write_bytes(data)
            report = backend.dbg_report(path, decoded, breakpoints=[3], show_tokens=True, max_tokens=100)
        self.assertIn("STRUCTURE: PASS", report)
        self.assertIn("BREAKPOINT line 3: RESOLVED", report)
        self.assertIn("DEBUGGER SCOPE: Static GDSC analysis", report)

    def test_unclosed_delimiter_is_detected(self):
        data = self.make_gdc("func broken():\n    return (1\n")
        decoded = backend.decode_gdsc(data)
        findings = backend.validate_gdc_structure(decoded)
        self.assertTrue(any(item[1] == "UNCLOSED_DELIMITER" for item in findings))

    def test_unexpected_closer_is_detected(self):
        data = self.make_gdc("func broken():\n    return 1)\n")
        decoded = backend.decode_gdsc(data)
        findings = backend.validate_gdc_structure(decoded)
        self.assertTrue(any(item[1] == "UNEXPECTED_CLOSER" for item in findings))

    def test_invalid_identifier_reference_is_detected(self):
        data = self.make_gdc("var example_name = 7\n")
        decoded = backend.decode_gdsc(data)
        token = next(item for item in decoded[5] if backend.TOK[item.typ] == "IDENTIFIER")
        token.arg = 999999
        findings = backend.validate_gdc_structure(decoded)
        self.assertTrue(any(item[1] == "IDENTIFIER_REFERENCE" for item in findings))

    def test_compile_file_rejects_unbalanced_output_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            source_path = pathlib.Path(folder) / "broken.gd"
            output_path = pathlib.Path(folder) / "broken.gdc"
            source_path.write_text("func broken():\n    return (1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "structural validation"):
                backend.compile_gd_file(source_path, output_path, force=True)
            self.assertFalse(output_path.exists())

    def test_diff_separates_compression_from_payload(self):
        source = "extends RefCounted\nfunc stable():\n    return 42\n"
        compressed = self.make_gdc(source)
        decoded_size, raw = backend.decode_payload(compressed)[1:]
        # A different valid Zstandard level creates a distinct container with the same payload.
        other = b"GDSC" + __import__("struct").pack("<II", 101, len(raw)) + backend.zstd_compress(raw, level=1)
        with tempfile.TemporaryDirectory() as folder:
            a = pathlib.Path(folder) / "a.gdc"
            b = pathlib.Path(folder) / "b.gdc"
            a.write_bytes(compressed)
            b.write_bytes(other)
            report = backend.diff_report(a, b)
        self.assertIn("CONTAINER BYTE-IDENTICAL: NO", report)
        self.assertIn("DECODED PAYLOAD BYTE-IDENTICAL: YES", report)
        self.assertIn("compression representation only", report)

    def test_cli_help_exposes_dbg(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(BACKEND), "--help"],
            capture_output=True, text=True, check=True
        )
        self.assertIn("dbg", result.stdout)
        self.assertIn("--breakpoint", result.stdout)


if __name__ == "__main__":
    unittest.main()
