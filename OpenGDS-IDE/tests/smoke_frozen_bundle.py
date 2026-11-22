"""Smoke-test the frozen OpenGDS-IDE executable and its embedded GDSC core."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "OpenGDS-IDE"


def frozen_executable() -> Path:
    dist = ROOT / "dist"
    if sys.platform == "win32":
        return dist / f"{APP_NAME}.exe"
    if sys.platform == "darwin":
        return dist / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    return dist / APP_NAME / APP_NAME


def run_checked(command: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        raise RuntimeError(
            f"Frozen command timed out after {timeout}s: {command!r}\n{output}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"Frozen command exited {result.returncode}: {command!r}\n{result.stdout}"
        )
    return result


def main() -> int:
    executable = frozen_executable()
    if not executable.is_file():
        raise FileNotFoundError(
            f"Expected frozen application executable is missing: {executable}"
        )

    version = run_checked([str(executable), "--opengds-cli", "--version"])
    print(version.stdout[-2000:])

    with tempfile.TemporaryDirectory(prefix="opengds-frozen-smoke-") as temp:
        work = Path(temp)
        source = work / "frozen_smoke.gd"
        compiled = work / "frozen_smoke.gdc"
        roundtrip = work / "roundtrip.gd"
        marker = "OpenGDS frozen application compiler smoke test"
        source.write_text(
            'extends Node\n\nfunc _ready():\n    print("' + marker + '")\n',
            encoding="utf-8",
            newline="\n",
        )

        compile_result = run_checked([
            str(executable), "--opengds-cli", "comp", str(source),
            "--no-compress", "--force",
        ])
        print(compile_result.stdout[-3000:])
        if not compiled.is_file() or compiled.stat().st_size <= 0:
            raise RuntimeError("Frozen compiler did not produce a non-empty GDSC artifact.")

        info = run_checked([
            str(executable), "--opengds-cli", "info", str(compiled),
        ])
        print(info.stdout[-3000:])

        decompile = run_checked([
            str(executable), "--opengds-cli", "dcmp", str(compiled),
            "--output", str(roundtrip),
        ])
        print(decompile.stdout[-3000:])
        if not roundtrip.is_file():
            raise RuntimeError("Frozen decompiler did not produce reconstructed source.")
        reconstructed = roundtrip.read_text(encoding="utf-8")
        if marker not in reconstructed:
            raise RuntimeError("Frozen compile/decompile round trip lost its source marker.")

    print(
        f"Frozen application smoke test passed: {platform.system()} "
        f"({executable})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FROZEN SMOKE TEST FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
