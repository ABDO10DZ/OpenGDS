"""Conservative, static project architecture and change-impact helpers."""
from __future__ import annotations
from collections import Counter
from pathlib import Path


def architecture_summary(index) -> dict:
    with index._connect() as db:
        files = db.execute("SELECT path FROM files ORDER BY path").fetchall()
        symbols = db.execute("SELECT name,kind,path,line FROM symbols ORDER BY path,line").fetchall()
    extensions = Counter(Path(path).suffix.lower() or "[no extension]" for (path,) in files)
    folders = Counter((Path(path).parts[0] if len(Path(path).parts) > 1 else "[root]") for (path,) in files)
    declarations = [row for row in symbols if row[1] in {"class", "function", "member"}]
    return {
        "indexed_files": len(files),
        "extensions": dict(extensions.most_common(20)),
        "top_level_areas": dict(folders.most_common(20)),
        "declaration_count": len(declarations),
        "declarations": [{"name": n, "kind": k, "path": p, "line": ln} for n,k,p,ln in declarations[:100]],
        "note": "Static inventory only; this is not a runtime dependency graph."
    }


def trace_symbol(index, query: str, limit: int = 100) -> dict:
    hits = index.search(query, limit)
    grouped = {}
    for hit in hits:
        grouped.setdefault(hit["path"], []).append({"symbol": hit["symbol"], "kind": hit["kind"], "line": hit["line"]})
    return {"query": query, "matches": len(hits), "files": grouped,
            "note": "Search is name-based; references may be incomplete for non-Python languages."}


def change_impact(index, relative_path: str, limit: int = 30) -> dict:
    related = index.related_files(relative_path, limit)
    with index._connect() as db:
        declarations = db.execute(
            "SELECT name,kind,line FROM symbols WHERE path=? AND kind IN ('class','function','member') ORDER BY line LIMIT 100",
            (Path(relative_path).as_posix(),)).fetchall()
    names = [row[0] for row in declarations]
    consumers = {}
    for name in names:
        for path, kind, line in db_query(index, name, relative_path):
            consumers.setdefault(path, []).append({"symbol": name, "kind": kind, "line": line})
    return {
        "changed_file": Path(relative_path).as_posix(),
        "declarations": [{"name": n, "kind": k, "line": ln} for n,k,ln in declarations],
        "candidate_related_files": related,
        "symbol_matches": consumers,
        "risk": "heuristic",
        "note": "Candidates are inferred from shared symbol names. Review results before editing; this does not prove a dependency or runtime impact."
    }


def db_query(index, symbol, excluded_path):
    with index._connect() as db:
        return db.execute("SELECT path,kind,line FROM symbols WHERE name=? AND path<>? ORDER BY path,line LIMIT 500",
                          (symbol, excluded_path)).fetchall()
