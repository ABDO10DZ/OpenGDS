from __future__ import annotations
import struct
import unittest
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
        ids, constants, lines, count = struct.unpack_from("<4I", raw)
        if ids or constants or lines:
            raise ValueError("token-only fixture expected")
        pos, tokens = 16, []
        for _ in range(count):
            word, line = struct.unpack_from("<II", raw, pos)
            pos += 8
            tokens.append(Token(word & 0x7f, word >> 8, line))
        if pos != len(raw):
            raise ValueError("trailing bytes")
        return 101, [], [], {}, {}, tokens

    @staticmethod
    def read_variant(raw, pos):
        raise AssertionError("no constants in fixture")

def short_token(typ, line):
    return bytes([typ]) + struct.pack("<I", line)

def long_token(typ, arg, line):
    return struct.pack("<II", 0x80 | typ | (arg << 8), line)

def container(version, records, v100=False):
    meta = (struct.pack("<5I", 0, 0, 0, 0, len(records)) if v100
            else struct.pack("<4I", 0, 0, 0, len(records)))
    return b"GDSC" + struct.pack("<II", version, 0) + meta + b"".join(records)

class GDSCCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()

    def test_version_profiles_cover_old_and_current_families(self):
        versions = {p["version"] for p in compat.supported_profiles()}
        self.assertTrue({3, 4, 5, 10, 11, 12, 13, 100, 101}.issubset(versions))

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

    def test_unknown_version_is_rejected_not_guessed(self):
        data = container(999, [short_token(1, 1)])
        self.assertIsNone(compat.inspect_header(data).profile)
        with self.assertRaises(compat.GDSCCompatibilityError):
            compat.decode_compatible(data, self.core)

    def test_legacy_revision_requires_external_adapter(self):
        data = container(13, [short_token(1, 1)])
        with self.assertRaises(compat.ExternalBytecodeToolRequired):
            compat.decode_compatible(data, self.core)

    def test_v101_triple_period_is_not_downconverted(self):
        with self.assertRaises(compat.GDSCCompatibilityError):
            compat._translate_tokens(short_token(83, 1), 0, 1, 101, 100)

    def test_v101_to_v100_round_trip_preserves_tokens_and_lines(self):
        data = container(101, [
            short_token(1, 1), long_token(2, 9, 2),
            short_token(82, 3), short_token(84, 4), short_token(99, 5)
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
