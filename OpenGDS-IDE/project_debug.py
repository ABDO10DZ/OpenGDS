"""Static error/stack-trace triage helpers. No code execution or file writes."""
from __future__ import annotations
import re
from pathlib import Path

_ERROR = re.compile(r"(?P<path>(?:res://)?(?:[A-Za-z]:[\\/]|/)?[^:\n]+\.(?:gd|py|js|ts|cs|cpp|c|rs|go|java|kt|gdc)):(?P<line>\d+)(?::(?P<column>\d+))?:\s*(?P<message>.+)", re.I)
_TRACE = re.compile(r"(?:File \"(?P<pyfile>[^\"]+)\", line (?P<pyline>\d+)|(?P<path>(?:res://)?[^:\n]+\.(?:gd|cs|cpp|js|ts|java|rs)):(?P<line>\d+))", re.I)

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
        m=_TRACE.search(line)
        if not m: continue
        path=m.group("pyfile") or m.group("path")
        number=m.group("pyline") or m.group("line")
        frames.append({"path":path,"line":int(number),"raw":line.strip()[:1000]})
        if len(frames)>=max(1,min(int(limit),50)): break
    return frames

def source_context(workspace: Path, relative: str, line: int, radius: int = 4) -> dict:
    path=(workspace/relative).resolve(strict=False)
    if path != workspace and workspace not in path.parents:
        return {"error":"Path outside workspace"}
    parts=[part.lower() for part in Path(relative).parts]
    if any(part in BLOCKED_DIRS or part.startswith(".env") or part in BLOCKED_NAMES or Path(part).suffix.lower() in BLOCKED_SUFFIXES for part in parts):
        return {"error":"Sensitive or excluded source paths are blocked"}
    current=workspace
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
    diagnostics=parse_diagnostics(error_text,limit)
    frames=parse_stack_trace(error_text,limit)
    contexts=[]
    for row in diagnostics[:10]:
        rel=row["path"].replace("\\","/")
        if rel.startswith("res://"): rel=rel[6:]
        # Only accept paths that resolve inside workspace; normalize absolute paths to workspace-relative.
        candidate=Path(rel)
        if candidate.is_absolute():
            try: rel=candidate.resolve(strict=False).relative_to(workspace).as_posix()
            except ValueError: continue
        ctx=source_context(workspace,rel,row["line"])
        if "excerpt" in ctx: contexts.append({"diagnostic":row,"context":ctx})
    return {"diagnostics":diagnostics,"stack_frames":frames,"source_contexts":contexts,
            "assessment":"Heuristic triage only. The error text and source excerpts are evidence; root-cause ranking is not a verified diagnosis."}
