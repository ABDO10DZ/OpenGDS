from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import gdsc_compat as compat


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_real_gdsc.py path/to/real.gdc")
    gdc_path = Path(sys.argv[1]).resolve()
    if not gdc_path.is_file():
        raise SystemExit(f"fixture not found: {gdc_path}")

    core_path = Path(__file__).resolve().parents[1] / "OpenGDS.py"
    sys.path.insert(0, str(core_path.parent))
    spec = importlib.util.spec_from_file_location("_opengds_real_core_ci", core_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load OpenGDS core: {core_path}")
    core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = core
    spec.loader.exec_module(core)

    data = gdc_path.read_bytes()
    header, decoded = compat.decode_compatible(data, core)
    if header.version != 100:
        raise SystemExit(f"expected real GDSC v100, got v{header.version}")
    errors = [item for item in core.validate_gdc_structure(decoded) if item[0] == "ERROR"]
    if errors:
        raise SystemExit("OpenGDS structural validation failed: " + repr(errors[:10]))

    reconstructed = core.reconstruct(decoded[1], decoded[2], decoded[3], decoded[4], decoded[5])
    rebuilt = core.decode_gdsc(core.compile_gd(reconstructed, compress=False, tab_size=4))
    if compat._signature(decoded) != compat._signature(rebuilt):
        raise SystemExit("real GDSC v100 did not survive decompile/recompile token round-trip")

    print(f"REAL_GDSC_VERSION={header.version}")
    print(f"ENGINE_RANGE={header.profile.engine_range if header.profile else 'unknown'}")
    print(f"FILE_BYTES={len(data)}")
    print(f"TOKENS={len(decoded[5])}")
    print("REAL_CORE_VALIDATION=PASS")
    print("DECOMPILE_RECOMPILE_ROUND_TRIP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
