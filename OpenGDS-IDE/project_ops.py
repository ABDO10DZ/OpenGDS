"""Project-wide OpenGDS build, decompile and Godot validation operations."""
from __future__ import annotations

from dataclasses import dataclass, field
import subprocess
from pathlib import Path
from typing import Iterable

EXCLUDED_DIRS = {".git", ".godot", ".opengds", ".venv", "__pycache__"}


@dataclass
class OperationSummary:
    mode: str
    succeeded: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def report(self) -> str:
        lines = [f"{self.mode} summary", f"Succeeded: {len(self.succeeded)}", f"Failed: {len(self.failed)}", f"Skipped: {len(self.skipped)}"]
        lines += [f"[NOTE] {note}" for note in self.notes]
        lines += [f"[OK] {p}" for p in self.succeeded]
        lines += [f"[FAILED] {p}: {message}" for p, message in self.failed]
        lines += [f"[SKIPPED] {p}: {message}" for p, message in self.skipped]
        return "\n".join(lines)


def iter_project_files(root: str | Path, suffix: str, *, include_compiled_output: bool = False) -> list[Path]:
    """Find project files while excluding engine/IDE caches.

    `.opengds/compiled` is intentionally included for GDSC decompilation when
    include_compiled_output=True; temporary debugger/decompiler folders remain
    excluded to avoid processing generated artifacts recursively.
    """
    import os
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    found: set[Path] = set()
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        kept = []
        for directory in dirs:
            if directory in {".git", ".godot", ".venv", "__pycache__"}:
                continue
            if directory == ".opengds":
                if include_compiled_output and (current_path / directory / "compiled").is_dir():
                    kept.append(directory)
                continue
            if current_path.name == ".opengds" and directory != "compiled":
                continue
            kept.append(directory)
        dirs[:] = sorted(kept)
        for name in files:
            candidate = current_path / name
            if candidate.suffix.lower() == suffix.lower():
                if current_path.name == ".opengds" and candidate.parent.name != "compiled":
                    continue
                if any(part in {"debug-cache", "decompiled"} for part in candidate.relative_to(root).parts):
                    continue
                found.add(candidate.resolve())
    return sorted(found)


def compile_project(backend, root: str | Path, output_root: str | Path, *, compressed: bool = True,
                    overwrite: bool = False, tab_size: int = 4, continue_on_error: bool = True) -> OperationSummary:
    root = Path(root).expanduser().resolve()
    output_root = Path(output_root).expanduser().resolve()
    sources = iter_project_files(root, ".gd")
    summary = OperationSummary("OpenGDS project compilation")
    if not sources:
        summary.skipped.append((root, "No .gd source files found"))
        return summary
    for source in sources:
        relative = source.relative_to(root)
        target = output_root / relative.with_suffix(".gdc")
        if target.exists() and not overwrite:
            summary.skipped.append((source, f"Output already exists: {target}"))
            continue
        try:
            backend.compile(source, target, compressed=compressed, overwrite=overwrite, tab_size=tab_size)
            summary.succeeded.append(target)
        except Exception as exc:
            summary.failed.append((source, str(exc)))
            if not continue_on_error:
                break
    return summary


def decompile_project(backend, root: str | Path, output_root: str | Path, *, overwrite: bool = False,
                      continue_on_error: bool = True, compiled_root: str | Path | None = None) -> OperationSummary:
    root = Path(root).expanduser().resolve()
    output_root = Path(output_root).expanduser().resolve()
    sources: dict[Path, Path] = {}
    for binary in iter_project_files(root, ".gdc", include_compiled_output=True):
        try:
            relative = binary.relative_to(root / ".opengds" / "compiled")
        except ValueError:
            relative = binary.relative_to(root)
        sources[binary] = relative
    if compiled_root:
        external_root = Path(compiled_root).expanduser().resolve()
        if external_root.is_dir():
            for binary in iter_project_files(external_root, ".gdc"):
                try:
                    relative = binary.relative_to(external_root)
                except ValueError:
                    continue
                sources.setdefault(binary, relative)
    summary = OperationSummary("OpenGDS project decompilation")
    if not sources:
        summary.skipped.append((root, "No .gdc files found in the project or configured compiled output directory"))
        return summary
    for binary, relative in sorted(sources.items(), key=lambda item: str(item[0]).casefold()):
        target = output_root / relative.with_suffix(".gd")
        if target.exists() and not overwrite:
            summary.skipped.append((binary, f"Output already exists: {target}"))
            continue
        try:
            source = backend.decompile(binary)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".opengds-tmp")
            try:
                temp.write_text(source, encoding="utf-8", newline="\n")
                temp.replace(target)
            finally:
                if temp.exists():
                    temp.unlink()
            summary.succeeded.append(target)
        except Exception as exc:
            summary.failed.append((binary, str(exc)))
            if not continue_on_error:
                break
    return summary


def godot_check_command(godot: str | Path, project_root: str | Path, script: str | Path) -> list[str]:
    root = Path(project_root).expanduser().resolve()
    source = Path(script).expanduser().resolve()
    relative = source.relative_to(root).as_posix()
    return [str(godot), "--headless", "--path", str(root), "--check-only", "--script", "res://" + relative]


def validate_project_with_godot(godot: str | Path, project_root: str | Path, *, timeout: int = 120) -> OperationSummary:
    root = Path(project_root).expanduser().resolve()
    if not (root / "project.godot").is_file():
        raise FileNotFoundError(f"Godot validation requires project.godot: {root}")
    scripts = iter_project_files(root, ".gd")
    summary = OperationSummary("Godot headless GDScript parse validation")
    if not scripts:
        summary.skipped.append((root, "No .gd source files found"))
        return summary
    for source in scripts:
        command = godot_check_command(godot, root, source)
        try:
            result = subprocess.run(command, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                    check=False, shell=False)
            if result.returncode == 0:
                summary.succeeded.append(source)
            else:
                summary.failed.append((source, (result.stdout or f"Godot exited with code {result.returncode}").strip()))
        except subprocess.TimeoutExpired:
            summary.failed.append((source, f"Godot check timed out after {timeout} seconds"))
        except Exception as exc:
            summary.failed.append((source, str(exc)))
    return summary
