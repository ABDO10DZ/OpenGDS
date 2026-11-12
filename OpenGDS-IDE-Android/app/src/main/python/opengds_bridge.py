"""Android adapter for the user's OpenGDS.py backend.

The backend remains the source of truth. This bridge only adds Android-friendly
Zstandard I/O and a small JSON/string API for Kotlin.
"""
from __future__ import annotations

import hashlib
import importlib.util
import importlib.machinery
import json
import os
import struct
import tempfile
import traceback
from pathlib import Path

_backend = None
_backend_path = None
_cancel_flag_file = None


def set_cancel_flag_file(path: str):
    global _cancel_flag_file
    _cancel_flag_file = str(path)


def _check_cancelled():
    if _cancel_flag_file and os.path.exists(_cancel_flag_file):
        raise RuntimeError("Operation cancelled by user")


def _install_android_zstd(module):
    original_decode = module.decode_payload
    original_compress = module.zstd_compress

    def decode_payload(data: bytes):
        if len(data) >= 12 and data[:4] == b"GDSC":
            version = struct.unpack_from("<I", data, 4)[0]
            decoded_size = struct.unpack_from("<I", data, 8)[0]
            payload = data[12:]
            if decoded_size:
                try:
                    import zstandard
                    raw = zstandard.ZstdDecompressor().decompress(
                        payload, max_output_size=decoded_size
                    )
                    if len(raw) != decoded_size:
                        raise ValueError(
                            f"decompressed size mismatch: expected {decoded_size}, got {len(raw)}"
                        )
                    return version, decoded_size, raw
                except ImportError:
                    # Desktop/CLI fallback retained by OpenGDS.py.
                    return original_decode(data)
        return original_decode(data)

    def zstd_compress(data: bytes, level: int = 3):
        try:
            import zstandard
            return zstandard.ZstdCompressor(level=level).compress(data)
        except ImportError:
            return original_compress(data, level)

    module.decode_payload = decode_payload
    module.zstd_compress = zstd_compress


def _load_candidate(path: str):
    candidate = Path(path).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(str(candidate))

    # Hash-based module names prevent Python from reusing stale bytecode after an update.
    import sys
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()[:16]
    module_name = "opengds_backend_" + digest
    # The manual-update flow stages the candidate as OpenGDS.py.manual.new.
    # spec_from_file_location() returns no loader for that suffix on CPython/Chaquopy.
    # Use an explicit source loader so valid Python source can be imported regardless
    # of the temporary staging suffix.
    loader = importlib.machinery.SourceFileLoader(module_name, str(candidate))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise ImportError(f"Unable to create a Python module spec for {candidate.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        loader.exec_module(module)
    except Exception as error:
        sys.modules.pop(module_name, None)
        raise ImportError(
            f"Selected OpenGDS.py failed to import: {type(error).__name__}: {error}"
        ) from error

    required = ("decode_gdsc", "decode_file", "reconstruct", "compile_gd", "info_report")
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        sys.modules.pop(module_name, None)
        raise RuntimeError("Incompatible OpenGDS.py: missing " + ", ".join(missing))

    _install_android_zstd(module)
    module._opengds_cancel_check = _check_cancelled
    return module, candidate


def validate_backend(path: str) -> str:
    """Load a candidate in isolation without changing the active backend."""
    module, candidate = _load_candidate(path)
    return json.dumps({
        "valid": True, "path": str(candidate), "api": "GDSC v101",
        "compiler": callable(module.compile_gd), "decompiler": callable(module.reconstruct),
    })


def configure_backend(path: str) -> str:
    """Load and activate a user-selectable OpenGDS.py file."""
    global _backend, _backend_path
    module, candidate = _load_candidate(path)
    _backend = module
    _backend_path = str(candidate)
    return json.dumps({"loaded": True, "path": _backend_path, "api": "GDSC v101"})


def _core():
    if _backend is None:
        raise RuntimeError("OpenGDS.py backend is not initialized")
    return _backend


def backend_status() -> str:
    return json.dumps({
        "ready": _backend is not None,
        "path": _backend_path,
        "backend": "OpenGDS.py",
        "bytecode": 101,
    })


def info(path: str) -> str:
    _check_cancelled()
    result = _core().info_report(path)
    _check_cancelled()
    return result


def decompile(path: str) -> str:
    _check_cancelled()
    core = _core()
    decoded = core.decode_file(path)
    source = core.reconstruct(decoded[1], decoded[2], decoded[3], decoded[4], decoded[5])
    _check_cancelled()
    return source


def validate_gdc(path: str) -> str:
    _check_cancelled()
    core = _core()
    decoded = core.decode_file(path)
    _check_cancelled()
    return json.dumps({
        "valid": decoded[0] == 101,
        "version": decoded[0],
        "identifiers": len(decoded[1]),
        "constants": len(decoded[2]),
        "tokens": len(decoded[5]),
    })


def compile_source(source: str, destination: str, compressed: bool = True,
                   tab_size: int = 4, force: bool = False) -> str:
    _check_cancelled()
    core = _core()
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        raise FileExistsError(f"Output exists (enable 'Replace existing .gd/.gdc outputs' in Settings): {dest}")

    data = core.compile_gd(source, compress=bool(compressed), tab_size=int(tab_size))
    _check_cancelled()
    decoded = core.decode_gdsc(data)
    if decoded[0] != 101:
        raise ValueError(f"Compiler produced unsupported GDSC version {decoded[0]}")
    if not decoded[5] and source.strip():
        raise ValueError("Compiler produced an empty token stream for non-empty GDScript")
    structural_errors = [item for item in core.validate_gdc_structure(decoded) if item[0] == "ERROR"]
    if structural_errors:
        summary = "; ".join(f"{code}: {message}" for _severity, code, message, _index in structural_errors[:8])
        raise ValueError("Compiled GDSC failed structural validation: " + summary)

    tmp = dest.with_name(dest.name + ".opengds-tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()

    return json.dumps({
        "path": str(dest),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "tokens": len(decoded[5]),
        "version": decoded[0],
        "compressed": bool(compressed),
    })


def report(mode: str, path: str) -> str:
    _check_cancelled()
    core = _core()
    if mode == "info":
        result = core.info_report(path)
        _check_cancelled()
        return result
    decoded = core.decode_file(path)
    _check_cancelled()
    if mode == "audit":
        return core.audit_report(path, decoded)
    if mode == "consts":
        return core.const_report(path, decoded)
    if mode == "disasm":
        return core.disasm_report(path, decoded)
    if mode == "dbg":
        result = core.dbg_report(path, decoded)
        _check_cancelled()
        return result
    if mode == "hexdump":
        return core.hexdump(core.decode_payload(Path(path).read_bytes())[2])
    raise ValueError("Unsupported report mode: " + mode)



def debug(path: str, breakpoint_lines=None, show_tokens: bool = False,
          context: int = 4, max_tokens: int = 200) -> str:
    """Run native static GDSC diagnostics and resolve optional source breakpoints."""
    _check_cancelled()
    core = _core()
    decoded = core.decode_file(path)
    _check_cancelled()
    result = core.dbg_report(
        path, decoded, breakpoints=breakpoint_lines or [],
        show_tokens=bool(show_tokens), context=int(context), max_tokens=int(max_tokens)
    )
    _check_cancelled()
    return result


def safe_call_json(function_name: str, *args) -> str:
    """Small generic diagnostic endpoint; exceptions remain explicit."""
    try:
        fn = getattr(_core(), function_name)
        result = fn(*args)
        return json.dumps({"ok": True, "result": result}, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc), "trace": traceback.format_exc()})


def decompile_all(folder: str, force: bool = False, continue_on_error: bool = True) -> str:
    core = _core()
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    ok, failed, skipped = 0, 0, 0
    messages = []
    for source_file in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".gdc"):
        try:
            _check_cancelled()
            with source_file.open("rb") as stream:
                header = stream.read(12)
            if len(header) < 12 or header[:4] != b"GDSC" or struct.unpack_from("<I", header, 4)[0] != 101:
                skipped += 1
                continue
            target = source_file.with_suffix(".gd")
            if target.exists() and not force:
                failed += 1
                messages.append(f"[SKIP] {source_file}: output exists: {target.name}")
                if not continue_on_error:
                    break
                continue
            if target.exists() and force:
                target.with_name(target.name + ".bak").write_bytes(target.read_bytes())
            decoded = core.decode_file(source_file)
            source = core.reconstruct(decoded[1], decoded[2], decoded[3], decoded[4], decoded[5])
            _check_cancelled()
            tmp = target.with_name(target.name + ".opengds-tmp")
            try:
                tmp.write_text(source, encoding="utf-8")
                os.replace(tmp, target)
            finally:
                if tmp.exists():
                    tmp.unlink()
            ok += 1
            messages.append(f"[OK] {source_file} -> {target}")
        except Exception as exc:
            if "cancelled by user" in str(exc).lower():
                raise
            failed += 1
            messages.append(f"[ERROR] {source_file}: {exc}")
            if not continue_on_error:
                break
    return json.dumps({"ok": ok, "failed": failed, "skipped": skipped, "messages": messages})


def compile_all(folder: str, compressed: bool = True, tab_size: int = 4,
                force: bool = False, continue_on_error: bool = True) -> str:
    core = _core()
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    ok, failed = 0, 0
    messages = []
    for source_file in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".gd"):
        try:
            _check_cancelled()
            target = source_file.with_suffix(".gdc")
            if target.exists() and not force:
                failed += 1
                messages.append(f"[SKIP] {source_file}: output exists: {target.name}")
                if not continue_on_error:
                    break
                continue
            if target.exists() and force:
                target.with_name(target.name + ".bak").write_bytes(target.read_bytes())
            data = core.compile_gd(source_file.read_text(encoding="utf-8-sig"),
                                   compress=bool(compressed), tab_size=int(tab_size))
            _check_cancelled()
            decoded = core.decode_gdsc(data)
            if decoded[0] != 101:
                raise ValueError(f"unsupported output version {decoded[0]}")
            structural_errors = [item for item in core.validate_gdc_structure(decoded) if item[0] == "ERROR"]
            if structural_errors:
                summary = "; ".join(f"{code}: {message}" for _severity, code, message, _index in structural_errors[:8])
                raise ValueError("Compiled GDSC failed structural validation: " + summary)
            tmp = target.with_name(target.name + ".opengds-tmp")
            try:
                tmp.write_bytes(data)
                os.replace(tmp, target)
            finally:
                if tmp.exists():
                    tmp.unlink()
            ok += 1
            messages.append(f"[OK] {source_file} -> {target} tokens={len(decoded[5])} bytes={len(data)}")
        except Exception as exc:
            if "cancelled by user" in str(exc).lower():
                raise
            failed += 1
            messages.append(f"[ERROR] {source_file}: {exc}")
            if not continue_on_error:
                break
    return json.dumps({"ok": ok, "failed": failed, "messages": messages})
