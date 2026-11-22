"""Conservative test selection from changed paths and test references.

This module only inspects workspace metadata and bounded test source text.
It never runs tests or modifies the workspace.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", ".godot", ".opengds", ".opengds-ide", ".venv", "venv",
    "node_modules", "__pycache__", "build", "dist", ".pytest_cache",
    ".ssh", ".aws", ".azure", ".gnupg", ".secrets", ".tox",
}
SECRET_NAMES = {
    ".env", ".npmrc", ".pypirc", ".netrc", ".git-credentials",
    "credentials.json", "secrets.json", "token.json", "auth.json",
    "service-account.json",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".cer", ".crt"}
MAX_TEST_FILES = 1000
MAX_TEST_BYTES = 200_000
MAX_SELECTED = 8

_FULL_SUITE_NAMES = {
    "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "setup.py",
    "requirements.txt", "requirements-dev.txt", "poetry.lock", "uv.lock",
    "pdm.lock", "package.json", "package-lock.json", "pnpm-lock.yaml",
    "yarn.lock", "cargo.toml", "cargo.lock", "cmakelists.txt",
    "project.godot",
}


def _safe_relative(value: str) -> str:
    raw = str(value or "").strip().replace("\\\\", "/")
    if not raw or "\x00" in raw:
        raise ValueError("Changed paths must be non-empty workspace-relative paths.")
    path = Path(raw)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise ValueError("Changed paths must stay inside the workspace.")
    parts = [part.lower() for part in path.parts]
    if any(part in EXCLUDED_DIRS or part.startswith(".env") or part in SECRET_NAMES
           or Path(part).suffix.lower() in SECRET_SUFFIXES for part in parts):
        raise PermissionError("Secret, cache and build paths cannot be analyzed.")
    return path.as_posix()


def _is_test_file(path: Path) -> bool:
    name = path.name.lower()
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py")


def _discover_tests(root: Path) -> list[Path]:
    found = []
    for current, dirs, files in __import__("os").walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRS
                   and not (base / d).is_symlink()]
        for name in files:
            path = base / name
            if path.is_symlink() or not _is_test_file(path):
                continue
            try:
                if path.stat().st_size > MAX_TEST_BYTES:
                    continue
            except OSError:
                continue
            rel = path.relative_to(root)
            parts = [p.lower() for p in rel.parts]
            if any(p.startswith(".env") or p in SECRET_NAMES
                   or Path(p).suffix.lower() in SECRET_SUFFIXES for p in parts):
                continue
            found.append(path)
            if len(found) >= MAX_TEST_FILES:
                return found
    return found


def select_tests(workspace: str | Path, changed_paths: list[str], *, scope_allows=None) -> dict:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    if not isinstance(changed_paths, list):
        raise TypeError("changed_paths must be a list of workspace-relative paths.")
    changed = list(dict.fromkeys(_safe_relative(row) for row in changed_paths))
    if not changed:
        return {
            "changed_paths": [],
            "selected_tests": [],
            "commands": [],
            "full_suite_recommended": False,
            "reason": "No changed workspace paths were found. Make a change or provide changed_paths.",
        }

    scope_allows = scope_allows or (lambda _path: True)
    changed = [path for path in changed if scope_allows(path)]
    if not changed:
        return {
            "changed_paths": [],
            "selected_tests": [],
            "commands": [],
            "full_suite_recommended": False,
            "reason": "No changed paths belong to the current assistant Focus.",
        }

    tests = _discover_tests(root)
    scores: dict[str, dict] = {}
    broad_reasons = []
    for rel in changed:
        path = Path(rel)
        name = path.name.lower()
        if name in _FULL_SUITE_NAMES or name.endswith((".lock", ".lockb")) or name.startswith("requirements"):
            broad_reasons.append(f"{rel} is a project-wide dependency/build/configuration file")
        if ".github/workflows" in rel.lower().replace("\\\\", "/"):
            broad_reasons.append(f"{rel} changes CI workflow behavior")

        stem = path.stem.lower()
        paired_names = {f"test_{stem}.py", f"{stem}_test.py"}
        for test in tests:
            test_rel = test.relative_to(root).as_posix()
            if not scope_allows(test_rel):
                continue
            score = 0
            reasons = []
            if test.name.lower() in paired_names:
                score = max(score, 100)
                reasons.append("filename pairs with changed source")
            if test_rel == rel:
                score = max(score, 120)
                reasons.append("test file itself changed")
            if len(stem) >= 4:
                try:
                    body = test.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError):
                    body = ""
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(stem)}(?![A-Za-z0-9_])", body, re.I):
                    score = max(score, 55)
                    reasons.append("test source references changed module name")
                if path.suffix.lower() == ".py":
                    module_parts = list(path.with_suffix("").parts)
                    module = ".".join(part for part in module_parts if part != "__init__")
                    if module and module in body:
                        score = max(score, 80)
                        reasons.append("test source imports or references changed module path")
            if score:
                row = scores.setdefault(test_rel, {"path": test_rel, "score": score, "reasons": []})
                row["score"] = max(row["score"], score)
                row["reasons"] = sorted(set(row["reasons"] + reasons))

    ordered = sorted(scores.values(), key=lambda row: (-row["score"], row["path"]))
    selected = ordered[:MAX_SELECTED]
    full_suite = bool(broad_reasons or not selected or len(ordered) > MAX_SELECTED)
    reason = "; ".join(dict.fromkeys(broad_reasons))
    if not selected and not reason:
        reason = "No reliable changed-file to test mapping was found"
    elif len(ordered) > MAX_SELECTED:
        reason = (reason + "; " if reason else "") + "more than eight related tests were found"

    commands = []
    for row in selected:
        test_path = Path(row["path"])
        commands.append({
            "task_id": "focused-unittest-" + re.sub(r"[^a-z0-9_-]+", "-", test_path.stem.lower()).strip("-"),
            "label": "Focused unittest: " + row["path"],
            "command": [sys.executable, "-m", "unittest", "discover",
                        "-s", test_path.parent.as_posix(), "-p", test_path.name, "-v"],
            "cwd": ".",
            "path": row["path"],
            "reason": "Run this likely-related test file only. " + "; ".join(row["reasons"]),
            "approval_required": True,
        })

    return {
        "changed_paths": changed,
        "selected_tests": selected,
        "commands": commands,
        "full_suite_recommended": full_suite,
        "full_suite_command": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"] if full_suite else None,
        "full_suite_reason": reason if full_suite else "",
        "discovered_test_count": len(tests),
        "selection_limit": MAX_SELECTED,
        "message": "Selection is heuristic and read-only. Review commands and explicitly approve each command before execution.",
    }
