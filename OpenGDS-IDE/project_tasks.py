"""Conservative, non-executing project task discovery for OpenGDS-IDE.

Only known project manifests are inspected. Returned commands are suggestions;
the agent must queue them through its existing approval workflow before execution.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def discover_project_tasks(workspace: str | Path, *, safe_path=None) -> list[dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    def exists(relative: str) -> bool:
        path = safe_path(relative) if safe_path else (root / relative)
        return path.is_file()

    tasks: list[dict[str, Any]] = []

    python_markers = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
    has_python_tests = any(exists(name) for name in python_markers)
    tests_dir = root / "tests"
    if safe_path:
        try:
            tests_dir = safe_path("tests")
        except (OSError, ValueError, PermissionError):
            tests_dir = root / ".blocked-tests"
    tests_dir_available = tests_dir.is_dir() and not tests_dir.is_symlink()
    scanned_test_entries = 0
    if tests_dir_available and not has_python_tests:
        for current, dirs, files in os.walk(tests_dir, followlinks=False):
            base = Path(current)
            dirs[:] = [
                name for name in dirs
                if name.lower() not in {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"}
                and not (base / name).is_symlink()
            ]
            for name in files:
                scanned_test_entries += 1
                if scanned_test_entries > 5000:
                    # Be conservative when the bounded scan is exhausted.
                    has_python_tests = True
                    break
                if name.startswith("test_") and name.endswith(".py"):
                    candidate = (base / name)
                    if candidate.is_symlink():
                        continue
                    if safe_path:
                        relative = candidate.relative_to(root).as_posix()
                        try:
                            if not safe_path(relative).is_file():
                                continue
                        except (OSError, ValueError, PermissionError):
                            continue
                    has_python_tests = True
                    break
            if has_python_tests:
                break
    if has_python_tests:
        tasks.append({
            "id": "python-unittest",
            "label": "Python unit tests",
            "command": [sys.executable, "-m", "unittest", "discover", *(["-s", "tests"] if tests_dir_available else []), "-v"],
            "cwd": ".",
            "reason": "Run the project's Python unittest discovery suite",
            "source": "Python test configuration or tests directory",
        })
        pytest_configured = False
        for marker in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "requirements.txt", "requirements-dev.txt"):
            if not exists(marker):
                continue
            try:
                manifest = safe_path(marker) if safe_path else root / marker
                if marker == "pytest.ini" or "pytest" in manifest.read_text(encoding="utf-8-sig").lower():
                    pytest_configured = True
                    break
            except (OSError, UnicodeError):
                continue
        if pytest_configured:
            tasks.append({
                "id": "python-pytest",
                "label": "Python pytest",
                "command": [sys.executable, "-m", "pytest", "-q"],
                "cwd": ".",
                "reason": "Run pytest for this Python project",
                "source": "pytest configuration or pyproject.toml",
            })

    if exists("package.json"):
        manifest = safe_path("package.json") if safe_path else root / "package.json"
        try:
            package = json.loads(manifest.read_text(encoding="utf-8"))
            scripts = package.get("scripts") if isinstance(package, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            scripts = {}
        if isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and scripts["test"].strip():
            tasks.append({
                "id": "node-test",
                "label": "Node.js test script",
                "command": ["npm", "test"],
                "cwd": ".",
                "reason": "Run the package's declared npm test script",
                "source": "package.json scripts.test",
            })

    if exists("Cargo.toml"):
        tasks.append({
            "id": "rust-test",
            "label": "Rust tests",
            "command": ["cargo", "test"],
            "cwd": ".",
            "reason": "Run the Rust project's test suite",
            "source": "Cargo.toml",
        })

    if exists("CMakeLists.txt"):
        tasks.append({
            "id": "cmake-configure",
            "label": "CMake configure",
            "command": ["cmake", "-S", ".", "-B", "build"],
            "cwd": ".",
            "reason": "Configure the CMake project in the build directory",
            "source": "CMakeLists.txt",
        })

    if exists("project.godot"):
        tasks.append({
            "id": "godot-editor-check",
            "label": "Godot headless project check",
            "command": ["godot", "--headless", "--path", ".", "--editor", "--quit"],
            "cwd": ".",
            "reason": "Run a headless Godot editor scan and project import check",
            "source": "project.godot",
        })

    return tasks
