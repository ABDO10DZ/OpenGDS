"""Conservative, non-executing project task discovery for OpenGDS-IDE.

Only known project manifests are inspected. Returned commands are suggestions;
the agent must queue them through its existing approval workflow before execution.
"""
from __future__ import annotations

import json
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
    has_python_tests = has_python_tests or (
        tests_dir.is_dir() and any(tests_dir.rglob("test_*.py"))
    )
    if has_python_tests:
        tasks.append({
            "id": "python-unittest",
            "label": "Python unit tests",
            "command": ["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
            "cwd": ".",
            "reason": "Run the project's Python unittest discovery suite",
            "source": "Python test configuration or tests directory",
        })
        if exists("pyproject.toml") or exists("pytest.ini"):
            tasks.append({
                "id": "python-pytest",
                "label": "Python pytest",
                "command": ["python", "-m", "pytest", "-q"],
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
        if exists("build/CMakeCache.txt"):
            tasks.append({
                "id": "cmake-build",
                "label": "CMake build",
                "command": ["cmake", "--build", "build"],
                "cwd": ".",
                "reason": "Build the configured CMake project",
                "source": "CMakeLists.txt and build/CMakeCache.txt",
            })
            tasks.append({
                "id": "cmake-test",
                "label": "CTest suite",
                "command": ["ctest", "--test-dir", "build", "--output-on-failure"],
                "cwd": ".",
                "reason": "Run tests registered with CTest",
                "source": "Configured CMake build directory",
            })
        else:
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
