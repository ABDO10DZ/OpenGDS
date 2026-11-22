"""Static error/stack-trace triage helpers. No code execution or file writes."""
from __future__ import annotations
import re
from pathlib import Path

BLOCKED_DIRS = {".git", ".ssh", ".aws", ".azure", ".gnupg", ".secrets", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".godot", ".opengds", ".opengds-ide", ".tox", ".pytest_cache"}
BLOCKED_NAMES = {"secrets.json", "credentials.json", "token.json", "auth.json", ".npmrc", ".netrc", ".git-credentials", "service-account.json"}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".cer", ".crt"}

_ERROR = re.compile(r"(?P<path>(?:res://)?(?:[A-Za-z]:[\\/]|/)?[^:\n]+\.(?:gd|py|js|ts|cs|cpp|c|rs|go|java|kt|gdc)):(?P<line>\d+)(?::(?P<column>\d+))?(?:\s*-\s*|:\s*)(?P<message>.+)", re.I)
_TRACE = re.compile(r"(?:File \"(?P<pyfile>[^\"]+)\", line (?P<pyline>\d+)|(?P<path>(?:res://)?[^:\n]+\.(?:gd|py|cs|cpp|js|ts|java|rs|go|kt)):(?P<line>\d+))", re.I)

def parse_diagnostics(text: str, limit: int = 100) -> list[dict]:
    rows=[]
    for line in str(text or "").splitlines():
        match=_ERROR.search(line.strip())
        if match:
            rows.append({"path":match.group("path"),"line":int(match.group("line")),
                         "column":int(match.group("column")) if match.group("column") else None,
                         "message":match.group("message").strip(),"raw":line[:1000]})
            if len(rows)>=max(1,min(int(limit),100)): break
    return rows

def parse_stack_trace(text: str, limit: int = 50) -> list[dict]:
    frames=[]
    for line in str(text or "").splitlines():
        # Diagnostic lines are not stack frames even when they contain file:line text.
        if _ERROR.search(line.strip()):
            continue
        m=_TRACE.search(line)
        if not m: continue
        path=m.group("pyfile") or m.group("path")
        if path.startswith("res://"):
            path = path[6:]
        number=m.group("pyline") or m.group("line")
        frames.append({"path":path,"line":int(number),"raw":line.strip()[:1000]})
        if len(frames)>=max(1,min(int(limit),50)): break
    return frames

def source_context(workspace: Path, relative: str, line: int, radius: int = 4) -> dict:
    root = Path(workspace).expanduser().resolve()
    path = (root / relative).resolve(strict=False)
    if path != root and root not in path.parents:
        return {"error":"Path outside workspace"}
    parts=[part.lower() for part in Path(relative).parts]
    if any(part in BLOCKED_DIRS or part.startswith(".env") or part in BLOCKED_NAMES or Path(part).suffix.lower() in BLOCKED_SUFFIXES for part in parts):
        return {"error":"Sensitive or excluded source paths are blocked"}
    current=root
    for part in Path(relative).parts:
        current=current/part
        if current.is_symlink(): return {"error":"Symlink paths are blocked"}
    if not path.is_file(): return {"error":"Source file not found"}
    if path.stat().st_size>200_000: return {"error":"Source file exceeds size limit"}
    try: lines=path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError,UnicodeDecodeError): return {"error":"File is not readable UTF-8 text"}
    line=max(1,int(line)); radius=max(0,min(int(radius),8))
    start=max(1,line-radius); end=min(len(lines),line+radius)
    return {"path":relative,"focus_line":line,"excerpt":[{"line":n,"text":lines[n-1][:500],"focus":n==line} for n in range(start,end+1)]}

def triage_error(workspace: Path, error_text: str, limit: int = 20) -> dict:
    root = Path(workspace).expanduser().resolve()
    diagnostics = parse_diagnostics(error_text, limit)
    frames = parse_stack_trace(error_text, limit)
    contexts = []
    for row in diagnostics[:10]:
        relative = row["path"].replace("\\", "/")
        if relative.startswith("res://"):
            relative = relative[6:]
        candidate = Path(relative)
        if candidate.is_absolute():
            try:
                relative = candidate.resolve(strict=False).relative_to(root).as_posix()
            except ValueError:
                continue
        context = source_context(root, relative, row["line"])
        if "excerpt" in context:
            contexts.append({"diagnostic": row, "context": context})
    stack_contexts = []
    for frame in frames[:10]:
        relative = str(frame["path"]).replace("\\", "/")
        candidate = Path(relative)
        if candidate.is_absolute():
            try:
                relative = candidate.resolve(strict=False).relative_to(root).as_posix()
            except ValueError:
                continue
        context = source_context(root, relative, frame["line"])
        if "excerpt" in context:
            stack_contexts.append({"frame": {**frame, "path": relative}, "context": context})
    return {
        "diagnostics": diagnostics,
        "stack_frames": frames,
        "source_contexts": contexts,
        "stack_contexts": stack_contexts,
        "assessment": "Heuristic triage only. Error text and source excerpts are evidence, not a verified root-cause determination.",
    }
