import struct
import sys
import types
import unittest
from unittest.mock import patch

from OpenGDS import decode_payload, zstd_compress


class PortableZstandardTests(unittest.TestCase):
    def test_compress_uses_python_zstandard_when_available(self):
        compressor = types.SimpleNamespace(compress=lambda data: b"ZSTD" + data)
        fake = types.SimpleNamespace(ZstdCompressor=lambda level=3: compressor)
        with patch.dict(sys.modules, {"zstandard": fake}):
            self.assertEqual(zstd_compress(b"hello"), b"ZSTDhello")

    def test_decompress_uses_python_zstandard_and_checks_decoded_size(self):
        raw = b"decoded-payload"
        decompressor = types.SimpleNamespace(decompress=lambda payload, max_output_size=0: raw)
        fake = types.SimpleNamespace(ZstdDecompressor=lambda: decompressor)
        container = b"GDSC" + struct.pack("<II", 101, len(raw)) + b"compressed-frame"
        with patch.dict(sys.modules, {"zstandard": fake}):
            version, declared, decoded = decode_payload(container)
        self.assertEqual(version, 101)
        self.assertEqual(declared, len(raw))
        self.assertEqual(decoded, raw)

    def test_native_libzstd_round_trip_when_python_wheel_is_absent(self):
        # The Linux CI/container has libzstd; Windows users receive the portable
        # zstandard wheel from requirements.txt instead.
        import ctypes.util
        if not ctypes.util.find_library("zstd"):
            self.skipTest("system libzstd is not installed")
        payload = b"native-zstd-round-trip\0" * 20
        with patch.dict(sys.modules, {"zstandard": None}):
            compressed = zstd_compress(payload)
            container = b"GDSC" + struct.pack("<II", 101, len(payload)) + compressed
            _, _, decoded = decode_payload(container)
        self.assertEqual(decoded, payload)

    def test_decompress_rejects_declared_size_mismatch(self):
        fake = types.SimpleNamespace(ZstdDecompressor=lambda: types.SimpleNamespace(decompress=lambda *a, **k: b"short"))
        container = b"GDSC" + struct.pack("<II", 101, 100) + b"frame"
        with patch.dict(sys.modules, {"zstandard": fake}):
            with self.assertRaisesRegex(ValueError, "decompressed size mismatch"):
                decode_payload(container)


if __name__ == "__main__":
    unittest.main()
