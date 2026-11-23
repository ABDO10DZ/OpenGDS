from __future__ import annotations
import struct
import unittest
import importlib.util
import sys
from pathlib import Path
import gdsc_compat as compat

class Token:
    def __init__(self, typ, arg, line, column=None):
        self.typ, self.arg, self.line, self.column = typ, arg, line, column

class FakeCore:
    @staticmethod
    def decode_gdsc(data):
        if data[:4] != b"GDSC" or struct.unpack_from("<I", data, 4)[0] != 101:
            raise ValueError("not normalized v101")
        if struct.unpack_from("<I", data, 8)[0]:
            raise ValueError("test fixture must be uncompressed")
        raw = data[12:]
        id_count, constant_count, line_count, token_count = struct.unpack_from("<4I", raw)
        pos, identifiers, constants = 16, [], []
        for _ in range(id_count):
            length = struct.unpack_from("<I", raw, pos)[0]
            pos += 4
            identifiers.append(raw[pos:pos + length * 4])
            pos += length * 4
        for _ in range(constant_count):
            value, pos = FakeCore.read_variant(raw, pos)
            constants.append(value)
        line_map, column_map = {}, {}
        for _ in range(line_count):
            key, value = struct.unpack_from("<II", raw, pos)
            pos += 8
            line_map[key] = value
        for _ in range(line_count):
            key, value = struct.unpack_from("<II", raw, pos)
            pos += 8
            column_map[key] = value
        tokens = []
        for _ in range(token_count):
            word, line = struct.unpack_from("<II", raw, pos)
            pos += 8
            tokens.append(Token(word & 0x7f, word >> 8, line))
        if pos != len(raw):
            raise ValueError("trailing bytes")
        return 101, identifiers, constants, line_map, column_map, tokens

    @staticmethod
    def read_variant(raw, pos):
        return struct.unpack_from("<I", raw, pos)[0], pos + 4

def short_token(typ, line):
    return bytes([typ]) + struct.pack("<I", line)

def long_token(typ, arg, line):
    return struct.pack("<II", 0x80 | typ | (arg << 8), line)

def container(version, records, v100=False):
    meta = (struct.pack("<5I", 0, 0, 0, 0, len(records)) if v100
            else struct.pack("<4I", 0, 0, 0, len(records)))
    return b"GDSC" + struct.pack("<II", version, 0) + meta + b"".join(records)

def structured_container(version, records, v100=False):
    identifier = struct.pack("<I", 1) + struct.pack("<I", 0x41424344)
    constant = struct.pack("<I", 0x12345678)
    line_map = struct.pack("<4I", 1, 10, 2, 20)
    column_map = struct.pack("<4I", 1, 4, 2, 8)
    if v100:
        meta = struct.pack("<5I", 1, 1, 2, 0, len(records))
    else:
        meta = struct.pack("<4I", 1, 1, 2, len(records))
    raw = meta + identifier + constant + line_map + column_map + b"".join(records)
    return b"GDSC" + struct.pack("<II", version, 0) + raw

class GDSCCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()

    def test_real_opengds_core_v101_to_v100_round_trip(self):
        core_path = Path(__file__).resolve().parents[1] / "OpenGDS.py"
        sys.path.insert(0, str(core_path.parent))
        spec = importlib.util.spec_from_file_location("_opengds_real_core_desktop_test", core_path)
        self.assertIsNotNone(spec)
        core = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = core
        spec.loader.exec_module(core)
        source = """extends RefCounted
const LIMIT := 42
var total: int = 0
func add(value: int) -> int:
    total += value
    return total
"""
        native = core.compile_gd(source, compress=False, tab_size=4)
        original = core.decode_gdsc(native)
        self.assertEqual(101, original[0])
        encoded = compat.encode_v100(native, core, compressed=False)
        header, decoded = compat.decode_compatible(encoded, core)
        self.assertEqual(100, header.version)
        self.assertEqual(compat._signature(original), compat._signature(decoded))
        errors = [item for item in core.validate_gdc_structure(decoded) if item[0] == "ERROR"]
        self.assertEqual([], errors)
        reconstructed = core.reconstruct(decoded[1], decoded[2], decoded[3], decoded[4], decoded[5])
        rebuilt = core.decode_gdsc(core.compile_gd(reconstructed, compress=False, tab_size=4))
        self.assertEqual(compat._signature(original), compat._signature(rebuilt))

    def test_version_profiles_cover_old_and_current_families(self):
        versions = {p["version"] for p in compat.supported_profiles()}
        self.assertTrue({1, 2, 3, 4, 5, 10, 11, 12, 13, 100, 101}.issubset(versions))

    def test_header_distinguishes_v100_and_v101(self):
        a = compat.inspect_header(container(100, [short_token(1, 1)], True))
        b = compat.inspect_header(container(101, [short_token(1, 1)]))
        self.assertEqual("native-v100", a.profile.capability)
        self.assertEqual("native-v101", b.profile.capability)

    def test_v100_token_ids_shift_after_period_period(self):
        data = container(100, [
            short_token(1, 1), short_token(82, 2), short_token(83, 3),
            short_token(84, 4), short_token(98, 5)
        ], True)
        header, decoded = compat.decode_compatible(data, self.core)
        self.assertEqual(100, header.version)
        self.assertEqual([1, 82, 84, 85, 99], [t.typ for t in decoded[5]])

    def test_mixed_5_and_8_byte_token_records_are_normalized(self):
        data = container(100, [
            short_token(1, 1), long_token(2, 7, 2), short_token(83, 3)
        ], True)
        _header, decoded = compat.decode_compatible(data, self.core)
        self.assertEqual([(1, 0, 1), (2, 7, 2), (84, 0, 3)],
                         [(t.typ, t.arg, t.line) for t in decoded[5]])

    def test_v100_preserves_identifier_constants_and_source_maps(self):
        data = structured_container(100, [
            short_token(83, 1), long_token(4, 12, 2)
        ], v100=True)
        header, decoded = compat.decode_compatible(data, self.core)
        self.assertEqual(100, header.version)
        self.assertEqual([struct.pack("<I", 0x41424344)], decoded[1])
        self.assertEqual([0x12345678], decoded[2])
        self.assertEqual({1: 10, 2: 20}, decoded[3])
        self.assertEqual({1: 4, 2: 8}, decoded[4])
        self.assertEqual([(84, 0, 1), (4, 12, 2)],
                         [(t.typ, t.arg, t.line) for t in decoded[5]])

    def test_unknown_version_is_rejected_not_guessed(self):
        data = container(999, [short_token(1, 1)])
        self.assertIsNone(compat.inspect_header(data).profile)
        with self.assertRaises(compat.GDSCCompatibilityError):
            compat.decode_compatible(data, self.core)

    def test_legacy_revision_requires_external_adapter(self):
        data = container(13, [short_token(1, 1)])
        with self.assertRaises(compat.ExternalBytecodeToolRequired):
            compat.decode_compatible(data, self.core)

    def test_compressed_v100_payload_decodes_and_round_trips(self):
        try:
            import zstandard
        except ImportError:
            self.skipTest("zstandard is not installed")
        data = structured_container(100, [
            short_token(83, 1), long_token(6, 11, 2)
        ], v100=True)
        raw = data[12:]
        compressed = b"GDSC" + struct.pack("<II", 100, len(raw)) + zstandard.ZstdCompressor(level=3).compress(raw)
        header, decoded = compat.decode_compatible(compressed, self.core)
        self.assertEqual(100, header.version)
        self.assertEqual({1: 10, 2: 20}, decoded[3])
        self.assertEqual({1: 4, 2: 8}, decoded[4])
        v101 = structured_container(101, [
            long_token(1, 0, 1), long_token(84, 0, 2), long_token(97, 0, 3)
        ])
        encoded = compat.encode_v100(v101, self.core, compressed=True)
        restored_header, restored = compat.decode_compatible(encoded, self.core)
        self.assertEqual(100, restored_header.version)
        self.assertEqual(compat._signature(self.core.decode_gdsc(v101)),
                         compat._signature(restored))

    def test_v101_triple_period_is_not_downconverted(self):
        with self.assertRaises(compat.GDSCCompatibilityError):
            compat._translate_tokens(short_token(83, 1), 0, 1, 101, 100)

    def test_v101_to_v100_round_trip_preserves_tokens_and_lines(self):
        data = container(101, [
            long_token(1, 0, 1), long_token(2, 9, 2),
            long_token(82, 0, 3), long_token(84, 0, 4), long_token(99, 0, 5)
        ])
        original = self.core.decode_gdsc(data)
        encoded = compat.encode_v100(data, self.core, compressed=False)
        header, restored = compat.decode_compatible(encoded, self.core)
        self.assertEqual(100, header.version)
        self.assertEqual(compat._signature(original), compat._signature(restored))

    def test_truncated_header_is_rejected(self):
        with self.assertRaises(compat.GDSCCompatibilityError):
            compat.inspect_header(b"GDSC\\0\\0")

if __name__ == "__main__":
    unittest.main()
