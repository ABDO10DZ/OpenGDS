"""Read-only lightweight code-review heuristics. No commands or edits."""
from __future__ import annotations
import re
from pathlib import Path

BLOCKED_DIRS = {".git", ".ssh", ".aws", ".azure", ".gnupg", ".secrets", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".godot", ".tox", ".pytest_cache"}
BLOCKED_NAMES = {"secrets.json", "credentials.json", "token.json", "auth.json", ".npmrc", ".netrc", ".git-credentials", "service-account.json"}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".cer", ".crt"}


    ("high","python","eval(","Avoid evaluating untrusted input; use a parser or explicit mapping."),
    ("high","python","exec(","Executing dynamic code expands the attack surface; prefer explicit logic."),
    ("high","python","shell=True","Shell execution can enable command injection; prefer argv arrays."),
    ("medium","python","pickle.loads","Unpickling untrusted data may execute code; use a safe data format."),
    ("medium","python","except Exception:","Broad exception handling can hide failures; narrow the exception types."),
    ("low","any","TODO","Unfinished work marker; verify it is intentional before release."),
    ("low","any","FIXME","Known issue marker; confirm it is tracked and acceptable."),
]
_PATTERN
