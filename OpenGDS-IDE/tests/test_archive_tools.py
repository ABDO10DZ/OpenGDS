import hashlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from archive_tools import ArchiveError, extract_pck, extract_zip, looks_like_pck_or_executable, pck_report, read_pck


def make_pck(path: Path, files: dict[str, bytes], *, prefix: bytes = b"", version: int = 3) -> bytes:
    """Create a minimal Godot PCK v3 fixture containing plain file entries."""
    if version not in (2, 3, 4):
        raise ValueError("fixture supports PCK format versions 2, 3 and 4")
    header_size = 96 if version == 2 else 104
    rows = []
    directory_len = 4
    for name, data in files.items():
        name_bytes = name.encode("utf-8")
        directory_len += 4 + len(name_bytes) + 8 + 8 + 16 + 4
        rows.append((name_bytes, data))
    payload_offset = header_size + directory_len
    directory = bytearray(struct.pack("<I", len(rows)))
    cursor = payload_offset
    payload = bytearray()
    for name_bytes, data in rows:
        directory += struct.pack("<I", len(name_bytes)) + name_bytes
        directory += struct.pack("<QQ", cursor, len(data))
        directory += hashlib.md5(data).digest()
        directory += struct.pack("<I", 0)
        payload += data
        cursor += len(data)
    if version == 2:
        # v2 stores the directory immediately after the fixed reserved header.
        header = b"GDPC" + struct.pack("<IIIIIQ", version, 4, 3, 0, 0, 0) + b"\0" * 64
    else:
        header = b"GDPC" + struct.pack("<IIIIIQQ", version, 4, 3, 0, 0, 0, header_size) + b"\0" * 64
    pck = prefix + header + directory + payload
    if prefix:
        pck += struct.pack("<Q", len(header + directory + payload)) + b"GDPC"
    path.write_bytes(pck)
    return pck


class ArchiveToolTests(unittest.TestCase):
    def test_read_and_extract_standalone_pck(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "game.pck"
            make_pck(source, {"res://scripts/player.gd": b"extends Node\n"})
            archive = read_pck(source)
            self.assertEqual(archive.format_version, 3)
            self.assertIn("res://scripts/player.gd", pck_report(archive))
            result = extract_pck(archive, root / "out")
            self.assertEqual(result["extracted"], 1)
            self.assertEqual((root / "out/scripts/player.gd").read_bytes(), b"extends Node\n")

    def test_read_standalone_pck_v2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "legacy-v2.pck"
            make_pck(source, {"res://legacy.txt": b"v2 payload"}, version=2)
            archive = read_pck(source)
            self.assertEqual(archive.format_version, 2)
            result = extract_pck(archive, root / "out")
            self.assertEqual(result["extracted"], 1)
            self.assertEqual((root / "out/legacy.txt").read_bytes(), b"v2 payload")

    def test_read_standalone_pck_v4(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "modern-v4.pck"
            make_pck(source, {"res://modern.txt": b"v4 payload"}, version=4)
            archive = read_pck(source)
            self.assertEqual(archive.format_version, 4)
            result = extract_pck(archive, root / "out")
            self.assertEqual(result["extracted"], 1)
            self.assertEqual((root / "out/modern.txt").read_bytes(), b"v4 payload")

    def test_read_exe_with_embedded_pck_trailer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "game.exe"
            make_pck(exe, {"res://project.godot": b"config_version=5\n"}, prefix=b"MZ" + b"\0" * 70)
            archive = read_pck(exe)
            self.assertGreater(archive.pack_offset, 0)
            self.assertEqual(archive.entries[0].path, "res://project.godot")

    def test_read_embedded_pck_in_platform_executable_with_unknown_extension(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable = root / "game.x86_64"
            make_pck(executable, {"res://project.godot": b"config_version=5\n"}, prefix=b"ELF" + b"\0" * 80)
            archive = read_pck(executable)
            self.assertGreater(archive.pack_offset, 0)
            self.assertEqual(archive.entries[0].path, "res://project.godot")

    def test_executable_detection_uses_magic_for_unknown_extension(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "game.custom"
            candidate.write_bytes(b"\x7fELF" + b"\0" * 64)
            self.assertTrue(looks_like_pck_or_executable(candidate))
            ordinary = Path(td) / "notes.dat"
            ordinary.write_bytes(b"plain text")
            self.assertFalse(looks_like_pck_or_executable(ordinary))

    def test_pck_path_length_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "oversized-path.pck"
            make_pck(source, {"res://project.godot": b"config_version=5\n"})
            with self.assertRaisesRegex(ArchiveError, "path exceeds"):
                read_pck(source, max_path_bytes=4)

    def test_pck_extraction_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "unsafe.pck"
            make_pck(source, {"../escape.txt": b"bad"})
            result = extract_pck(read_pck(source), root / "out")
            self.assertEqual(result["extracted"], 0)
            self.assertEqual(result["errors"], 1)
            self.assertFalse((root / "escape.txt").exists())

    def test_zip_extraction_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "evil.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("../escape.txt", "bad")
                zf.writestr("ok/file.txt", "good")
            result = extract_zip(source, root / "out")
            self.assertEqual(result["extracted"], 1)
            self.assertEqual(result["errors"], 1)
            self.assertEqual((root / "out/ok/file.txt").read_text(), "good")
            self.assertFalse((root / "escape.txt").exists())

    def test_zip_extraction_respects_size_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "large.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("big.bin", b"123456789")
            result = extract_zip(source, root / "out", max_file_bytes=4)
            self.assertEqual(result["extracted"], 0)
            self.assertEqual(result["errors"], 1)


if __name__ == "__main__":
    unittest.main()
