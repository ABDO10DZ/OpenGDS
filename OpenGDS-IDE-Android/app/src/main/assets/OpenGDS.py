#!/usr/bin/env python3
"""OpenGDS / OGDS
GDSC inspector/decompiler/compiler with native static debugging for Godot 4.x GDSC v101.

Usage:
  python3 OpenGDS.py info <file-or-folder>
  python3 OpenGDS.py comp <file-or-folder> [--no-compress]
  python3 OpenGDS.py dcmp <file-or-folder>
  python3 OpenGDS.py hexdump <file-or-folder>
  python3 OpenGDS.py consts <file-or-folder>
  python3 OpenGDS.py audit <file-or-folder>
  python3 OpenGDS.py disasm <file-or-folder>
  python3 OpenGDS.py dbg <file-or-folder> [--breakpoint LINE] [--show-tokens]
  python3 OpenGDS.py diff <godot.gdc> <opengds.gdc>

GDSC analysis modes accept .gdc files. comp accepts .gd files and uses
a native Python port of Godot 4.5 GDSC v101 tokenization/serialization. Folder input is
recursive. Folder outputs go under <folder>.<mode>/ by default.
"""
from __future__ import annotations
import argparse, ctypes, ctypes.util, hashlib, json, math, os, re, shutil, struct, subprocess, tempfile, zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TOK = [
"EMPTY","ANNOTATION","IDENTIFIER","LITERAL","LESS","LESS_EQUAL","GREATER","GREATER_EQUAL","EQUAL_EQUAL","BANG_EQUAL",
"AND","OR","NOT","AMPERSAND_AMPERSAND","PIPE_PIPE","BANG","AMPERSAND","PIPE","TILDE","CARET","LESS_LESS","GREATER_GREATER",
"PLUS","MINUS","STAR","STAR_STAR","SLASH","PERCENT","EQUAL","PLUS_EQUAL","MINUS_EQUAL","STAR_EQUAL","STAR_STAR_EQUAL",
"SLASH_EQUAL","PERCENT_EQUAL","LESS_LESS_EQUAL","GREATER_GREATER_EQUAL","AMPERSAND_EQUAL","PIPE_EQUAL","CARET_EQUAL",
"IF","ELIF","ELSE","FOR","WHILE","BREAK","CONTINUE","PASS","RETURN","MATCH","WHEN","AS","ASSERT","AWAIT","BREAKPOINT",
"CLASS","CLASS_NAME","CONST","ENUM","EXTENDS","FUNC","IN","IS","NAMESPACE","PRELOAD","SELF","SIGNAL","STATIC","SUPER","TRAIT","VAR","VOID","YIELD",
"BRACKET_OPEN","BRACKET_CLOSE","BRACE_OPEN","BRACE_CLOSE","PARENTHESIS_OPEN","PARENTHESIS_CLOSE","COMMA","SEMICOLON","PERIOD","PERIOD_PERIOD","PERIOD_PERIOD_PERIOD",
"COLON","DOLLAR","FORWARD_ARROW","UNDERSCORE","NEWLINE","INDENT","DEDENT","CONST_PI","CONST_TAU","CONST_INF","CONST_NAN",
"VCS_CONFLICT_MARKER","BACKTICK","QUESTION_MARK","ERROR","TK_EOF"]
PUNCT={
"BRACKET_OPEN":"[","BRACKET_CLOSE":"]","BRACE_OPEN":"{","BRACE_CLOSE":"}","PARENTHESIS_OPEN":"(","PARENTHESIS_CLOSE":")","COMMA":",","SEMICOLON":";","PERIOD":".","PERIOD_PERIOD":"..","PERIOD_PERIOD_PERIOD":"...","COLON":":","DOLLAR":"$","FORWARD_ARROW":"->","UNDERSCORE":"_",
"LESS":"<","LESS_EQUAL":"<=","GREATER":">","GREATER_EQUAL":">=","EQUAL_EQUAL":"==","BANG_EQUAL":"!=","AND":"and","OR":"or","NOT":"not","AMPERSAND":"&","PIPE":"|","TILDE":"~","CARET":"^","LESS_LESS":"<<","GREATER_GREATER":">>","PLUS":"+","MINUS":"-","STAR":"*","STAR_STAR":"**","SLASH":"/","PERCENT":"%","EQUAL":"=","PLUS_EQUAL":"+=","MINUS_EQUAL":"-=","STAR_EQUAL":"*=","STAR_STAR_EQUAL":"**=","SLASH_EQUAL":"/=","PERCENT_EQUAL":"%=","LESS_LESS_EQUAL":"<<=","GREATER_GREATER_EQUAL":">>=","AMPERSAND_EQUAL":"&=","PIPE_EQUAL":"|=","CARET_EQUAL":"^=","AMPERSAND_AMPERSAND":"&&","PIPE_PIPE":"||","BANG":"!","QUESTION_MARK":"?","CONST_PI":"PI","CONST_TAU":"TAU","CONST_INF":"INF","CONST_NAN":"NAN"}
KEYWORDS={k:k.lower() for k in ["IF","ELIF","ELSE","FOR","WHILE","BREAK","CONTINUE","PASS","RETURN","MATCH","WHEN","AS","ASSERT","AWAIT","BREAKPOINT","CLASS","CLASS_NAME","CONST","ENUM","EXTENDS","FUNC","IN","IS","NAMESPACE","PRELOAD","SELF","SIGNAL","STATIC","SUPER","TRAIT","VAR","VOID","YIELD"]}
@dataclass
class Token:
    index:int; typ:int; arg:int; line:int; column:int|None

def _check_cancelled():
    callback = globals().get('_opengds_cancel_check')
    if callable(callback):
        callback()

def u32(b,p): return struct.unpack_from('<I',b,p)[0]

def read_variant(b,p):
    header=u32(b,p); p+=4; typ=header&0xff; flags=(header>>16)&0xff
    if typ==0:return None,p
    if typ==1:return bool(u32(b,p)),p+4
    if typ==2:
        if flags&1:return struct.unpack_from('<q',b,p)[0],p+8
        return struct.unpack_from('<i',b,p)[0],p+4
    if typ==3:
        if flags&1:return struct.unpack_from('<d',b,p)[0],p+8
        return struct.unpack_from('<f',b,p)[0],p+4
    if typ in (4,21):
        n=u32(b,p);p+=4;raw=b[p:p+n];s=raw.rstrip(b'\0').decode('utf-8','replace');p=(p+n+3)&~3
        return (('STRINGNAME',s) if typ==21 else s),p
    if typ==22:
        # Godot's current NodePath Variant layout is: name_count|0x80000000,
        # subname_count, np_flags (bit 0 = absolute), then UTF-8 strings.
        name_flags=u32(b,p);p+=4;nc=name_flags&0x7fffffff
        sc=u32(b,p);p+=4
        np_flags=u32(b,p);p+=4
        absolute=bool(np_flags&1)
        names=[]
        for _ in range(nc+sc):
            _check_cancelled()
            n=u32(b,p);p+=4;raw=b[p:p+n];p=(p+n+3)&~3
            names.append(raw.rstrip(b'\0').decode('utf-8','replace'))
        node='/'.join(names[:nc]); path=node+(':'+':'.join(names[nc:]) if sc else '')
        if absolute and not path.startswith('/'):path='/'+path
        return ('NODEPATH',path),p
    raise ValueError(f'unsupported Variant type {typ} at 0x{p-4:x}')

def decode_payload(data:bytes):
    """Validate GDSC v101 and return (version, decoded_size, decoded_payload)."""
    if data[:4]!=b'GDSC':raise ValueError('not GDSC')
    if len(data)<12:raise ValueError('short GDSC header')
    version=u32(data,4)
    if version != 101:
        raise ValueError(f'unsupported GDSC version {version}; OpenGDS currently supports GDSC v101')
    dec_size=u32(data,8);payload=data[12:]
    if dec_size:
        if shutil.which('zstd') is None:
            raise ValueError('zstd is required to decode compressed GDSC files; install the zstd command-line tool')
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'in.zst';o=Path(td)/'out.bin';a.write_bytes(payload)
            r=subprocess.run(['zstd','-q','-d','-f',str(a),'-o',str(o)],
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if r.returncode:
                raise ValueError('zstd decompression failed: '+r.stderr.decode(errors='replace'))
            raw=o.read_bytes()
        if len(raw)!=dec_size:
            raise ValueError(f'decompressed size mismatch: expected {dec_size}, got {len(raw)}')
    else:
        raw=payload
    return version,dec_size,raw

def decode_gdsc(data:bytes):
    version, dec_size, raw = decode_payload(data)
    if dec_size and len(raw)!=dec_size:
        raise ValueError(f'decompressed size mismatch: expected {dec_size}, got {len(raw)}')
    if len(raw)<16:raise ValueError('short payload')
    id_n,const_n,line_n,tok_n=struct.unpack_from('<4I',raw,0);p=16;ids=[]
    for _ in range(id_n):
        _check_cancelled()
        n=u32(raw,p);p+=4;chars=[]
        for j in range(n):
            x=bytes(c^0xB6 for c in raw[p+4*j:p+4*j+4]);chars.append(chr(struct.unpack('<I',x)[0]))
        p+=4*n;ids.append(''.join(chars))
    constants=[]
    for _ in range(const_n):
        _check_cancelled()
        v,p=read_variant(raw,p);constants.append(v)
    lm={}
    for _ in range(line_n):
        _check_cancelled()
        i,line=struct.unpack_from('<II',raw,p);p+=8
        if i in lm:
            raise ValueError(f'duplicate token index {i} in line map')
        lm[i]=line
    cm={}
    for _ in range(line_n):
        _check_cancelled()
        i,col=struct.unpack_from('<II',raw,p);p+=8
        if i in cm:
            raise ValueError(f'duplicate token index {i} in column map')
        cm[i]=col
    toks=[]
    for i in range(tok_n):
        _check_cancelled()
        word,line=struct.unpack_from('<II',raw,p);p+=8;typ=word&0x7f;arg=word>>8
        if typ>=len(TOK):raise ValueError(f'invalid token type {typ} at {i}')
        toks.append(Token(i,typ,arg,line,cm.get(i)))
    if p!=len(raw):raise ValueError(f'trailing payload: {len(raw)-p} bytes')
    return version,ids,constants,lm,cm,toks

def quote_string(s):return '"'+s.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')+'"'

def token_text(t,ids,constants):
    n=TOK[t.typ]
    if n in ('ANNOTATION','IDENTIFIER'):return ids[t.arg] if t.arg<len(ids) else f'<id:{t.arg}>'
    if n=='LITERAL':
        v=constants[t.arg] if t.arg<len(constants) else f'<const:{t.arg}>'
        if isinstance(v,tuple) and v[0]=='STRINGNAME':return '&'+quote_string(v[1])
        if isinstance(v,tuple) and v[0]=='NODEPATH':return '^'+quote_string(v[1])
        if isinstance(v,str):return quote_string(v)
        if v is True:return 'true'
        if v is False:return 'false'
        if v is None:return 'null'
        if isinstance(v,float) and math.isnan(v):return 'NAN'
        return str(v)
    if n in KEYWORDS:return KEYWORDS[n]
    if n in PUNCT:return PUNCT[n]
    if n in ('EMPTY','NEWLINE','INDENT','DEDENT','TK_EOF'):return ''
    return '<error>' if n=='ERROR' else n.lower()

def needs_space(prev,cur):
    if not prev:return False
    if cur in (')',']','}',',',';', '.', '..', ':'):return False
    if prev in ('(','[','{','.', '..','$'):return False
    if cur=='(':return prev in {'if','for','while','match','assert','await','return'}
    if prev==',':return True
    if prev==':' and cur=='=':return False
    ops=(":=",":","=","+","-","*","/","%","==","!=","<",">","<=",">=","and","or","as","is","->","+=","-=","*=","/=","%=","**=","<<=",">>=","&=","|=","^=")
    if prev in ops or cur in ops:return True
    return (prev[-1:].isalnum() or prev[-1:] in '_"\'') and (cur[:1].isalnum() or cur[:1] in '_"\'@')

def _indent_unit(columns):
    vals=sorted({c-1 for c in columns if c is not None and c > 1})
    if not vals:
        return 4
    from math import gcd
    g=0
    for v in vals:
        g=gcd(g,v)
    return g if 1 <= g <= 8 else 4

def _needs_backslash(prev_text, next_first, nesting):
    """Whether a physical source-line break must use GDScript's \\ continuation."""
    if nesting > 0:
        return False
    if not prev_text:
        return False
    # A block header ends the line naturally.
    if prev_text.endswith(':'):
        return False
    # Tokens that cannot legally terminate an expression.
    continuation_ends = {
        '=', ':=', '+=', '-=', '*=', '/=', '%=', '**=', '<<=', '>>=',
        '&=', '|=', '^=', '+', '-', '*', '/', '%', '**',
        '==', '!=', '<', '>', '<=', '>=', 'and', 'or', 'in', 'is', 'as',
        '.', '..', ',', '->', '?'
    }
    if prev_text in continuation_ends:
        return True
    # A next token that clearly continues an expression.
    if next_first in ('.', '[', '(', ')', ']', '}', ',', 'and', 'or', 'in', 'is', 'as'):
        return False
    return False

def _roundtrip_literal_text(token, ids, constants, index, tokens, column_map):
    """Choose literal spelling that preserves token start/end-line behavior."""
    if token.typ == 3:
        value = constants[token.arg]
        if isinstance(value, str) and "\n" in value and index + 1 < len(tokens):
            next_token = tokens[index + 1]
            delta = max(0, next_token.line - token.line)
            # If the next token has no position-map entry, its line must be
            # covered by this literal (or a continuation). Use only as many
            # physical newlines as needed; encode the remaining value newlines
            # as escaped \n so the literal value remains identical.
            physical_newlines = min(value.count("\n"), delta) if delta and (index + 1) not in column_map else 0
            if physical_newlines:
                body = []
                seen = 0
                for char in value:
                    if char == "\\":
                        body.append("\\\\")
                    elif char == '"':
                        body.append('\\"')
                    elif char == "\r":
                        body.append("\\r")
                    elif char == "\n":
                        body.append("\n" if seen < physical_newlines else "\\n")
                        seen += 1
                    elif char == "\t":
                        body.append("\\t")
                    else:
                        body.append(char)
                return '"""' + ''.join(body) + '"""'
    return token_text(token, ids, constants)


def reconstruct(ids, constants, line_map, column_map, tokens):
    """Rebuild source while preserving every v101 token line/column entry.

    GDSC strips comments and most whitespace, so source formatting is
    reconstructed. Unlike the former pretty-printer, this routine does not
    invent statement boundaries: stored token line numbers remain authoritative.
    """
    out = []
    physical_line = 1
    previous = ''
    nodepath = False

    for index, token in enumerate(tokens):
        _check_cancelled()
        text = _roundtrip_literal_text(token, ids, constants, index, tokens, column_map)
        if not text:
            continue

        if token.line > physical_line:
            delta = token.line - physical_line
            if index in column_map:
                out.append('\n' * delta)
                physical_line = token.line
                out.append(' ' * max(0, column_map[index] - 1))
                previous = ''
                nodepath = False
            else:
                # Godot removes explicit line-continuation lines from the
                # position maps. Recreate the continuation marker.
                out.append(' ' + chr(92) + '\n')
                physical_line += 1
                if delta > 1:
                    out.append('\n' * (delta - 1))
                    physical_line += delta - 1

        if text == '$':
            if previous in (':=', '=', '+=', '-=', '*=', '/=', '%=', '**='):
                out.append(' ')
            nodepath = True
        elif nodepath and (text == '/' or TOK[token.typ] == 'IDENTIFIER'):
            pass
        elif nodepath:
            if needs_space(previous, text):
                out.append(' ')
            nodepath = False
        elif needs_space(previous, text):
            out.append(' ')

        out.append(text)
        previous = text
        if text.startswith('"""'):
            physical_line += text.count('\n')

    out.append('\n')
    return ''.join(out)

def decode_file(path):return decode_gdsc(Path(path).read_bytes())

def iter_files(path, suffix='.gdc'):
    p=Path(path)
    if p.is_file():
        if suffix and p.suffix.lower()!=suffix:return []
        return [p]
    if p.is_dir():return sorted(x for x in p.rglob('*') if x.is_file() and (not suffix or x.suffix.lower()==suffix))
    raise FileNotFoundError(path)

def fmt_const(v):
    if isinstance(v,tuple):return f'{v[0]}: {v[1]!r}'
    if isinstance(v,float):
        if math.isnan(v):return 'NAN'
        if math.isinf(v):return 'INF' if v>0 else '-INF'
    return repr(v)

def hexdump(data,width=16):
    lines=[]
    for off in range(0,len(data),width):
        chunk=data[off:off+width];hx=' '.join(f'{x:02x}' for x in chunk);hx += '   '*(width-len(chunk));ascii_s=''.join(chr(x) if 32<=x<127 else '.' for x in chunk)
        lines.append(f'{off:08x}  {hx[:width*3-1]:<{width*3-1}}  |{ascii_s}|')
    return '\n'.join(lines)+'\n'

def const_report(path,decoded):
    version,ids,constants,lm,cm,toks=decoded
    out=[f'FILE: {path}',f'GDSC version: {version}',f'Identifiers: {len(ids)}',f'Constants: {len(constants)}','']
    for i,v in enumerate(constants):out.append(f'[{i:4}] {type(v).__name__:12} {fmt_const(v)}')
    return '\n'.join(out)+'\n'

def disasm_report(path,decoded):
    version,ids,constants,lm,cm,toks=decoded
    out=[f'FILE: {path}',f'GDSC version: {version}',f'Identifiers: {len(ids)}  Constants: {len(constants)}  Tokens: {len(toks)}','', 'INDEX  LINE COL  TYPE                   ARG     TEXT']
    for t in toks:out.append(f'{t.index:5} {t.line:5} {str(t.column if t.column is not None else "-"):>3}  {TOK[t.typ]:22} {t.arg:7}  {token_text(t,ids,constants)!r}')
    return '\n'.join(out)+'\n'


def validate_gdc_structure(decoded):
    """Return conservative structural diagnostics for a decoded GDSC v101 file.

    This checks the serialized token graph and source maps. It deliberately does
    not claim to parse GDScript semantics or execute the program.
    Each diagnostic is (severity, code, message, token_index).
    """
    version, ids, constants, line_map, column_map, tokens = decoded
    findings = []

    def add(severity, code, message, token_index=None):
        findings.append((severity, code, message, token_index))

    if version != 101:
        add('ERROR', 'BYTECODE_VERSION', f'expected GDSC v101, got v{version}')

    if not tokens:
        add('WARNING', 'EMPTY_TOKEN_STREAM', 'the token stream is empty')
        return findings

    token_count = len(tokens)
    if set(line_map) != set(column_map):
        add('ERROR', 'POSITION_MAP_KEYS', 'line and column maps reference different token indices')

    for index, line in line_map.items():
        if not 0 <= index < token_count:
            add('ERROR', 'LINE_MAP_INDEX', f'line map references token {index}, outside 0..{token_count - 1}')
        if line < 1:
            add('ERROR', 'LINE_MAP_VALUE', f'line map token {index} has invalid line {line}', index)
        elif index < token_count and tokens[index].line != line:
            add('ERROR', 'LINE_MAP_MISMATCH', f'line map says {line}, token stores line {tokens[index].line}', index)

    for index, column in column_map.items():
        if not 0 <= index < token_count:
            add('ERROR', 'COLUMN_MAP_INDEX', f'column map references token {index}, outside 0..{token_count - 1}')
        if column < 1:
            add('ERROR', 'COLUMN_MAP_VALUE', f'column map token {index} has invalid column {column}', index)

    delimiter_pairs = {
        TOK.index('PARENTHESIS_OPEN'): TOK.index('PARENTHESIS_CLOSE'),
        TOK.index('BRACKET_OPEN'): TOK.index('BRACKET_CLOSE'),
        TOK.index('BRACE_OPEN'): TOK.index('BRACE_CLOSE'),
    }
    close_to_open = {close: open_ for open_, close in delimiter_pairs.items()}
    stack = []
    previous_line = 0

    for token in tokens:
        if token.index % 1024 == 0:
            _check_cancelled()
        if token.index < 0 or token.index >= token_count:
            add('ERROR', 'TOKEN_INDEX', f'invalid token index {token.index}', token.index)

        if token.line < 1:
            add('ERROR', 'TOKEN_LINE', f'token has invalid source line {token.line}', token.index)
        elif token.line < previous_line:
            add('ERROR', 'NON_MONOTONIC_LINES',
                f'source line moved backwards from {previous_line} to {token.line}', token.index)
        previous_line = max(previous_line, token.line)

        if token.typ in (TOK.index('ANNOTATION'), TOK.index('IDENTIFIER')) and token.arg >= len(ids):
            add('ERROR', 'IDENTIFIER_REFERENCE',
                f'{TOK[token.typ]} references identifier[{token.arg}], but only {len(ids)} exist', token.index)
        elif token.typ == TOK.index('LITERAL') and token.arg >= len(constants):
            add('ERROR', 'CONSTANT_REFERENCE',
                f'LITERAL references constant[{token.arg}], but only {len(constants)} exist', token.index)

        if token.typ == TOK.index('ERROR'):
            add('ERROR', 'ERROR_TOKEN', 'the token stream contains a tokenizer ERROR token', token.index)
        elif token.typ == TOK.index('VCS_CONFLICT_MARKER'):
            add('WARNING', 'VCS_CONFLICT_MARKER', 'the source contains a version-control conflict marker', token.index)

        if token.typ in delimiter_pairs:
            stack.append((token.typ, token.index, token.line, token.column))
        elif token.typ in close_to_open:
            expected_open = close_to_open[token.typ]
            if not stack:
                add('ERROR', 'UNEXPECTED_CLOSER',
                    f'unexpected {TOK[token.typ]} without a matching opener', token.index)
            elif stack[-1][0] != expected_open:
                opener = stack[-1]
                add('ERROR', 'DELIMITER_MISMATCH',
                    f'{TOK[token.typ]} does not match {TOK[opener[0]]} opened at token {opener[1]}',
                    token.index)
                # Pop the mismatched opener to prevent a cascade of duplicate reports.
                stack.pop()
            else:
                stack.pop()

    for opener_type, index, line, column in stack:
        position = f'line {line}' + (f', column {column}' if column is not None else '')
        add('ERROR', 'UNCLOSED_DELIMITER',
            f'{TOK[opener_type]} opened at token {index} ({position}) has no matching closer', index)

    return findings


def dbg_report(path, decoded, breakpoints=(), show_tokens=False, context=4, max_tokens=200):
    """Native, engine-independent GDSC structural debugger (static analysis only)."""
    p = Path(path)
    data = p.read_bytes()
    version, ids, constants, line_map, column_map, tokens = decoded
    declared_size = u32(data, 8) if len(data) >= 12 else 0
    stored_size = max(0, len(data) - 12)
    raw_size = declared_size if declared_size else stored_size
    findings = validate_gdc_structure(decoded)

    type_counts = {}
    for token in tokens:
        name = TOK[token.typ]
        type_counts[name] = type_counts.get(name, 0) + 1

    out = [
        f'OPEN GDSC DEBUGGER: {p}',
        f'FORMAT: GDSC v{version}',
        f'CONTAINER: {len(data):,} bytes; {"Zstandard" if declared_size else "uncompressed"}',
        f'PAYLOAD: {raw_size:,} bytes; stored payload {stored_size:,} bytes',
        f'SYMBOLS: {len(ids):,} identifiers; {len(constants):,} constants',
        f'SOURCE MAP: {len(line_map):,} line entries; {len(column_map):,} column entries',
        f'TOKEN STREAM: {len(tokens):,} tokens',
        '',
    ]

    if findings:
        counts = {}
        for severity, _code, _message, _index in findings:
            counts[severity] = counts.get(severity, 0) + 1
        summary = ', '.join(f'{key}={counts[key]}' for key in ('ERROR', 'WARNING', 'INFO') if counts.get(key))
        out.append(f'DIAGNOSTICS: {len(findings)} ({summary})')
        for severity, code, message, index in findings:
            location = f' token #{index}' if index is not None else ''
            out.append(f'[{severity}] {code}{location}: {message}')
    else:
        out.append('DIAGNOSTICS: 0')
        out.append('STRUCTURE: PASS — references, source maps, token positions and delimiters are consistent')

    interesting = ('FUNC', 'CLASS', 'CLASS_NAME', 'VAR', 'CONST', 'SIGNAL', 'IF', 'ELIF',
                   'ELSE', 'FOR', 'WHILE', 'MATCH', 'RETURN', 'AWAIT', 'ASSERT', 'BREAKPOINT')
    counts = [(name, type_counts.get(name, 0)) for name in interesting if type_counts.get(name, 0)]
    out.append('')
    out.append('CODE SHAPE: ' + (', '.join(f'{name}={count}' for name, count in counts) if counts else 'no common declaration/control-flow tokens'))

    breakpoint_tokens = []
    tokens_by_line = {}
    for token in tokens:
        tokens_by_line.setdefault(token.line, token)
    available_lines = sorted(tokens_by_line)
    for source_line in breakpoints:
        if source_line < 1:
            out.append(f'BREAKPOINT line {source_line}: INVALID (line numbers start at 1)')
            continue
        token = tokens_by_line.get(source_line)
        if token is None:
            before = max((line for line in available_lines if line < source_line), default=None)
            after = min((line for line in available_lines if line > source_line), default=None)
            out.append(f'BREAKPOINT line {source_line}: UNRESOLVED (no token starts on that source line; nearest previous={before}, next={after})')
            continue
        col = f':{token.column}' if token.column is not None else ''
        out.append(f'BREAKPOINT line {source_line}: RESOLVED -> token #{token.index} at {source_line}{col} ({TOK[token.typ]} {token_text(token, ids, constants)!r})')
        breakpoint_tokens.append(token.index)

    if show_tokens:
        out.append('')
        out.append(f'TOKEN LIST (first {min(max_tokens, len(tokens)):,} of {len(tokens):,})')
        out.append('INDEX  LINE COL  TYPE                   ARG     TEXT')
        for token in tokens[:max_tokens]:
            out.append(f'{token.index:5} {token.line:5} {str(token.column if token.column is not None else "-"):>3}  {TOK[token.typ]:22} {token.arg:7}  {token_text(token, ids, constants)!r}')
        if len(tokens) > max_tokens:
            out.append(f'... {len(tokens) - max_tokens:,} tokens omitted; increase --max-tokens to inspect more')

    if breakpoint_tokens:
        selected = set()
        for index in breakpoint_tokens:
            selected.update(range(max(0, index - context), min(len(tokens), index + context + 1)))
        out.append('')
        out.append(f'BREAKPOINT CONTEXT (±{context} tokens)')
        out.append('INDEX  LINE COL  TYPE                   ARG     TEXT')
        for index in sorted(selected):
            token = tokens[index]
            marker = '>' if index in breakpoint_tokens else ' '
            out.append(f'{marker}{token.index:4} {token.line:5} {str(token.column if token.column is not None else "-"):>3}  {TOK[token.typ]:22} {token.arg:7}  {token_text(token, ids, constants)!r}')

    out.extend([
        '',
        'DEBUGGER SCOPE: Static GDSC analysis; no Godot executable or game runtime is launched.',
        'LIMIT: This maps source breakpoints to tokens and detects structural faults. It does not execute GDScript, inspect live variables, or prove semantic/runtime correctness.',
    ])
    return '\n'.join(out) + '\n'


def _safe_variant_summary(value):
    """Describe constants without dumping possible credentials or long string data."""
    if isinstance(value, tuple) and len(value) >= 2:
        kind, content = value[0], value[1]
        if isinstance(content, str):
            digest = hashlib.sha256(content.encode('utf-8')).hexdigest()[:12]
            return f'{kind}(chars={len(content)}, sha256={digest})'
        return f'{kind}({type(content).__name__})'
    if isinstance(value, str):
        digest = hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]
        return f'STRING(chars={len(value)}, sha256={digest})'
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    return type(value).__name__


def _safe_token_summary(token, ids, constants):
    name = TOK[token.typ]
    if token.typ in (TOK.index('ANNOTATION'), TOK.index('IDENTIFIER')):
        value = ids[token.arg] if token.arg < len(ids) else f'<bad-id:{token.arg}>'
        return f'{name} {value!r}'
    if token.typ == TOK.index('LITERAL'):
        value = constants[token.arg] if token.arg < len(constants) else f'<bad-constant:{token.arg}>'
        return f'{name} {_safe_variant_summary(value)}'
    return f'{name} arg={token.arg}'


def diff_report(path_a, path_b, decoded_a=None, decoded_b=None, max_differences=12):
    """Compare two GDSC containers at both compressed and decoded token levels."""
    a_path, b_path = Path(path_a), Path(path_b)
    a_data, b_data = a_path.read_bytes(), b_path.read_bytes()
    decoded_a = decoded_a or decode_gdsc(a_data)
    decoded_b = decoded_b or decode_gdsc(b_data)
    ver_a, ids_a, const_a, lines_a, cols_a, toks_a = decoded_a
    ver_b, ids_b, const_b, lines_b, cols_b, toks_b = decoded_b
    raw_a = decode_payload(a_data)[2]
    raw_b = decode_payload(b_data)[2]

    ids_equal = ids_a == ids_b
    constants_equal = const_a == const_b
    lines_equal = lines_a == lines_b
    columns_equal = cols_a == cols_b
    tokens_equal = toks_a == toks_b
    payload_equal = raw_a == raw_b
    container_equal = a_data == b_data

    out = [
        'OPEN GDSC DIFFERENTIAL REPORT',
        f'A: {a_path} ({len(a_data):,} bytes; SHA-256 {hashlib.sha256(a_data).hexdigest()[:16]})',
        f'B: {b_path} ({len(b_data):,} bytes; SHA-256 {hashlib.sha256(b_data).hexdigest()[:16]})',
        f'VERSION: A=v{ver_a}; B=v{ver_b}',
        f'CONTAINER BYTE-IDENTICAL: {"YES" if container_equal else "NO"}',
        f'DECODED PAYLOAD BYTE-IDENTICAL: {"YES" if payload_equal else "NO"}',
        f'DECODED PAYLOAD SHA-256: A={hashlib.sha256(raw_a).hexdigest()[:16]}; B={hashlib.sha256(raw_b).hexdigest()[:16]}',
        f'IDENTIFIERS: {len(ids_a)} vs {len(ids_b)}; equal={ids_equal}',
        f'CONSTANTS: {len(const_a)} vs {len(const_b)}; equal={constants_equal}',
        f'LINE MAPS: {len(lines_a)} vs {len(lines_b)}; equal={lines_equal}',
        f'COLUMN MAPS: {len(cols_a)} vs {len(cols_b)}; equal={columns_equal}',
        f'TOKENS: {len(toks_a)} vs {len(toks_b)}; equal={tokens_equal}',
        '',
    ]

    if payload_equal:
        out.append('RESULT: decoded GDSC data is identical; any file-level difference is container/compression representation only.')
    elif ver_a != ver_b:
        out.append('RESULT: bytecode versions differ; token-level comparison may not be meaningful across versions.')
    else:
        out.append('RESULT: decoded data differs; inspect the first differences below.')

    if not ids_equal:
        for i in range(min(max_differences, max(len(ids_a), len(ids_b)))):
            av = ids_a[i] if i < len(ids_a) else '<missing>'
            bv = ids_b[i] if i < len(ids_b) else '<missing>'
            if av != bv:
                out.append(f'IDENTIFIER DIFF [{i}]: A={av!r}; B={bv!r}')
                break
    if not constants_equal:
        for i in range(min(max_differences, max(len(const_a), len(const_b)))):
            av = const_a[i] if i < len(const_a) else '<missing>'
            bv = const_b[i] if i < len(const_b) else '<missing>'
            if av != bv:
                out.append(f'CONSTANT DIFF [{i}]: A={_safe_variant_summary(av)}; B={_safe_variant_summary(bv)}')
                break
    if not lines_equal:
        keys = sorted(set(lines_a) | set(lines_b))
        emitted = 0
        for index in keys:
            av, bv = lines_a.get(index), lines_b.get(index)
            if av != bv:
                out.append(f'LINE MAP DIFF token[{index}]: A={av}; B={bv}')
                emitted += 1
                if emitted >= max_differences: break
    if not columns_equal:
        keys = sorted(set(cols_a) | set(cols_b))
        emitted = 0
        for index in keys:
            av, bv = cols_a.get(index), cols_b.get(index)
            if av != bv:
                out.append(f'COLUMN MAP DIFF token[{index}]: A={av}; B={bv}')
                emitted += 1
                if emitted >= max_differences: break

    if not tokens_equal:
        differences = []
        total = max(len(toks_a), len(toks_b))
        for index in range(total):
            ta = toks_a[index] if index < len(toks_a) else None
            tb = toks_b[index] if index < len(toks_b) else None
            if ta != tb:
                differences.append((index, ta, tb))
                if len(differences) >= max_differences:
                    break
        out.append('')
        out.append(f'FIRST TOKEN DIFFERENCES (up to {max_differences}):')
        for index, ta, tb in differences:
            left = '<missing>' if ta is None else f'line={ta.line}, col={ta.column}, {_safe_token_summary(ta, ids_a, const_a)}'
            right = '<missing>' if tb is None else f'line={tb.line}, col={tb.column}, {_safe_token_summary(tb, ids_b, const_b)}'
            out.append(f'  token[{index}] A: {left}')
            out.append(f'             B: {right}')
    out.append('')
    out.append('NOTE: matching decoded payloads prove binary identity, not identical container compression or game runtime behavior.')
    return '\n'.join(out) + '\n'


def format_bytes(size):
    """Human-readable binary size while retaining exact bytes in the report."""
    value=float(size)
    for unit in ('B','KiB','MiB','GiB','TiB'):
        if value < 1024.0 or unit == 'TiB':
            return f'{size:,} bytes ({value:.2f} {unit})'
        value /= 1024.0


def info_report(path):
    """Report container metadata and fully validate supported GDSC v101 files."""
    p=Path(path)
    data=p.read_bytes()
    if len(data)<12:
        raise ValueError(f'short GDSC header: {len(data)} bytes; expected at least 12')
    if data[:4] != b'GDSC':
        raise ValueError('not a GDSC file (missing GDSC signature)')

    version=u32(data,4)
    declared_decoded_size=u32(data,8)
    stored_payload_size=len(data)-12
    digest=hashlib.sha256(data).hexdigest()
    out=[
        f'FILE: {p}',
        'FORMAT: Godot GDScript binary-token container (GDSC)',
        f'SIGNATURE: {data[:4].decode("ascii")}',
        f'BYTECODE VERSION: {version}',
        'ENGINE RELEASE: Not encoded in the GDSC header',
        f'FILE SIZE: {format_bytes(len(data))}',
        f'HEADER SIZE: 12 bytes',
        f'STORED PAYLOAD: {format_bytes(stored_payload_size)}',
        f'COMPRESSION: {"Zstandard" if declared_decoded_size else "None (raw payload)"}',
        f'DECLARED DECODED SIZE: {format_bytes(declared_decoded_size) if declared_decoded_size else "Not present (raw payload)"}',
        f'SHA-256: {digest}',
    ]

    if version != 101:
        out.append('VALIDATION: Not decoded (this OpenGDS build supports GDSC v101 only)')
        return '\n'.join(out)+'\n'

    decoded=decode_gdsc(data)
    _version,ids,constants,line_map,column_map,tokens=decoded
    raw_size=declared_decoded_size if declared_decoded_size else stored_payload_size
    out.extend([
        'VALIDATION: PASS (GDSC v101 structure and payload decoded)',
        f'DECODED PAYLOAD: {format_bytes(raw_size)}',
        f'IDENTIFIERS: {len(ids):,}',
        f'CONSTANTS: {len(constants):,}',
        f'TOKEN LINE ENTRIES: {len(line_map):,}',
        f'TOKEN COLUMN ENTRIES: {len(column_map):,}',
        f'TOKENS: {len(tokens):,}',
    ])
    if raw_size:
        ratio=stored_payload_size/raw_size
        if not declared_decoded_size:
            out.append('STORED / DECODED RATIO: 1.000 (uncompressed)')
        elif ratio < 1.0:
            out.append(f'STORED / DECODED RATIO: {ratio:.3f} ({(1.0-ratio)*100:.1f}% smaller)')
        elif ratio > 1.0:
            out.append(f'STORED / DECODED RATIO: {ratio:.3f} ({(ratio-1.0)*100:.1f}% larger; compression overhead for this small payload)')
        else:
            out.append('STORED / DECODED RATIO: 1.000 (same size)')
    return '\n'.join(out)+'\n'

SECRET_PATTERNS=[
 ('private_key',re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
 ('jwt',re.compile(r'\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b')),
 ('api_key_assignment',re.compile(r'(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd)\b\s*[:=]')),
 ('aws_access_key',re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
 ('github_token',re.compile(r'\bgh[pousr]_[A-Za-z0-9_]{20,}\b')),
 ('generic_secret_assignment',re.compile(r'(?i)\b(?:secret|token|credential|key)\b\s*[:=]\s*["\'][^"\']{8,}["\']')),
]
URL_RE=re.compile(r'https?://[^\s"\']+')

def audit_report(path,decoded):
    version,ids,constants,lm,cm,toks=decoded
    findings=[]
    for i,v in enumerate(constants):
        if isinstance(v,tuple):s=str(v[1])
        elif isinstance(v,str):s=v
        else:continue
        for name,rx in SECRET_PATTERNS:
            m=rx.search(s)
            if m:
                # Never print the matched credential/token material. Report only its type and location.
                findings.append((name,'constant',i,'<redacted>'))
        for m in URL_RE.finditer(s):
            scheme=m.group(0).split(':',1)[0].lower();severity='info'
            if scheme=='http':severity='medium'
            findings.append(('url',severity,i,m.group(0)))
    text='\n'.join(token_text(t,ids,constants) for t in toks)
    if re.search(r'(?i)\b(?:OS\.execute|OS\.shell_open|JavaScriptBridge|load_string|ResourceLoader\.load)\b',text):
        findings.append(('dynamic_execution','info','tokens','Potentially security-sensitive dynamic/external execution API reference'))
    out=[f'FILE: {path}',f'GDSC version: {version}',f'Constants scanned: {len(constants)}',f'Tokens scanned: {len(toks)}','']
    if not findings:out.append('RESULT: No high-confidence hard-coded secret patterns or suspicious URLs detected.')
    else:
        sev_order={'critical':0,'high':1,'medium':2,'info':3,'constant':4}
        out.append(f'FINDINGS: {len(findings)}')
        for kind,where,idx,detail in sorted(findings,key=lambda x:sev_order.get(x[1],9) if x[1] in sev_order else 9):
            if kind=='url':out.append(f'- URL [{where}] constant[{idx}]: {detail}')
            elif kind=='dynamic_execution':out.append(f'- DYNAMIC_EXECUTION [{where}]: {detail}')
            else:out.append(f'- POSSIBLE_SECRET [{kind}] constant[{idx}]: {detail}')
    out.append('NOTE: Audit is heuristic/static; absence of findings is not proof of security.')
    return '\n'.join(out)+'\n'


def const_summary(path, decoded):
    version,ids,constants,lm,cm,toks=decoded
    counts={}
    for v in constants:
        if isinstance(v,tuple): k=v[0].lower()
        elif v is None: k='null'
        elif isinstance(v,bool): k='bool'
        elif isinstance(v,int): k='int'
        elif isinstance(v,float): k='float'
        elif isinstance(v,str): k='string'
        else: k=type(v).__name__.lower()
        counts[k]=counts.get(k,0)+1
    parts=', '.join(f'{k}={counts[k]}' for k in sorted(counts))
    return f'{path}: constants={len(constants)} ({parts or "none"})'

def audit_summary(path, decoded):
    report=audit_report(path,decoded)
    if 'RESULT: No ' in report:
        return f'{path}: findings=0'
    m=re.search(r'^FINDINGS:\s*(\d+)',report,re.M)
    total=int(m.group(1)) if m else 0
    kinds={}
    for line in report.splitlines():
        m=re.match(r'- (?:POSSIBLE_SECRET \[([^\]]+)\]|URL \[([^\]]+)\]|DYNAMIC_EXECUTION)',line)
        if m:
            k=next((x for x in m.groups() if x), 'other')
            kinds[k]=kinds.get(k,0)+1
    suffix=', '.join(f'{k}={v}' for k,v in sorted(kinds.items()))
    return f'{path}: findings={total}' + (f' ({suffix})' if suffix else '')


# Native Python port of Godot 4.5 GDScript tokenizer-buffer v101.
# Godot 4.5 / GDSC tokenizer v101 enum from gdscript_tokenizer.h
TOK_NAMES = [
'EMPTY','ANNOTATION','IDENTIFIER','LITERAL','LESS','LESS_EQUAL','GREATER','GREATER_EQUAL','EQUAL_EQUAL','BANG_EQUAL',
'AND','OR','NOT','AMPERSAND_AMPERSAND','PIPE_PIPE','BANG','AMPERSAND','PIPE','TILDE','CARET','LESS_LESS','GREATER_GREATER',
'PLUS','MINUS','STAR','STAR_STAR','SLASH','PERCENT','EQUAL','PLUS_EQUAL','MINUS_EQUAL','STAR_EQUAL','STAR_STAR_EQUAL',
'SLASH_EQUAL','PERCENT_EQUAL','LESS_LESS_EQUAL','GREATER_GREATER_EQUAL','AMPERSAND_EQUAL','PIPE_EQUAL','CARET_EQUAL',
'IF','ELIF','ELSE','FOR','WHILE','BREAK','CONTINUE','PASS','RETURN','MATCH','WHEN','AS','ASSERT','AWAIT','BREAKPOINT',
'CLASS','CLASS_NAME','TK_CONST','ENUM','EXTENDS','FUNC','TK_IN','IS','NAMESPACE','PRELOAD','SELF','SIGNAL','STATIC','SUPER','TRAIT','VAR','TK_VOID','YIELD',
'BRACKET_OPEN','BRACKET_CLOSE','BRACE_OPEN','BRACE_CLOSE','PARENTHESIS_OPEN','PARENTHESIS_CLOSE','COMMA','SEMICOLON','PERIOD','PERIOD_PERIOD','PERIOD_PERIOD_PERIOD','COLON','DOLLAR','FORWARD_ARROW','UNDERSCORE',
'NEWLINE','INDENT','DEDENT','CONST_PI','CONST_TAU','CONST_INF','CONST_NAN','VCS_CONFLICT_MARKER','BACKTICK','QUESTION_MARK','ERROR','TK_EOF'
]
assert len(TOK_NAMES)==100, len(TOK_NAMES)
T={n:i for i,n in enumerate(TOK_NAMES)}
KW={
'as':'AS','and':'AND','assert':'ASSERT','await':'AWAIT','break':'BREAK','breakpoint':'BREAKPOINT','class':'CLASS','class_name':'CLASS_NAME','const':'TK_CONST','continue':'CONTINUE','elif':'ELIF','else':'ELSE','enum':'ENUM','extends':'EXTENDS','for':'FOR','func':'FUNC','if':'IF','in':'TK_IN','is':'IS','match':'MATCH','namespace':'NAMESPACE','not':'NOT','or':'OR','pass':'PASS','preload':'PRELOAD','return':'RETURN','self':'SELF','signal':'SIGNAL','static':'STATIC','super':'SUPER','trait':'TRAIT','var':'VAR','void':'TK_VOID','while':'WHILE','when':'WHEN','yield':'YIELD','INF':'CONST_INF','NAN':'CONST_NAN','PI':'CONST_PI','TAU':'CONST_TAU'
}
OPS={
'==':'EQUAL_EQUAL','!=':'BANG_EQUAL','&&':'AMPERSAND_AMPERSAND','||':'PIPE_PIPE','<<':'LESS_LESS','>>':'GREATER_GREATER',
'+=':'PLUS_EQUAL','-=':'MINUS_EQUAL','*=':'STAR_EQUAL','**=':'STAR_STAR_EQUAL','/=':'SLASH_EQUAL','%=':'PERCENT_EQUAL','<<=':'LESS_LESS_EQUAL','>>=':'GREATER_GREATER_EQUAL','&=':'AMPERSAND_EQUAL','|=':'PIPE_EQUAL','^=':'CARET_EQUAL',
'<=':'LESS_EQUAL','>=':'GREATER_EQUAL','->':'FORWARD_ARROW','**':'STAR_STAR',
'[':'BRACKET_OPEN',']':'BRACKET_CLOSE','{':'BRACE_OPEN','}':'BRACE_CLOSE','(':'PARENTHESIS_OPEN',')':'PARENTHESIS_CLOSE',',':'COMMA',';':'SEMICOLON','.':'PERIOD', '..':'PERIOD_PERIOD','...':'PERIOD_PERIOD_PERIOD',':':'COLON','$':'DOLLAR','_':'UNDERSCORE',
'<':'LESS','>':'GREATER','+':'PLUS','-':'MINUS','*':'STAR','/':'SLASH','%':'PERCENT','=':'EQUAL','!':'BANG','&':'AMPERSAND','|':'PIPE','~':'TILDE','^':'CARET','?':'QUESTION_MARK','`':'BACKTICK'
}
# Fix invalid typo mapping above.
OPS['=']='EQUAL'

@dataclass
class Tok:
    typ:int; val:object; line:int; col:int; end_line:int

class Lexer:
    def __init__(self, src, tab_size=4):
        self.s=src.replace('\r\n','\n').replace('\r','\n')
        self.i=0; self.line=1; self.col=1; self.tab=tab_size
        self.continuation_lines=[]; self.toks=[]
        self.last_type=T['EMPTY']; self.last_val=None
    def peek(self,n=0):
        j=self.i+n
        return self.s[j] if 0<=j<len(self.s) else ''
    def adv(self):
        if self.i>=len(self.s): return ''
        c=self.s[self.i]; self.i+=1
        if c=='\n': self.line+=1; self.col=1
        else: self.col+=1
        return c
    def add(self, typ, val=None, line=None, col=None):
        tok=Tok(typ, val, self.line if line is None else line, self.col if col is None else col, self.line)
        self.toks.append(tok); self.last_type=typ; self.last_val=val
        return tok
    def can_precede_bin(self):
        return self.last_type in {T['IDENTIFIER'],T['LITERAL'],T['SELF'],T['BRACKET_CLOSE'],T['BRACE_CLOSE'],T['PARENTHESIS_CLOSE'],T['CONST_PI'],T['CONST_TAU'],T['CONST_INF'],T['CONST_NAN']}
    def skip(self):
        while self.i<len(self.s):
            c=self.peek()
            if c in ' \t':
                self.adv()
                if c == '\t': self.col += self.tab - 1
                continue
            if c=='\n': self.adv(); continue
            if c=='#':
                while self.i<len(self.s) and self.peek()!='\n': self.adv()
                continue
            break
    def ident_start(self,c): return bool(c) and (c=='_' or c.isalpha() or ord(c)>=128 and (c.isidentifier()))
    def ident_cont(self,c): return bool(c) and (c=='_' or c.isalnum() or ord(c)>=128 and (('A'+c).isidentifier()))
    def scan_ident(self,at=False):
        st_line,st_col=self.line,self.col
        s=''
        while self.ident_cont(self.peek()): s+=self.adv()
        if at:
            self.add(T['ANNOTATION'],s,st_line,st_col); return
        if s=='_': self.add(T['UNDERSCORE'],'_',st_line,st_col); return
        if s in KW: self.add(T[KW[s]],s,st_line,st_col); return
        if s=='true': self.add(T['LITERAL'],True,st_line,st_col); return
        if s=='false': self.add(T['LITERAL'],False,st_line,st_col); return
        if s=='null': self.add(T['LITERAL'],None,st_line,st_col); return
        self.add(T['IDENTIFIER'],s,st_line,st_col)
    def scan_number(self, signed=''):
        st_line,st_col=self.line,self.col-(len(signed) if signed else 1)
        raw=signed
        # The first digit or dot has already been consumed by caller only if signed not empty? Keep simple by consuming rest from cursor.
        # caller has consumed first char; reconstruct prefix from last consumed.
        if not signed:
            raw=self.s[self.i-1]
        # Start from current cursor; follow Godot's basic number grammar.
        if raw.endswith('.'):
            has_dec=True
        else: has_dec=False
        base=10
        if raw.endswith('0') and self.peek() in 'xXbB':
            x=self.adv(); raw+=x; base=16 if x.lower()=='x' else 2
            while self.peek() and (self.peek().isdigit() or self.peek()=='_' or (base==16 and self.peek().lower() in 'abcdef')): raw+=self.adv()
        else:
            while self.peek() and (self.peek().isdigit() or self.peek()=='_'):
                raw+=self.adv()
            if base==10 and self.peek()=='.' and self.peek(1)!='.':
                has_dec=True; raw+=self.adv()
                while self.peek() and (self.peek().isdigit() or self.peek()=='_'): raw+=self.adv()
            if base==10 and self.peek() in 'eE':
                has_dec=True; raw+=self.adv()
                if self.peek() in '+-': raw+=self.adv()
                while self.peek() and (self.peek().isdigit() or self.peek()=='_'): raw+=self.adv()
        clean=raw.replace('_','')
        try:
            if base==16: val=int(clean,16)
            elif base==2: val=int(clean,2)
            elif has_dec or 'e' in clean.lower(): val=float(clean)
            else: val=int(clean,10)
        except Exception: raise ValueError(f'bad number {raw} at {st_line}:{st_col}')
        self.add(T['LITERAL'],val,st_line,st_col)
    def scan_string(self, prefix=''):
        st_line=self.line; st_col=self.col-len(prefix)-1 # prefix and opening quote consumed
        quote=self.s[self.i-1]
        # For prefix r/&/^, opening quote was just consumed after prefix.
        multiline=self.peek()==quote and self.peek(1)==quote
        if multiline:
            self.adv(); self.adv()
        out=[]; raw=(prefix=='r'); typ='STRING'
        if prefix=='&': typ='STRINGNAME'
        elif prefix=='^': typ='NODEPATH'
        while self.i<len(self.s):
            c=self.peek()
            if c=='\\':
                self.adv()
                if not self.peek(): raise ValueError('unterminated string')
                esc=self.adv()
                if raw:
                    if esc==quote: out.extend(['\\',quote])
                    elif esc=='\\': out.extend(['\\','\\'])
                    else: out.append('\\')
                else:
                    mp={'a':'\a','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t','v':'\v',"'":"'",'"':'"','\\':'\\'}
                    if esc in mp: out.append(mp[esc])
                    elif esc in ('u','U'):
                        n=4 if esc=='u' else 6
                        hx=''.join(self.adv() for _ in range(n))
                        out.append(chr(int(hx,16)))
                    elif esc=='\n': pass
                    else: raise ValueError(f'invalid escape \\{esc}')
                continue
            if c==quote:
                self.adv()
                if multiline:
                    if self.peek()==quote and self.peek(1)==quote:
                        self.adv(); self.adv(); break
                    out.append(quote)
                else: break
                continue
            self.adv(); out.append(c)
        else: raise ValueError('unterminated string')
        v=''.join(out)
        if typ=='STRINGNAME': val=('STRINGNAME',v)
        elif typ=='NODEPATH': val=('NODEPATH',v)
        else: val=v
        self.add(T['LITERAL'],val,st_line,st_col)
    def tokenize(self):
        while self.i<len(self.s):
            self.skip()
            if self.i>=len(self.s): break
            st_line,st_col=self.line,self.col
            c=self.adv()
            if c=='\\':
                if self.peek()=='\n':
                    self.adv(); self.continuation_lines.append(self.line); continue
                raise ValueError(f'Unexpected backslash at {st_line}:{st_col}')
            if c.isdigit(): self.scan_number(); continue
            if c=='.' and self.peek().isdigit(): self.scan_number(); continue
            if c=='r' and self.peek() in ('"',"'"):
                self.adv(); self.scan_string('r'); continue
            if self.ident_start(c):
                # identifier scan with first char consumed
                while self.ident_cont(self.peek()): c+=self.adv()
                if c=='_': self.add(T['UNDERSCORE'],'_',st_line,st_col)
                elif c in KW: self.add(T[KW[c]],c,st_line,st_col)
                elif c=='true': self.add(T['LITERAL'],True,st_line,st_col)
                elif c=='false': self.add(T['LITERAL'],False,st_line,st_col)
                elif c=='null': self.add(T['LITERAL'],None,st_line,st_col)
                else: self.add(T['IDENTIFIER'],c,st_line,st_col)
                continue
            if c=='@':
                name=''
                if not self.ident_start(self.peek()): raise ValueError(f'bad annotation at {st_line}:{st_col}')
                name+=self.adv()
                while self.ident_cont(self.peek()): name+=self.adv()
                self.add(T['ANNOTATION'],'@'+name,st_line,st_col); continue
            if c in ('"',"'"):
                self.scan_string(); continue
            if c in ('&','^') and self.peek() in ('"',"'"):
                self.adv(); self.scan_string(c); continue
            # signed numbers: Godot treats +/- as part of literal where prior token cannot end expression
            if c in '+-' and self.peek().isdigit() and not self.can_precede_bin():
                self.scan_number(c); continue
            # Longest multi-char operator
            op=None
            for n in (3,2):
                cand=c+''.join(self.peek(k) for k in range(n-1))
                if cand in OPS:
                    op=cand
                    for _ in range(n-1): self.adv()
                    break
            if op is None: op=c
            if op not in OPS: raise ValueError(f'unknown char {op!r} at {st_line}:{st_col}')
            if op=='.' and self.peek().isdigit():
                self.scan_number(); continue
            self.add(T[OPS[op]],op,st_line,st_col)
        return self.toks, self.continuation_lines

# --- Variant writer and GDSC v101 serialization ---
def variant_key(v):
    if isinstance(v,tuple): return v
    if v is None: return ('nil',)
    if isinstance(v,bool): return ('bool',v)
    if isinstance(v,int): return ('int',v)
    if isinstance(v,float): return ('float',struct.pack('<d',v))
    if isinstance(v,str): return ('string',v)
    return (type(v).__name__,repr(v))

def encode_variant(v):
    if v is None: return struct.pack('<I',0)
    if isinstance(v,bool): return struct.pack('<II',1,int(v))
    if isinstance(v,int):
        if v>2147483647 or v< -2147483648: return struct.pack('<Iq',2|(1<<16),v)
        return struct.pack('<Ii',2,v)
    if isinstance(v,float):
        f=struct.unpack('<f',struct.pack('<f',v))[0]
        if float(f)==v: return struct.pack('<If',3,f)
        return struct.pack('<Id',3|(1<<16),v)
    if isinstance(v,str):
        data=v.encode('utf-8'); pad=(-len(data))%4
        return struct.pack('<II',4,len(data))+data+b'\0'*pad
    if isinstance(v,tuple) and v[0]=='STRINGNAME':
        data=v[1].encode('utf-8'); pad=(-len(data))%4
        return struct.pack('<II',21,len(data))+data+b'\0'*pad
    if isinstance(v,tuple) and v[0]=='NODEPATH':
        # Basic NodePath support: slash-delimited names, colon-delimited subnames.
        path=v[1]; absolute=path.startswith('/')
        body=path[1:] if absolute else path
        bits=body.split(':'); node=bits[0]; subs=bits[1:] if len(bits)>1 else []
        names=[x for x in node.split('/') if x]
        out=bytearray(struct.pack('<III',len(names)|0x80000000,len(subs),1 if absolute else 0))
        for s in names+subs:
            b=s.encode(); out += struct.pack('<I',len(b))+b+b'\0'*((-len(b))%4)
        return struct.pack('<I',22)+out
    raise TypeError(f'unsupported Variant: {v!r}')

def zstd_compress(data, level=3):
    libname=ctypes.util.find_library('zstd')
    if not libname: raise RuntimeError('libzstd not found (needed for Godot-compatible Zstandard output)')
    lib=ctypes.CDLL(libname)
    lib.ZSTD_compressBound.argtypes=[ctypes.c_size_t]; lib.ZSTD_compressBound.restype=ctypes.c_size_t
    lib.ZSTD_compress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]; lib.ZSTD_compress.restype=ctypes.c_size_t
    lib.ZSTD_isError.argtypes=[ctypes.c_size_t]; lib.ZSTD_isError.restype=ctypes.c_uint
    cap=lib.ZSTD_compressBound(len(data)); dst=ctypes.create_string_buffer(cap); src=ctypes.create_string_buffer(data)
    n=lib.ZSTD_compress(dst,cap,src,len(data),level)
    if lib.ZSTD_isError(n): raise RuntimeError('Zstandard compression failed')
    return dst.raw[:n]

def compile_gd(src, compress=True, tab_size=4):
    lexer=Lexer(src,tab_size=tab_size); toks, continuation_lines=lexer.tokenize()
    ids=[]; id_map={}; constants=[]; c_map={}
    token_bin=bytearray(); token_lines={}; token_cols={}; last_line=0
    for i,t in enumerate(toks):
        _check_cancelled()
        typ=t.typ; tv=typ
        if typ in (T['ANNOTATION'],T['IDENTIFIER']):
            key=t.val
            if key not in id_map: id_map[key]=len(ids); ids.append(key)
            tv |= id_map[key]<<8
        elif typ==T['LITERAL']:
            key=variant_key(t.val)
            if key not in c_map: c_map[key]=len(constants); constants.append(t.val)
            tv |= c_map[key]<<8
        token_bin += struct.pack('<II',tv|0x80,t.line)
        if i>0 and t.line>last_line:
            token_lines[i]=t.line; token_cols[i]=t.col
        last_line=t.end_line
    # Remove column/line entries for explicit continuation lines, as the engine does.
    for line in continuation_lines:
        idx=next((k for k,v in token_lines.items() if v==line),None)
        if idx is not None: token_lines.pop(idx,None); token_cols.pop(idx,None)
    content=bytearray(struct.pack('<4I',len(ids),len(constants),len(token_lines),len(toks)))
    for s in ids:
        codepoints=[ord(ch) for ch in s]
        content += struct.pack('<I',len(codepoints))
        for cp in codepoints: content += bytes(x^0xb6 for x in struct.pack('<I',cp))
    for v in constants: content += encode_variant(v)
    for i,line in sorted(token_lines.items()): content += struct.pack('<II',i,line)
    for i,col in sorted(token_cols.items()): content += struct.pack('<II',i,col)
    content += token_bin
    if compress:
        payload=zstd_compress(bytes(content),3)
        return b'GDSC'+struct.pack('<II',101,len(content))+payload
    return b'GDSC'+struct.pack('<II',101,0)+content


def process_one(mode,path,stdout=False,args=None):
    if mode=='info':return info_report(path)
    if mode=='hexdump':
        # Hexdump the decoded GDSC payload, not the compressed GDSC container.
        _version, _header_field, raw = decode_payload(Path(path).read_bytes())
        return hexdump(raw)
    decoded=decode_file(path)
    if mode=='dcmp':return reconstruct(decoded[1],decoded[2],decoded[3],decoded[4],decoded[5])
    if mode=='dbg':
        args = args or argparse.Namespace(breakpoint=[], show_tokens=False, context=4, max_tokens=200)
        return dbg_report(path, decoded, breakpoints=args.breakpoint, show_tokens=args.show_tokens, context=args.context, max_tokens=args.max_tokens)
    if mode=='consts':return const_report(path,decoded)
    if mode=='disasm':return disasm_report(path,decoded)
    if mode=='audit':return audit_report(path,decoded)
    raise ValueError(mode)

def compile_gd_file(src_path, dest_path, compressed=True, force=False, tab_size=4):
    """Compile GDScript text into a native GDSC v101 tokenizer buffer.

    This is a direct Python implementation of Godot's tokenizer-buffer writer;
    it does not launch or require the Godot editor.
    """
    src_path = Path(src_path)
    dest_path = Path(dest_path)
    if dest_path.exists() and not force:
        raise FileExistsError(f'Output exists (use --force to replace it): {dest_path}')

    source = src_path.read_text(encoding='utf-8-sig')
    output = compile_gd(source, compress=compressed, tab_size=tab_size)
    decoded = decode_gdsc(output)
    if decoded[0] != 101:
        raise ValueError(f'compiler produced unsupported GDSC version {decoded[0]}')
    structural_errors = [item for item in validate_gdc_structure(decoded) if item[0] == 'ERROR']
    if structural_errors:
        summary = '; '.join(f'{code}: {message}' for _severity, code, message, _index in structural_errors[:8])
        raise ValueError(f'compiled GDSC failed structural validation: {summary}')

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(dest_path.name + '.opengds-tmp')
    try:
        temp_path.write_bytes(output)
        temp_path.replace(dest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return hashlib.sha256(output).hexdigest(), len(output), len(decoded[5])


def run_comp(args, path):
    files = iter_files(path, suffix='.gd')
    if not files:
        raise SystemExit(f'No .gd files found: {path}')

    input_path = Path(path)
    is_folder = input_path.is_dir()
    if is_folder:
        output_root = Path(args.outdir or args.output) if (args.outdir or args.output) else Path(str(input_path) + '.comp')
    elif args.outdir:
        output_root = Path(args.outdir) / input_path.with_suffix('.gdc').name
    else:
        output_root = Path(args.output) if args.output else input_path.with_suffix('.gdc')

    base = input_path.resolve()
    ok = bad = 0
    for source in files:
        try:
            if is_folder:
                rel = source.resolve().relative_to(base)
                dest = output_root / rel.with_suffix('.gdc')
            else:
                dest = output_root
            digest, size, token_count = compile_gd_file(
                source, dest, compressed=not args.no_compress,
                force=args.force, tab_size=args.tab_size
            )
            ok += 1
            print(f'[OK] {source} -> {dest}  tokens={token_count}  size={size}  SHA-256={digest}')
        except Exception as error:
            bad += 1
            print(f'[ERROR] {source}: {error}', file=os.sys.stderr)
            if not args.continue_on_error:
                print('Stopped. Use --continue-on-error to process remaining .gd files.', file=os.sys.stderr)
                raise SystemExit(2)

    print(f'Compiled: {ok}  Failed: {bad}  Output directory: {output_root if is_folder else output_root.parent}')
    if bad:
        raise SystemExit(2)


def main():
    ap=argparse.ArgumentParser(prog='OpenGDS')
    ap.add_argument('mode',choices=['info','comp','dcmp','hexdump','audit','consts','disasm','dbg','diff'])
    ap.add_argument('path')
    ap.add_argument('other',nargs='?',help='second GDC file for diff mode')
    ap.add_argument('-o','--output',help='output file for single-file input, or output root for folder input')
    ap.add_argument('--outdir',help='output root for folder input')
    ap.add_argument('--continue-on-error',action='store_true',help='continue recursive processing after a bad GDC')
    ap.add_argument('--tab-size',type=int,default=4,help='tab width used when measuring source columns (default: 4)')
    ap.add_argument('--no-compress',action='store_true',help='write uncompressed GDSC token data (comp only)')
    ap.add_argument('--force',action='store_true',help='overwrite existing comp output files')
    ap.add_argument('-b','--breakpoint',dest='breakpoint',type=int,action='append',default=[],help='map a source-line breakpoint to its first GDSC token (dbg only; repeatable)')
    ap.add_argument('--context',type=int,default=4,help='tokens of context around each mapped breakpoint (dbg only)')
    ap.add_argument('--show-tokens',action='store_true',help='include a token listing in dbg output')
    ap.add_argument('--max-tokens',type=int,default=200,help='maximum token rows shown by --show-tokens (dbg only)')
    args=ap.parse_args()
    if args.context < 0 or args.max_tokens < 1:
        raise SystemExit('ERROR: --context must be >= 0 and --max-tokens must be >= 1')
    p=Path(args.path)

    if args.mode == 'diff':
        if not args.other:
            raise SystemExit('ERROR: diff requires two .gdc files: diff <file-a.gdc> <file-b.gdc>')
        other = Path(args.other)
        if not p.is_file() or not other.is_file():
            raise SystemExit('ERROR: diff accepts two individual .gdc files, not folders')
        try:
            result = diff_report(p, other)
        except Exception as error:
            raise SystemExit(f'ERROR: diff: {error}')
        if args.output:
            Path(args.output).write_text(result, encoding='utf-8')
        else:
            print(result, end='')
        return
    if args.other:
        raise SystemExit('ERROR: the second path argument is supported only by diff mode')

    if args.mode=='comp':
        try:
            run_comp(args,p)
        except Exception as e:
            raise SystemExit(f'ERROR: {e}')
        return

    suffix='.gdc'
    files=iter_files(p,suffix=suffix)
    if not files:
        raise SystemExit(f'No {suffix} files found: {p}')
    is_folder=p.is_dir()
    if not is_folder:
        try:result=process_one(args.mode,p,args=args)
        except Exception as e:
            raise SystemExit(f'ERROR: {p}: {e}')
        if args.output:Path(args.output).write_text(result,encoding='utf-8')
        else:print(result,end='')
        return

    root=Path(args.outdir or args.output) if (args.outdir or args.output) else Path(str(p)+'.'+args.mode)
    root.mkdir(parents=True,exist_ok=True)
    base=p.resolve()
    ok=bad=0
    summaries=[]
    for f in files:
        try:
            result=process_one(args.mode,f,args=args)
            if args.mode=='consts':
                summaries.append(const_summary(f, decode_file(f)))
            elif args.mode=='audit':
                summaries.append(audit_summary(f, decode_file(f)))
            rel=f.resolve().relative_to(base)
            if args.mode=='dcmp':ext='.gd'
            elif args.mode=='hexdump':ext='.hex'
            elif args.mode=='dbg':ext='.dbg.txt'
            else:ext=f'.{args.mode}.txt'
            dest=(root/rel).with_suffix(ext)
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(result,encoding='utf-8')
            ok+=1
            print(f'[OK] {f} -> {dest}')
        except Exception as e:
            bad+=1
            print(f'[ERROR] {f}: {e}',file=os.sys.stderr)
            if not args.continue_on_error:
                print('Stopped. Use --continue-on-error to process the remaining files.',file=os.sys.stderr)
                raise SystemExit(2)
    if args.mode in ('consts','audit') and summaries:
        summary_path=root/'SUMMARY.txt'
        summary_path.write_text('\n'.join(summaries)+'\n',encoding='utf-8')
        print(f'=== {args.mode} summary ===')
        for summary in summaries:print(summary)
        print(f'Summary: {summary_path}')
    print(f'Processed: {ok}  Failed: {bad}  Output directory: {root}')
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
