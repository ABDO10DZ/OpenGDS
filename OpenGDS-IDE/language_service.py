"""Lightweight GDScript symbol extraction and editor-side fallback diagnostics.

Godot's LSP remains the source of semantic completion and parser diagnostics.
This module provides a fast local outline and useful fallback checks offline.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re

@dataclass(frozen=True)
class Symbol:
    kind: str
    name: str
    line: int
    column: int
    detail: str = ""

@dataclass(frozen=True)
class Diagnostic:
    severity: str
    line: int
    column: int
    message: str
    source: str = "OpenGDS - IDE"

_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*class_name\s+([A-Za-z_]\w*)")),
    ("class", re.compile(r"^\s*class\s+([A-Za-z_]\w*)")),
    ("function", re.compile(r"^\s*(?:static\s+)?func\s+([A-Za-z_]\w*)\s*(\([^)]*\))?")),
    ("signal", re.compile(r"^\s*signal\s+([A-Za-z_]\w*)")),
    ("enum", re.compile(r"^\s*enum\s+([A-Za-z_]\w*)")),
    ("constant", re.compile(r"^\s*const\s+([A-Za-z_]\w*)")),
    ("variable", re.compile(r"^\s*(?:@onready\s+)?(?:static\s+)?var\s+([A-Za-z_]\w*)")),
]


def extract_symbols(source: str) -> list[Symbol]:
    found: list[Symbol] = []
    for line_no, line in enumerate(source.splitlines(), 1):
        for kind, pattern in _SYMBOL_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            name = match.group(1)
            signature = match.group(2) or "" if kind == "function" else ""
            detail = f"{name}{signature}" if kind == "function" else name
            found.append(Symbol(kind, name, line_no, match.start(1), detail))
            break
    return found


def analyze_gdscript(source: str) -> list[Diagnostic]:
    """Run conservative lexical/style checks; not a replacement for Godot parsing."""
    diagnostics: list[Diagnostic] = []
    lines = source.splitlines()
    for number, line in enumerate(lines, 1):
        if line.rstrip(" \t") != line:
            diagnostics.append(Diagnostic("Warning", number, len(line.rstrip(" \t")), "Trailing whitespace"))
        indent = line[:len(line) - len(line.lstrip(" \t"))]
        if " " in indent and "\t" in indent:
            diagnostics.append(Diagnostic("Warning", number, 0, "Mixed tabs and spaces in indentation"))
        stripped = line.strip()
        code = stripped.split("#", 1)[0].rstrip()
        if code.startswith(("func ", "static func ")) and not code.endswith(":"):
            diagnostics.append(Diagnostic("Warning", number, len(line), "Function declaration may be missing a trailing ':'"))
        elif code.startswith(("if ", "elif ", "for ", "while ", "match ")) and not code.endswith(":"):
            diagnostics.append(Diagnostic("Warning", number, len(line), "Control-flow statement may be missing a trailing ':'"))
        elif code == "else" or code == "else ":
            diagnostics.append(Diagnostic("Warning", number, len(line), "'else' statement may be missing a trailing ':'"))

    # Check bracket balance while ignoring comments and quoted strings.
    stack: list[tuple[str, int, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    triple = False
    escaped = False
    line_no = 1
    col = 0
    i = 0
    while i < len(source):
        ch = source[i]
        col += 1
        if ch == "\n":
            line_no += 1
            col = 0
            if quote and not triple and not escaped:
                diagnostics.append(Diagnostic("Warning", line_no - 1, col, "String literal continues onto another line"))
                quote = None
            escaped = False
            i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif triple and source.startswith(quote * 3, i):
                quote = None
                triple = False
                i += 2
                col += 2
            elif not triple and ch == quote:
                quote = None
            i += 1
            continue
        if ch == "#":
            end = source.find("\n", i)
            if end < 0:
                break
            i = end
            continue
        if ch in ('"', "'"):
            quote = ch
            triple = source.startswith(ch * 3, i)
            if triple:
                i += 2
                col += 2
            i += 1
            continue
        if ch in "([{":
            stack.append((ch, line_no, col))
        elif ch in ")]}" :
            if not stack or stack[-1][0] != pairs[ch]:
                diagnostics.append(Diagnostic("Error", line_no, max(0, col - 1), f"Unmatched closing delimiter '{ch}'"))
            else:
                stack.pop()
        i += 1
    if quote:
        diagnostics.append(Diagnostic("Error", line_no, col, "Unterminated string literal"))
    for opener, row, column in stack:
        diagnostics.append(Diagnostic("Error", row, column - 1, f"Unclosed delimiter '{opener}'"))

    seen: dict[str, Symbol] = {}
    for symbol in extract_symbols(source):
        if symbol.kind in {"class", "function", "signal", "enum", "constant"}:
            if symbol.name in seen:
                diagnostics.append(Diagnostic("Warning", symbol.line, symbol.column,
                    f"'{symbol.name}' is declared more than once in this file"))
            else:
                seen[symbol.name] = symbol
    return sorted(diagnostics, key=lambda d: (d.line, d.column, d.severity != "Error"))


def project_symbols(root: str | Path, *, limit: int = 1500) -> list[str]:
    root = Path(root)
    words: set[str] = set()
    if not root.is_dir():
        return []
    count = 0
    for path in root.rglob("*.gd"):
        if any(part in {".godot", ".git"} for part in path.parts):
            continue
        try:
            for symbol in extract_symbols(path.read_text(encoding="utf-8")):
                if symbol.kind in {"class", "function", "signal", "enum", "constant", "variable"}:
                    words.add(symbol.name)
        except (OSError, UnicodeError):
            pass
        count += 1
        if count >= limit:
            break
    return sorted(words, key=str.casefold)
