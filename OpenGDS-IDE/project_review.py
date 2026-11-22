"""Read-only lightweight code-review heuristics. No commands or edits."""
from __future__ import annotations
import re
from pathlib import Path

_RULES=[
    ("high","python","eval(","Avoid evaluating untrusted input; use a parser or explicit mapping."),
    ("high","python","exec(","Executing dynamic code expands the attack surface; prefer explicit logic."),
    ("high","python","shell=True","Shell execution can enable command injection; prefer argv arrays."),
    ("medium","python","pickle.loads","Unpickling untrusted data may execute code; use a safe data format."),
    ("medium","python","except Exception:","Broad exception handling can hide failures; narrow the exception types."),
    ("low","any","TODO","Unfinished work marker; verify it is intentional before release."),
    ("low","any","FIXME","Known issue marker; confirm it is tracked and acceptable."),
]
_PATTERN_RULES=[
    ("high",r"\beval\s*\(","Dynamic evaluation"),
    ("high",r"\bexec\s*\(","Dynamic execution"),
    ("high",r"\bsubprocess\.(?:run|Popen|call)\s*\([^\n]*shell\s*=\s*True","Shell-enabled subprocess"),
    ("medium",r"\bpickle\.(?:load|loads)\s*\(","Potential unsafe pickle deserialization"),
    ("medium",r"\bexcept\s*:\s*(?:pass|$)","Bare exception swallowed"),
    ("low",r"\b(?:TODO|FIXME)\b","Unfinished-work marker"),
]

def review_file(workspace: Path, relative: str) -> dict:
    path=(workspace/relative).resolve(strict=False)
    if path != workspace and workspace not in path.parents: return {"error":"Path outside workspace"}
    current=workspace
    for part in Path(relative).parts:
        current=current/part
        if current.is_symlink(): return {"error":"Symlink paths are blocked"}
    if not path.is_file(): return {"error":"File not found"}
    if path.stat().st_size>200_000: return {"error":"File exceeds review size limit"}
    try: lines=path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError,UnicodeDecodeError): return {"error":"File is not readable UTF-8 text"}
    ext=path.suffix.lower()
    findings=[]
    for no,line in enumerate(lines,1):
        for severity,pattern,description in _PATTERN_RULES:
            if re.search(pattern,line,re.I):
                findings.append({"severity":severity,"line":no,"rule":description,"snippet":line.strip()[:300]})
    counts={level:sum(1 for f in findings if f["severity"]==level) for level in ("high","medium","low")}
    return {"path":relative,"findings":findings[:100],"truncated":len(findings)>100,"counts":counts,
            "summary":"Static heuristic review only. Findings may be false positives and do not replace tests or human review."}

