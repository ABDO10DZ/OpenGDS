"""Safe, read-only-first inspectors for common Godot package containers.

The PCK reader follows Godot's public file_access_pack.cpp / pck_packer.cpp
layout. It supports standalone PCK and trailer-embedded PCK data for v2-v4.
Encrypted directory metadata is deliberately not guessed or bypassed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mmap
import os
from pathlib import Path, PurePosixPath
import struct
import zipfile

PCK_MAGIC = b"GDPC"
PACK_DIR_ENCRYPTED = 1 << 0
PACK_REL_FILEBASE = 1 << 1
PACK_SPARSE_BUNDLE = 1 << 2
PACK_FILE_ENCRYPTED = 1 << 0
PACK_FILE_REMOVAL = 1 << 1
PACK_FILE_DELTA = 1 << 2


class ArchiveError(ValueError):
    pass


_EXECUTABLE_SUFFIXES = {".exe", ".bin", ".x86_64", ".linux", ".linuxbsd", ".macos", ".dll", ".so", ".dylib"}
_EXECUTABLE_MAGICS = {
    b"MZ",                  # PE / Windows executables
    b"\x7fELF",             # ELF / Linux and Android native executables
    b"\xfe\xed\xfa\xce",   # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",   # Mach-O 64-bit
    b"\xce\xfa\xed\xfe",   # Mach-O swapped 32-bit
    b"\xcf\xfa\xed\xfe",   # Mach-O swapped 64-bit
    b"\xca\xfe\xba\xbe",   # universal Mach-O
}


def looks_like_pck_or_executable(path: str | Path) -> bool:
    """Fast header/suffix check for PCK containers and likely Godot executables."""
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    if suffix == ".pck" or suffix in _EXECUTABLE_SUFFIXES:
        return True
    try:
        with candidate.open("rb") as stream:
            header = stream.read(8)
    except OSError:
        return False
    return header.startswith(PCK_MAGIC) or any(header.startswith(magic) for magic in _EXECUTABLE_MAGICS)


@dataclass(frozen=True)
class PCKEntry:
    path: str
    offset: int
    size: int
    md5: str
    flags: int

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & PACK_FILE_ENCRYPTED)

    @property
    def removed(self) -> bool:
        return bool(self.flags & PACK_FILE_REMOVAL)

    @property
    def delta(self) -> bool:
        return bool(self.flags & PACK_FILE_DELTA)


@dataclass(frozen=True)
class PCKArchive:
    path: Path
    pack_offset: int
    format_version: int
    engine_version: tuple[int, int, int]
    flags: int
    file_base: int
    entries: tuple[PCKEntry, ...]


def _u32(f) -> int:
    raw = f.read(4)
    if len(raw) != 4:
        raise ArchiveError("Unexpected end of file while reading PCK metadata")
    return struct.unpack("<I", raw)[0]


def _u64(f) -> int:
    raw = f.read(8)
    if len(raw) != 8:
        raise ArchiveError("Unexpected end of file while reading PCK metadata")
    return struct.unpack("<Q", raw)[0]


def _candidate_offsets(path: Path) -> list[int]:
    size = path.stat().st_size
    if size < 4:
        return []
    with path.open("rb") as head:
        found: list[int] = [0] if head.read(4) == PCK_MAGIC else []

    # Godot's embedded-PCK trailer: [... PCK bytes ][uint64 pack size]['GDPC'].
    with path.open("rb") as f:
        if size >= 12:
            f.seek(size - 4)
            if f.read(4) == PCK_MAGIC:
                f.seek(size - 12)
                pack_size_raw = f.read(8)
                if len(pack_size_raw) == 8:
                    pack_size = struct.unpack("<Q", pack_size_raw)[0]
                    candidate = size - 12 - pack_size
                    if 0 <= candidate <= size - 4:
                        found.append(candidate)

    # Godot exports can append/embed PCK data in executable files whose
    # extensions vary by platform (for example .x86_64, .linux, or no suffix).
    # Therefore scan any non-standalone file when the header/trailer did not
    # identify a pack. Every candidate is still structurally validated below.
    if not found:
        try:
            with path.open("rb") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as view:
                    pos = view.find(PCK_MAGIC)
                    while pos >= 0:
                        if pos not in found:
                            found.append(pos)
                        pos = view.find(PCK_MAGIC, pos + 1)
        except (OSError, ValueError):
            pass
    return sorted(set(found))


def read_pck(path: str | Path, *, max_entries: int = 250_000, max_path_bytes: int = 65_536) -> PCKArchive:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    file_size = path.stat().st_size
    parse_errors: list[str] = []
    for start in _candidate_offsets(path):
        try:
            with path.open("rb") as f:
                f.seek(start)
                if f.read(4) != PCK_MAGIC:
                    continue
                version = _u32(f)
                engine = (_u32(f), _u32(f), _u32(f))
                if version not in (2, 3, 4):
                    raise ArchiveError(f"Unsupported PCK format version {version}; supported versions are 2, 3 and 4")
                flags = _u32(f)
                file_base_field = _u64(f)
                file_base = start + file_base_field if (version >= 3 or flags & PACK_REL_FILEBASE) else file_base_field
                if version >= 3:
                    directory_offset = _u64(f)
                    # 16 reserved 32-bit words follow the directory offset.
                    f.seek(f.tell() + 16 * 4)
                    if flags & PACK_DIR_ENCRYPTED:
                        raise ArchiveError("This PCK uses an encrypted directory. OpenGDS can identify it but cannot list/extract it without the project's authorized key.")
                    f.seek(start + directory_offset)
                else:
                    f.seek(f.tell() + 16 * 4)
                    if flags & PACK_DIR_ENCRYPTED:
                        raise ArchiveError("This PCK uses an encrypted directory. OpenGDS can identify it but cannot list/extract it without the project's authorized key.")
                count = _u32(f)
                if count > max_entries:
                    raise ArchiveError(f"PCK directory declares {count:,} entries (limit {max_entries:,})")
                entries: list[PCKEntry] = []
                for index in range(count):
                    name_len = _u32(f)
                    if name_len > max_path_bytes:
                        raise ArchiveError(f"PCK entry {index} path exceeds the {max_path_bytes:,}-byte safety limit")
                    name_raw = f.read(name_len)
                    if len(name_raw) != name_len:
                        raise ArchiveError(f"PCK entry {index} has a truncated path")
                    name = name_raw.rstrip(b"\0").decode("utf-8", errors="strict")
                    rel_offset = _u64(f)
                    size = _u64(f)
                    digest_raw = f.read(16)
                    if len(digest_raw) != 16:
                        raise ArchiveError(f"PCK entry {index} has a truncated MD5")
                    entry_flags = _u32(f)
                    absolute_offset = file_base + rel_offset
                    if not (entry_flags & PACK_FILE_REMOVAL):
                        if absolute_offset < start or absolute_offset + size > file_size:
                            raise ArchiveError(f"PCK entry {name!r} points outside the archive")
                    entries.append(PCKEntry(name, absolute_offset, size, digest_raw.hex(), entry_flags))
                return PCKArchive(path, start, version, engine, flags, file_base, tuple(entries))
        except (ArchiveError, UnicodeDecodeError, OSError, struct.error) as exc:
            parse_errors.append(f"offset {start}: {exc}")
    detail = "\n".join(parse_errors[-5:])
    raise ArchiveError("No supported Godot PCK directory could be parsed." + ("\n" + detail if detail else ""))


def pck_report(archive: PCKArchive) -> str:
    live = [e for e in archive.entries if not e.removed]
    encrypted = sum(e.encrypted for e in live)
    total = sum(e.size for e in live)
    lines = [
        f"FILE: {archive.path}",
        "FORMAT: Godot PCK resource pack",
        f"PACK OFFSET: {archive.pack_offset}",
        f"PACK FORMAT VERSION: {archive.format_version}",
        f"ENGINE VERSION: {'.'.join(map(str, archive.engine_version))}",
        f"PACK FLAGS: 0x{archive.flags:08x}",
        f"FILES: {len(live)}",
        f"TOTAL UNCOMPRESSED FILE SIZE: {total:,} bytes",
        f"ENCRYPTED FILE ENTRIES: {encrypted}",
        "",
        "DIRECTORY:",
    ]
    for entry in archive.entries:
        if entry.removed:
            state = "REMOVAL"
        else:
            state = "ENCRYPTED" if entry.encrypted else "DELTA" if entry.delta else "OK"
        lines.append(f"[{state:9}] {entry.size:>12,}  {entry.path}")
    if encrypted:
        lines += ["", "NOTE: Encrypted file payloads are listed but cannot be extracted by this reader."]
    return "\n".join(lines) + "\n"


def _safe_target(root: Path, entry_name: str) -> Path:
    normalized = entry_name.replace("\\", "/")
    if not normalized or "\x00" in normalized:
        raise ArchiveError(f"Invalid empty or NUL-containing archive path: {entry_name!r}")
    # Godot stores resource paths as res://... in some PCK generations.
    if normalized.startswith("res://"):
        normalized = normalized[6:]
    normalized = normalized.lstrip("/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in ("..", "") for part in pure.parts) or (pure.parts and ":" in pure.parts[0]):
        raise ArchiveError(f"Unsafe PCK path rejected: {entry_name!r}")
    target = (root / Path(*pure.parts)).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise ArchiveError(f"PCK path escapes extraction directory: {entry_name!r}")
    return target


def extract_pck(archive: PCKArchive, destination: str | Path, *, overwrite: bool = False,
                max_file_bytes: int = 2 * 1024**3, max_total_bytes: int = 8 * 1024**3) -> dict:
    root = Path(destination).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    extracted = skipped = errors = 0
    error_details: list[str] = []
    total_written = 0
    with archive.path.open("rb") as f:
        for entry in archive.entries:
            if entry.removed or entry.encrypted or entry.delta:
                skipped += 1
                continue
            try:
                if entry.size > max_file_bytes:
                    raise ArchiveError(f"Entry exceeds per-file extraction limit ({entry.size:,} > {max_file_bytes:,} bytes)")
                if total_written + entry.size > max_total_bytes:
                    raise ArchiveError(f"Extraction would exceed total byte limit ({max_total_bytes:,} bytes)")
                target = _safe_target(root, entry.path)
                if target.exists() and not overwrite:
                    skipped += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                f.seek(entry.offset)
                remaining = entry.size
                digest = hashlib.md5()
                temp = target.with_name(target.name + ".opengds-tmp")
                try:
                    with temp.open("wb") as out:
                        while remaining:
                            block = f.read(min(1024 * 1024, remaining))
                            if not block:
                                raise ArchiveError(f"Truncated payload for {entry.path}")
                            out.write(block)
                            digest.update(block)
                            remaining -= len(block)
                    if digest.hexdigest() != entry.md5:
                        raise ArchiveError(f"MD5 mismatch for {entry.path}; extracted file rejected")
                    os.replace(temp, target)
                    extracted += 1
                    total_written += entry.size
                finally:
                    if temp.exists():
                        temp.unlink()
            except Exception as exc:
                errors += 1
                error_details.append(f"{entry.path}: {exc}")
    return {"extracted": extracted, "skipped": skipped, "errors": errors, "error_details": error_details, "bytes": total_written, "destination": str(root)}


def zip_report(path: str | Path) -> str:
    path = Path(path).expanduser().resolve()
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        lines = [f"FILE: {path}", "FORMAT: ZIP archive (may be a Godot PCK/ZIP export)",
                 f"ENTRIES: {len(infos)}", f"TOTAL UNCOMPRESSED SIZE: {sum(x.file_size for x in infos):,} bytes", "", "DIRECTORY:"]
        lines.extend(f"{'DIR ' if x.is_dir() else 'FILE'} {x.file_size:>12,}  {x.filename}" for x in infos)
        return "\n".join(lines) + "\n"


def extract_zip(path: str | Path, destination: str | Path, *, overwrite: bool = False,
                max_file_bytes: int = 2 * 1024**3, max_total_bytes: int = 8 * 1024**3) -> dict:
    path = Path(path).expanduser().resolve()
    root = Path(destination).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    extracted = skipped = errors = total_written = 0
    error_details: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            try:
                if info.file_size > max_file_bytes:
                    raise ArchiveError(f"Entry exceeds per-file extraction limit ({info.file_size:,} > {max_file_bytes:,} bytes)")
                if total_written + info.file_size > max_total_bytes:
                    raise ArchiveError(f"Extraction would exceed total byte limit ({max_total_bytes:,} bytes)")
                target = _safe_target(root, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if target.exists() and not overwrite:
                    skipped += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(info)
                temp = target.with_name(target.name + ".opengds-tmp")
                try:
                    temp.write_bytes(data)
                    os.replace(temp, target)
                finally:
                    if temp.exists():
                        temp.unlink()
                extracted += 1
                total_written += len(data)
            except Exception as exc:
                errors += 1
                error_details.append(f"{info.filename}: {exc}")
    return {"extracted": extracted, "skipped": skipped, "errors": errors, "error_details": error_details, "bytes": total_written, "destination": str(root)}


def create_project_zip(root: str | Path, output: str | Path, *, include_hidden: bool = True) -> Path:
    """Create a deterministic project ZIP without IDE/cache/git directories."""
    root = Path(root).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    excluded = {".git", ".godot", ".opengds", ".venv", "__pycache__"}
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".opengds-tmp")
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for current, dirs, files in os.walk(root):
                current_path = Path(current)
                dirs[:] = sorted(d for d in dirs if d not in excluded and (include_hidden or not d.startswith(".")))
                for name in sorted(files):
                    source = current_path / name
                    if source == output or source == temp:
                        continue
                    if not include_hidden and name.startswith("."):
                        continue
                    relative = source.relative_to(root).as_posix()
                    zf.write(source, relative)
        os.replace(temp, output)
    finally:
        if temp.exists():
            temp.unlink()
    return output
