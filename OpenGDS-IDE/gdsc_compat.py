"""GDSC compatibility for the desktop and Android IDEs; never patches OpenGDS.py."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import os, shutil, struct, subprocess, tempfile
from pathlib import Path
from typing import Any

MAGIC = b"GDSC"
MAX_DECODED = 512 * 1024 * 1024
V100_SHIFT_START = 83
V101_TRIPLE_PERIOD = 83

@dataclass(frozen=True)
class BytecodeProfile:
    version: int
    family: str
    engine_range: str
    capability: str
    notes: str = ""

PROFILES = {
    1: BytecodeProfile(1, "Godot 1.x", "pre-1.0 development", "gdre"),
    2: BytecodeProfile(2, "Godot 1.x", "pre-1.0 development", "gdre"),
    3: BytecodeProfile(3, "Godot 1.x", "1.0.0–early 1.1 development", "gdre"),
    4: BytecodeProfile(4, "Godot 1.x", "1.1.0", "gdre"),
    5: BytecodeProfile(5, "Godot 2.x", "2.0 development", "gdre"),
    6: BytecodeProfile(6, "Godot 2.x", "2.0 development", "gdre"),
    7: BytecodeProfile(7, "Godot 2.x", "2.0 development", "gdre"),
    8: BytecodeProfile(8, "Godot 2.x", "2.0 development", "gdre"),
    9: BytecodeProfile(9, "Godot 2.x", "2.0 development", "gdre"),
    10: BytecodeProfile(10, "Godot 2.x / 3.x", "2.0.0–2.1.6 and early 3.0 development", "gdre",
                        "Shared by multiple engine branches; supply the exact engine version to GDRE Tools."),
    11: BytecodeProfile(11, "Godot 3.x", "3.0 development", "gdre"),
    12: BytecodeProfile(12, "Godot 3.x", "3.0.0–3.0.6 and early 3.1 development", "gdre"),
    13: BytecodeProfile(13, "Godot 3.x", "3.1–3.5", "gdre"),
    100: BytecodeProfile(100, "Godot 4.x", "4.3–4.4", "native-v100",
                         "20-byte payload metadata; v100 token ids."),
    101: BytecodeProfile(101, "Godot 4.x", "4.5+", "native-v101",
                         "16-byte payload metadata; v101 token ids."),
}

class GDSCCompatibilityError(ValueError):
    pass

class ExternalBytecodeToolRequired(GDSCCompatibilityError):
    pass

@dataclass(frozen=True)
class GDSCHeader:
    version: int
    decoded_size: int
    stored_size: int
    profile: BytecodeProfile | None
    def to_dict(self):
        return {
            "version": self.version, "decoded_size": self.decoded_size,
            "stored_size": self.stored_size, "known": self.profile is not None,
            "family": self.profile.family if self.profile else "Unknown",
            "engine_range": self.profile.engine_range if self.profile else "Unknown",
            "capability": self.profile.capability if self.profile else "unknown",
            "notes": self.profile.notes if self.profile else "Unknown revision",
        }

def inspect_header(data: bytes) -> GDSCHeader:
    if len(data) < 12 or data[:4] != MAGIC:
        raise GDSCCompatibilityError("Invalid or truncated GDSC header")
    version, decoded_size = struct.unpack_from("<II", data, 4)
    if decoded_size > MAX_DECODED:
        raise GDSCCompatibilityError("Declared GDSC size exceeds the safety limit")
    return GDSCHeader(version, decoded_size, len(data) - 12, PROFILES.get(version))

def supported_profiles():
    return [dict(asdict(p)) for p in PROFILES.values()]

def _payload(data: bytes, core: Any | None = None):
    header = inspect_header(data)
    stored = data[12:]
    if not header.decoded_size:
        return header, stored
    try:
        import zstandard
        raw = zstandard.ZstdDecompressor().decompress(
            stored, max_output_size=header.decoded_size
        )
    except ImportError:
        exe = shutil.which("zstd")
        if not exe:
            raise GDSCCompatibilityError("Compressed GDSC requires zstandard or zstd CLI")
        result = subprocess.run(
            [exe, "-q", "-d", "-c"], input=stored, capture_output=True,
            timeout=120, check=False
        )
        if result.returncode:
            raise GDSCCompatibilityError(result.stderr.decode("utf-8", "replace"))
        raw = result.stdout
    if len(raw) != header.decoded_size:
        raise GDSCCompatibilityError("GDSC decompressed size does not match its header")
    return header, raw

def _compress(raw: bytes, core: Any):
    try:
        import zstandard
        return zstandard.ZstdCompressor(level=3).compress(raw)
    except ImportError:
        fn = getattr(core, "zstd_compress", None)
        if callable(fn):
            return fn(raw, 3)
        exe = shutil.which("zstd")
        if not exe:
            raise GDSCCompatibilityError("Compressed output requires zstandard or zstd CLI")
        result = subprocess.run([exe, "-q", "-3", "-c"], input=raw,
                                capture_output=True, timeout=120, check=False)
        if result.returncode:
            raise GDSCCompatibilityError(result.stderr.decode("utf-8", "replace"))
        return result.stdout

def _u32(raw: bytes, pos: int, what: str):
    if pos < 0 or pos + 4 > len(raw):
        raise GDSCCompatibilityError("Truncated GDSC while reading " + what)
    return struct.unpack_from("<I", raw, pos)[0]

def _layout(raw: bytes, meta: int, core: Any):
    if len(raw) < meta:
        raise GDSCCompatibilityError("Truncated GDSC payload metadata")
    if meta == 20:
        ids, constants, lines, _reserved, tokens = struct.unpack_from("<5I", raw)
    else:
        ids, constants, lines, tokens = struct.unpack_from("<4I", raw)
    if max(ids, constants, lines, tokens) > 20_000_000:
        raise GDSCCompatibilityError("GDSC section count exceeds safety limit")
    pos = meta
    for i in range(ids):
        size = _u32(raw, pos, "identifier length") * 4
        pos += 4
        if size > len(raw) - pos:
            raise GDSCCompatibilityError("Truncated identifier table")
        pos += size
    read_variant = getattr(core, "read_variant", None)
    if constants and not callable(read_variant):
        raise GDSCCompatibilityError("OpenGDS core does not expose Variant decoding")
    for _ in range(constants):
        try:
            _value, next_pos = read_variant(raw, pos)
        except Exception as exc:
            raise GDSCCompatibilityError("Cannot parse constant table: " + str(exc)) from exc
        if not isinstance(next_pos, int) or not pos < next_pos <= len(raw):
            raise GDSCCompatibilityError("Invalid Variant length")
        pos = next_pos
    map_size = lines * 16
    if map_size > len(raw) - pos:
        raise GDSCCompatibilityError("Truncated source-position maps")
    pos += map_size
    return ids, constants, lines, tokens, pos

def _translate_tokens(raw: bytes, offset: int, count: int, source: int, target: int):
    out = bytearray()
    pos = offset
    for index in range(count):
        if pos >= len(raw):
            raise GDSCCompatibilityError("Truncated token stream at index " + str(index))
        extended = bool(raw[pos] & 0x80)
        width = 8 if extended else 5
        if pos + width > len(raw):
            raise GDSCCompatibilityError("Truncated token record " + str(index))
        if extended:
            word = _u32(raw, pos, "token word")
            line = _u32(raw, pos + 4, "token line")
            arg = word >> 8
        else:
            word = raw[pos]
            line = _u32(raw, pos + 1, "token line")
            arg = 0
        typ = word & 0x7F
        if source == 100 and target == 101:
            if typ >= V100_SHIFT_START:
                typ += 1
        elif source == 101 and target == 100:
            if typ == V101_TRIPLE_PERIOD:
                raise GDSCCompatibilityError(
                    "The triple-period token is unavailable in GDSC v100"
                )
            if typ > V101_TRIPLE_PERIOD:
                typ -= 1
        elif source != target:
            raise GDSCCompatibilityError("No token map for these bytecode versions")
        if typ > 0x7F or arg > 0xFFFFFF:
            raise GDSCCompatibilityError("Invalid token value")
        out.extend(struct.pack("<II", 0x80 | typ | (arg << 8), line))
        pos += width
    if pos != len(raw):
        raise GDSCCompatibilityError("Unexpected trailing bytes after token stream")
    return bytes(out)

def normalize_v100(data: bytes, core: Any):
    header, raw = _payload(data, core)
    if header.version != 100:
        raise GDSCCompatibilityError("Expected GDSC v100")
    ids, constants, lines, tokens, token_offset = _layout(raw, 20, core)
    token_data = _translate_tokens(raw, token_offset, tokens, 100, 101)
    payload = struct.pack("<4I", ids, constants, lines, tokens)
    payload += raw[20:token_offset] + token_data
    return MAGIC + struct.pack("<II", 101, 0) + payload

def _signature(decoded):
    _version, ids, constants, lines, columns, tokens = decoded
    return (
        tuple(ids), tuple(repr(v) for v in constants),
        tuple(sorted(lines.items())), tuple(sorted(columns.items())),
        tuple((t.typ, t.arg, t.line, t.column) for t in tokens),
    )

def encode_v100(v101_data: bytes, core: Any, compressed: bool = True):
    original = core.decode_gdsc(v101_data)
    if original[0] != 101:
        raise GDSCCompatibilityError("Native compiler did not produce v101")
    _header, raw = _payload(v101_data, core)
    ids, constants, lines, tokens, token_offset = _layout(raw, 16, core)
    token_data = _translate_tokens(raw, token_offset, tokens, 101, 100)
    payload = struct.pack("<5I", ids, constants, lines, 0, tokens)
    payload += raw[16:token_offset] + token_data
    stored = _compress(payload, core) if compressed else payload
    output = MAGIC + struct.pack("<II", 100, len(payload) if compressed else 0) + stored
    roundtrip = core.decode_gdsc(normalize_v100(output, core))
    if _signature(original) != _signature(roundtrip):
        raise GDSCCompatibilityError("v100 conversion failed round-trip validation")
    return output

def decode_compatible(data: bytes, core: Any):
    header = inspect_header(data)
    if header.version == 101:
        return header, core.decode_gdsc(data)
    if header.version == 100:
        decoded = core.decode_gdsc(normalize_v100(data, core))
        return header, decoded
    if header.profile and header.profile.capability == "gdre":
        raise ExternalBytecodeToolRequired(
            f"GDSC revision {header.version} is recognized ({header.profile.engine_range}); "
            "legacy decoding must use GDRE Tools."
        )
    raise GDSCCompatibilityError(
        f"Unknown GDSC revision {header.version}; no decoder was selected."
    )

def decompile_data(data: bytes, core: Any):
    header, decoded = decode_compatible(data, core)
    text = core.reconstruct(decoded[1], decoded[2], decoded[3], decoded[4], decoded[5])
    return header, text

def compile_data(source: str, core: Any, bytecode_version: int = 101,
                 compressed: bool = True, tab_size: int = 4):
    if bytecode_version not in (100, 101):
        profile = PROFILES.get(bytecode_version)
        label = profile.engine_range if profile else "unknown engine"
        raise ExternalBytecodeToolRequired(
            f"Bytecode revision {bytecode_version} ({label}) requires GDRE Tools "
            "and an explicit engine target."
        )
    data = core.compile_gd(source, compress=bool(compressed), tab_size=int(tab_size))
    return data if bytecode_version == 101 else encode_v100(data, core, compressed)

def find_gdre_tools(path: str | Path | None = None):
    candidates = [str(path)] if path else []
    candidates += [os.environ.get("GDRE_TOOLS", ""), "gdre_tools", "gdre_tools.exe"]
    for item in filter(None, candidates):
        item = str(Path(item).expanduser()) if os.path.sep in item else item
        if Path(item).is_file():
            return str(Path(item).resolve())
        found = shutil.which(item)
        if found:
            return found
    return None

def decompile_legacy_file(path: str | Path, executable=None,
                          bytecode_hint: str | None = None, timeout: int = 180):
    tool = find_gdre_tools(executable)
    if not tool:
        raise ExternalBytecodeToolRequired(
            "Legacy bytecode is recognized. Install GDRE Tools and set GDRE_TOOLS "
            "or add gdre_tools to PATH."
        )
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    with tempfile.TemporaryDirectory(prefix="opengds-gdre-") as temp:
        copy = Path(temp) / source.name
        shutil.copy2(source, copy)
        command = [tool, "--headless", f"--decompile={copy}"]
        if bytecode_hint:
            command.append(f"--bytecode={bytecode_hint}")
        result = subprocess.run(command, cwd=temp, capture_output=True, text=True,
                                timeout=timeout, check=False)
        generated = copy.with_suffix(".gd")
        if result.returncode or not generated.is_file():
            detail = (result.stderr or result.stdout).strip()
            raise GDSCCompatibilityError(
                "GDRE Tools decompilation failed: " + (detail or str(result.returncode))
            )
        return generated.read_text(encoding="utf-8", errors="replace")

def compile_legacy_file(source_path: str | Path, output_path: str | Path,
                        bytecode_hint: str, executable=None, timeout: int = 180):
    tool = find_gdre_tools(executable)
    if not tool:
        raise ExternalBytecodeToolRequired("Legacy compilation requires GDRE Tools")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="opengds-gdre-") as temp:
        copy = Path(temp) / source.name
        shutil.copy2(source, copy)
        out_dir = Path(temp) / "out"
        out_dir.mkdir()
        command = [tool, "--headless", f"--compile={copy}",
                   f"--bytecode={bytecode_hint}", f"--output={out_dir}"]
        result = subprocess.run(command, cwd=temp, capture_output=True, text=True,
                                timeout=timeout, check=False)
        candidates = list(out_dir.rglob("*.gdc"))
        if result.returncode or len(candidates) != 1:
            detail = (result.stderr or result.stdout).strip()
            raise GDSCCompatibilityError(
                "GDRE Tools compile failed: " + (detail or f"{len(candidates)} outputs")
            )
        temp_target = target.with_name(target.name + ".opengds-tmp")
        try:
            shutil.copy2(candidates[0], temp_target)
            os.replace(temp_target, target)
        finally:
            if temp_target.exists():
                temp_target.unlink()
    return target
