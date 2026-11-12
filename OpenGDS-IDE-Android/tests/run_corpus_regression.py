#!/usr/bin/env python3
"""Compare OpenGDS decompile/recompile results against an extracted GDSC corpus.

Usage:
    python tests/run_corpus_regression.py /path/to/extracted/assets

The corpus is read-only. No Godot executable is launched and no source or GDC
files in the supplied corpus are modified.
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys

BACKEND = pathlib.Path(__file__).parents[1] / "app/src/main/assets/OpenGDS.py"
spec = importlib.util.spec_from_file_location("opengds_corpus_backend", BACKEND)
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=pathlib.Path, help="directory containing original .gdc files")
    args = parser.parse_args()
    root = args.corpus.resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    totals = {"files": 0, "payload_exact": 0, "container_exact": 0, "structural_pass": 0}
    failures: list[str] = []
    container_differences: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".gdc":
            continue
        relative = str(path.relative_to(root))
        totals["files"] += 1
        try:
            original = path.read_bytes()
            decoded = backend.decode_gdsc(original)
            diagnostics = backend.validate_gdc_structure(decoded)
            errors = [item for item in diagnostics if item[0] == "ERROR"]
            if errors:
                failures.append(f"{relative}: original structural diagnostics: {errors[:3]}")
                continue
            totals["structural_pass"] += 1

            source = backend.reconstruct(decoded[1], decoded[2], decoded[3], decoded[4], decoded[5])
            rebuilt = backend.compile_gd(source, compress=True)
            rebuilt_decoded = backend.decode_gdsc(rebuilt)
            rebuilt_errors = [item for item in backend.validate_gdc_structure(rebuilt_decoded) if item[0] == "ERROR"]
            if rebuilt_errors:
                failures.append(f"{relative}: rebuilt structural diagnostics: {rebuilt_errors[:3]}")
                continue

            original_payload = backend.decode_payload(original)[2]
            rebuilt_payload = backend.decode_payload(rebuilt)[2]
            if original_payload == rebuilt_payload:
                totals["payload_exact"] += 1
            else:
                failures.append(f"{relative}: decoded payload differs")
            if original == rebuilt:
                totals["container_exact"] += 1
            else:
                container_differences.append(relative)
        except Exception as exc:
            failures.append(f"{relative}: {type(exc).__name__}: {exc}")

    print("OpenGDS GDSC corpus regression")
    for key, value in totals.items():
        print(f"{key}: {value}/{totals['files']}")
    print(f"container-only differences: {len(container_differences)}")
    for name in container_differences[:30]:
        print(f"  CONTAINER-DIFF {name}")
    print(f"failures: {len(failures)}")
    for failure in failures[:30]:
        print(f"  FAIL {failure}")
    return 1 if failures or totals["payload_exact"] != totals["files"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
