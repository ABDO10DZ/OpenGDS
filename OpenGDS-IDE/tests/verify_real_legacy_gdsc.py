from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gdsc_compat as compat


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_real_legacy_gdsc.py path/to/legacy.gdc path/to/gdre_tools")
    source_gdc = Path(sys.argv[1]).resolve()
    gdre = Path(sys.argv[2]).resolve()
    header = compat.inspect_header(source_gdc.read_bytes())
    if header.version != 13:
        raise SystemExit(f"expected Godot 3.5 GDSC revision 13, got {header.version}")
    if not header.profile or header.profile.capability != "gdre":
        raise SystemExit("legacy revision was not routed to the GDRE adapter")

    reconstructed = compat.decompile_legacy_file(
        source_gdc, executable=gdre, bytecode_hint="3.5.0"
    )
    required = ("extends", "func", "add")
    if not all(word in reconstructed for word in required):
        raise SystemExit("GDRE legacy decompiler did not preserve the expected source declarations")

    with tempfile.TemporaryDirectory(prefix="opengds-legacy-ci-") as temp:
        source = Path(temp) / "reconstructed.gd"
        output = Path(temp) / "recompiled"
        source.write_text(reconstructed, encoding="utf-8")
        target = compat.compile_legacy_file(
            source, output / "recompiled.gdc", "3.5.0", executable=gdre
        )
        compiled_header = compat.inspect_header(target.read_bytes())
        if compiled_header.version != 13:
            raise SystemExit(
                f"GDRE legacy compiler emitted revision {compiled_header.version}, expected 13"
            )
        again = compat.decompile_legacy_file(
            target, executable=gdre, bytecode_hint="3.5.0"
        )
        if not all(word in again for word in required):
            raise SystemExit("legacy compile/decompile round-trip lost expected declarations")

    print(f"REAL_LEGACY_VERSION={header.version}")
    print(f"ENGINE_RANGE={header.profile.engine_range}")
    print(f"FILE_BYTES={source_gdc.stat().st_size}")
    print("GDRE_DECOMPILE=PASS")
    print("GDRE_RECOMPILE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
