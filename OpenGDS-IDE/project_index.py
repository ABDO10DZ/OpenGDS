"""Persistent, incremental local symbol index for OpenGDS-IDE.

Stores file metadata and symbol names only (not source contents) in a user cache.
Indexing is bounded, read-only with respect to the project, and excludes secrets.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import sqlite3
import sys
from pathlib import Path

EXCLUDED = {".git", ".godot", ".opengds", ".opengds-ide", ".venv", "venv", "node_modules",
            "__pycache__", "build", "dist", ".pytest_cache", ".ssh", ".aws", ".azure",
            ".gnupg", ".secrets", ".tox"}
SECRET_NAMES = {"credentials.json", "secrets.json", "token.json", "auth.json", ".npmrc",
                ".pypirc", ".netrc", ".git-credentials", "service-account.json"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".cer", ".crt"}
TEXT_SUFFIXES = {".py", ".gd", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".c", ".h",
                 ".cpp", ".hpp", ".cs", ".rs", ".go", ".rb", ".php", ".swift", ".lua",
                 ".sh", ".bat", ".ps1", ".sql", ".json", ".toml", ".yaml", ".yml", ".md"}
MAX_FILE_BYTES = 200_000
MAX_FILES = 5000
MAX_SYMBOLS_PER_FILE = 300


def cache_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "OpenGDS-IDE" / "project-index"


def _safe_relative(rel: Path) -> bool:
    parts = [p.lower() for p in rel.parts]
    return not any(p in EXCLUDED or p.startswith(".env") or p in SECRET_NAMES
                   or Path(p).suffix in SECRET_SUFFIXES for p in parts)


def _symbols(text: str, suffix: str) -> list[tuple[str, str, int]]:
    result: list[tuple[str, str, int]] = []
    if suffix == ".py":
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    result.append((node.name, "class" if isinstance(node, ast.ClassDef) else "function", node.lineno))
                elif isinstance(node, ast.Name):
                    result.append((node.id, "reference", getattr(node, "lineno", 1)))
                elif isinstance(node, ast.Attribute):
                    result.append((node.attr, "reference", getattr(node, "lineno", 1)))
        except SyntaxError:
            pass
    else:
        patterns = [
            (r"^\s*(?:class|class_name)\s+([A-Za-z_][\w]*)", "class"),
            (r"^\s*(?:func|function|def)\s+([A-Za-z_][\w]*)", "function"),
            (r"^\s*(?:signal|enum|const|var)\s+([A-Za-z_][\w]*)", "member"),
            (r"^\s*(?:export\s+)?(?:class|interface|type)\s+([A-Za-z_][\w]*)", "class"),
        ]
        for line_no, line in enumerate(text.splitlines(), 1):
            for pattern, kind in patterns:
                match = re.search(pattern, line)
                if match:
                    result.append((match.group(1), kind, line_no))
                    break
    dedup = {}
    for row in result:
        dedup.setdefault(row, None)
    return list(dedup)[:MAX_SYMBOLS_PER_FILE]


class ProjectIndex:
    def __init__(self, workspace: str | Path, *, cache_root: str | Path | None = None,
                 safe_path=None, scope_allows=None):
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise NotADirectoryError(self.workspace)
        key = hashlib.sha256(str(self.workspace).encode()).hexdigest()[:24]
        self.db_path = Path(cache_root or cache_directory()) / f"{key}.sqlite3"
        self.safe_path = safe_path
        self.scope_allows = scope_allows or (lambda _p: True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _init_db(self):
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER, digest TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS symbols(path TEXT, name TEXT, kind TEXT, line INTEGER)")
            db.execute("CREATE INDEX IF NOT EXISTS symbol_name ON symbols(name)")
            db.execute("CREATE INDEX IF NOT EXISTS symbol_path ON symbols(path)")

    def _walk(self):
        count = 0
        for root, dirs, files in os.walk(self.workspace, followlinks=False):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED and not (root_path / d).is_symlink()]
            for name in files:
                path = root_path / name
                rel = path.relative_to(self.workspace)
                if not _safe_relative(rel) or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if not self.scope_allows(rel.as_posix()):
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                yield rel.as_posix(), path
                count += 1
                if count >= MAX_FILES:
                    return

    def refresh(self) -> dict:
        scanned = updated = removed = 0
        current = {}
        with self._connect() as db:
            for rel, path in self._walk():
                scanned += 1
                try:
                    st = path.stat()
                    current[rel] = (st.st_mtime_ns, st.st_size)
                    prior = db.execute("SELECT mtime_ns,size FROM files WHERE path=?", (rel,)).fetchone()
                    if prior and prior == current[rel]:
                        continue
                    raw = path.read_bytes()
                    if len(raw) > MAX_FILE_BYTES:
                        continue
                    text = raw.decode("utf-8-sig")
                    digest = hashlib.sha256(raw).hexdigest()
                    symbols = _symbols(text, path.suffix.lower())
                    db.execute("DELETE FROM symbols WHERE path=?", (rel,))
                    db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)",
                               (rel, st.st_mtime_ns, st.st_size, digest))
                    db.executemany("INSERT INTO symbols VALUES(?,?,?,?)",
                                   [(rel, *sym) for sym in symbols])
                    updated += 1
                except (OSError, UnicodeError):
                    continue
            known = {row[0] for row in db.execute("SELECT path FROM files")}
            gone = known - set(current)
            for rel in gone:
                db.execute("DELETE FROM symbols WHERE path=?", (rel,))
                db.execute("DELETE FROM files WHERE path=?", (rel,))
            removed = len(gone)
        return {"scanned": scanned, "updated": updated, "removed": removed, "indexed_files": len(current)}

    def status(self) -> dict:
        with self._connect() as db:
            files = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            symbols = db.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        return {"indexed_files": files, "symbols": symbols, "cache_path": str(self.db_path)}

    def search(self, query: str, limit: int = 40) -> list[dict]:
        q = str(query or "").strip()
        if not q:
            raise ValueError("Symbol search query cannot be empty.")
        limit = max(1, min(int(limit), 100))
        with self._connect() as db:
            rows = db.execute(
                "SELECT path,name,kind,line FROM symbols WHERE name LIKE ? ESCAPE '\\' ORDER BY CASE WHEN name=? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END,path,line LIMIT ?",
                (f"%{q.replace('%','\\%').replace('_','\\_')}%", q, f"{q}%", limit)).fetchall()
        return [{"path": p, "symbol": n, "kind": k, "line": ln} for p,n,k,ln in rows]

    def related_files(self, path: str, limit: int = 20) -> list[dict]:
        rel = Path(path).as_posix()
        with self._connect() as db:
            names = [r[0] for r in db.execute("SELECT name FROM symbols WHERE path=? AND kind IN ('class','function','member') LIMIT 80", (rel,))]
            if not names:
                return []
            hits = {}
            for name in names:
                for p,n,k,ln in db.execute("SELECT path,name,kind,line FROM symbols WHERE name=? AND path<>?", (name, rel)):
                    hits[p] = hits.get(p, 0) + 1
        return [{"path": p, "shared_symbols": score} for p,score in sorted(hits.items(), key=lambda x:(-x[1],x[0]))[:max(1,min(int(limit),50))]]
