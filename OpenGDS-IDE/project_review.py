"""Read-only lightweight code-review heuristics. No commands or edits."""
from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

BLOCKED_DIRS = {
    ".git", ".ssh", ".aws", ".azure", ".gnupg", ".secrets",
    "node_modules", "__pycache__", ".venv", "venv", "build", "dist",
    ".godot", ".tox", ".pytest_cache",
}
BLOCKED_NAMES = {
    "secrets.json", "credentials.json", "token.json", "auth.json",
    ".npmrc", ".pypirc", ".netrc", ".git-credentials", "service-account.json",
}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".cer", ".crt"}
MAX_REVIEW_BYTES = 200_000
MAX_FINDINGS = 100

PATTERNS = (
    ("high", re.compile(r"\beval\s*\(", re.I), "Dynamic evaluation"),
    ("high", re.compile(r"\bexec\s*\(", re.I), "Dynamic execution"),
    ("high", re.compile(r"\bsubprocess\.(?:run|Popen|call)\s*\([^\n]*shell\s*=\s*True", re.I), "Shell-enabled subprocess"),
    ("medium", re.compile(r"\bpickle\.(?:load|loads)\s*\(", re.I), "Potential unsafe pickle deserialization"),
    ("medium", re.compile(r"\bexcept\s*:\s*(?:pass|$)", re.I), "Bare exception swallowed"),
    ("low", re.compile(r"\b(?:TODO|FIXME)\b", re.I), "Unfinished-work marker"),
)


def _safe_source_path(workspace: str | Path, relative: str) -> tuple[Path | None, str | None]:
    root = Path(workspace).expanduser().resolve()
    raw = str(relative or "").strip().replace("\\", "/")
    if not raw or "\x00" in raw:
        return None, "A workspace-relative path is required"
    candidate_name = PureWindowsPath(raw)
    rel = Path(raw)
    if rel.is_absolute() or candidate_name.is_absolute() or candidate_name.drive or any(part in {"..", ""} for part in rel.parts):
        return None, "Path must remain inside the workspace"
    parts = [part.lower() for part in rel.parts]
    if any(part in BLOCKED_DIRS or part.startswith(".env") or part in BLOCKED_NAMES
           or Path(part).suffix.lower() in BLOCKED_SUFFIXES for part in parts):
        return None, "Sensitive or excluded paths are blocked"
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return None, "Symlink paths are blocked"
    resolved = current.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        return None, "Path outside workspace"
    return resolved, None


def review_file(workspace: str | Path, relative: str) -> dict:
    path, error = _safe_source_path(workspace, relative)
    if error:
        return {"error": error}
    assert path is not None
    if not path.is_file():
        return {"error": "File not found"}
    try:
        if path.stat().st_size > MAX_REVIEW_BYTES:
            return {"error": "File exceeds review size limit"}
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return {"error": "File is not readable UTF-8 text"}

    findings = []
    for number, line in enumerate(lines, 1):
        for severity, pattern, description in PATTERNS:
            if pattern.search(line):
                findings.append({
                    "severity": severity,
                    "line": number,
                    "rule": description,
                    "snippet": line.strip()[:300],
                })
    counts = {
        level: sum(1 for finding in findings if finding["severity"] == level)
        for level in ("high", "medium", "low")
    }
    return {
        "path": str(relative).replace("\\", "/"),
        "findings": findings[:MAX_FINDINGS],
        "truncated": len(findings) > MAX_FINDINGS,
        "counts": counts,
        "summary": "Static heuristic review only. Findings may be false positives and do not replace tests or human review.",
    }
