"""Versioned OpenGDS IDE workspace descriptors and recent-project history.

A .ogds file is an IDE/workspace descriptor. It can accompany a Godot project
(project.godot) but does not replace the engine's required project.godot file.
Opening a plain directory is also supported and does not require either file.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from datetime import datetime, timezone

PROJECT_FORMAT = "opengds-project"
PROJECT_VERSION = 2

DEFAULT_PROJECT = {
    "format": PROJECT_FORMAT,
    "version": PROJECT_VERSION,
    "name": "",
    "root": ".",
    "godot_project": "project.godot",
    "backend": "",
    "godot_executable": "",
    "compile": {
        "compressed": True,
        "tab_size": 4,
        "overwrite": False,
        "continue_on_error": True,
        "output_directory": ".opengds/compiled",
        "validate_with_godot": True,
    },
    "debug": {
        "headless": False,
        "interrupt": False,
        "include_frame_callbacks": False,
        "scene": "",
        "source_path": "",
        "extra_args": [],
        "dry_run": False,
        "context": 4,
        "max_tokens": 200,
        "show_tokens": False,
    },
    "editor": {
        "tab_width": 4,
        "encoding": "utf-8",
        "autosave": True,
    },
}


def _deep_merge_defaults(data: dict) -> dict:
    merged = json.loads(json.dumps(DEFAULT_PROJECT))
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def workspace_from_directory(root: str | Path, *, name: str | None = None, descriptor: str = "") -> dict:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)
    data = json.loads(json.dumps(DEFAULT_PROJECT))
    data.update({
        "name": name or root_path.name or "Workspace",
        "root": str(root_path),
        "descriptor": descriptor,
        "godot_project": "project.godot" if (root_path / "project.godot").is_file() else "",
        "backend": "",
    })
    return data


def create_project(root: str | Path, name: str | None = None, descriptor: str | Path | None = None) -> Path:
    root_path = Path(root).expanduser().resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    path = Path(descriptor).expanduser().resolve() if descriptor else root_path / "file.ogds"
    data = json.loads(json.dumps(DEFAULT_PROJECT))
    data.update({
        "name": name or root_path.name,
        "root": "." if path.parent == root_path else str(root_path),
        "godot_project": "project.godot" if (root_path / "project.godot").is_file() else "",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return path


def load_project(path: str | Path) -> dict:
    candidate = Path(path).expanduser().resolve()
    if candidate.is_dir():
        descriptor = candidate / "file.ogds"
        if not descriptor.exists():
            return workspace_from_directory(candidate)
        candidate = descriptor
    if candidate.name.lower() == "project.godot":
        return workspace_from_directory(candidate.parent)
    if candidate.suffix.lower() != ".ogds":
        raise ValueError(f"Not an OpenGDS .ogds descriptor or Godot project.godot file: {candidate}")

    data = json.loads(candidate.read_text(encoding="utf-8-sig"))
    if data.get("format") != PROJECT_FORMAT:
        raise ValueError("Not an OpenGDS IDE project descriptor (expected format='opengds-project')")
    if int(data.get("version", 0)) > PROJECT_VERSION:
        raise ValueError("This project was created by a newer OpenGDS IDE version")

    data = _deep_merge_defaults(data)
    root_value = Path(data.get("root") or ".").expanduser()
    if not root_value.is_absolute():
        root_value = candidate.parent / root_value
    root_path = root_value.resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise FileNotFoundError(f"Workspace root does not exist or is not a folder: {root_path}")
    data["root"] = str(root_path)
    data["descriptor"] = str(candidate)
    data["godot_project"] = data.get("godot_project") or ("project.godot" if (root_path / "project.godot").exists() else "")
    # v1 descriptors stored an absolute backend path. Keep it; new descriptors
    # leave backend blank to use the OpenGDS.py shipped beside the IDE.
    return data


def save_project(data: dict) -> None:
    descriptor = Path(data["descriptor"]).resolve()
    clean = {k: v for k, v in data.items() if k != "descriptor"}
    root = Path(clean.get("root", descriptor.parent)).resolve()
    try:
        clean["root"] = root.relative_to(descriptor.parent).as_posix() or "."
    except ValueError:
        clean["root"] = str(root)
    clean["version"] = PROJECT_VERSION
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    temp = descriptor.with_name(descriptor.name + ".tmp")
    try:
        temp.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, descriptor)
    finally:
        if temp.exists():
            temp.unlink()


class History:
    def __init__(self, path: str | Path, limit: int = 30):
        self.path, self.limit = Path(path), limit
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def entries(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def add(self, path: str | Path) -> None:
        value = str(Path(path).expanduser().resolve())
        rows = [x for x in self.entries() if x.get("path") != value]
        rows.insert(0, {"path": value, "opened": datetime.now(timezone.utc).isoformat()})
        self.path.write_text(json.dumps(rows[:self.limit], indent=2), encoding="utf-8")

    def remove(self, path: str) -> None:
        rows = [x for x in self.entries() if x.get("path") != path]
        self.path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self.path.write_text("[]", encoding="utf-8")
