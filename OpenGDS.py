#!/usr/bin/env python3
"""OpenGDS / OGDS
GDSC inspector/decompiler for the supplied Godot 4.x GDSC v101 corpus.

Usage:
  python3 OpenGDS.py dcmp <file-or-folder>
  python3 OpenGDS.py hexdump <file-or-folder>
  python3 OpenGDS.py consts <file-or-folder>
  python3 OpenGDS.py audit <file-or-folder>
  python3 OpenGDS.py disasm <file-or-folder>

Folders are processed recursively. For folder input, generated artifacts are
written under <folder>.<mode>/ by default. Use --outdir to choose another root.
"""
from __future__ import annotations
import argparse, json, math, os, re, struct, subprocess, tempfile, zipfile
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
"BRACKET_OPEN","BRACKET_CLOSE","BRACE_OPEN","BRACE_CLOSE","PARENTHESIS_OPEN","PARENTHESIS_CLOSE","COMMA","SEMICOLON","PERIOD","PERIOD_PERIOD","QUESTION_MARK",
"COLON","DOLLAR","FORWARD_ARROW","UNDERSCORE","NEWLINE","INDENT","DEDENT","CONST_PI","CONST_TAU","CONST_INF","CONST_NAN",
"VCS_CONFLICT_MARKER","BACKTICK","ERROR","TK_EOF"]
PUNCT={
"BRACKET_OPEN":"[","BRACKET_CLOSE":"]","BRACE_OPEN":"{","BRACE_CLOSE":"}","PARENTHESIS_OPEN":"(","PARENTHESIS_CLOSE":")","COMMA":",","SEMICOLON":";","PERIOD":".","PERIOD_PERIOD":"..","COLON":":","DOLLAR":"$","FORWARD_ARROW":"->","UNDERSCORE":"_",
"LESS":"<","LESS_EQUAL":"<=","GREATER":">","GREATER_EQUAL":">=","EQUAL_EQUAL":"==","BANG_EQUAL":"!=","AND":"and","OR":"or","NOT":"not","AMPERSAND":"&","PIPE":"|","TILDE":"~","CARET":"^","LESS_LESS":"<<","GREATER_GREATER":">>","PLUS":"+","MINUS":"-","STAR":"*","STAR_STAR":"**","SLASH":"/","PERCENT":"%","EQUAL":"=","PLUS_EQUAL":"+=","MINUS_EQUAL":"-=","STAR_EQUAL":"*=","STAR_STAR_EQUAL":"**=","SLASH_EQUAL":"/=","PERCENT_EQUAL":"%=","LESS_LESS_EQUAL":"<<=","GREATER_GREATER_EQUAL":">>=","AMPERSAND_EQUAL":"&=","PIPE_EQUAL":"|=","CARET_EQUAL":"^=","AMPERSAND_AMPERSAND":"&&","PIPE_PIPE":"||","BANG":"!","QUESTION_MARK":"?","CONST_PI":"PI","CONST_TAU":"TAU","CONST_INF":"INF","CONST_NAN":"NAN"}
KEYWORDS={k:k.lower() for k in ["IF","ELIF","ELSE","FOR","WHILE","BREAK","CONTINUE","PASS","RETURN","MATCH","WHEN","AS","ASSERT","AWAIT","BREAKPOINT","CLASS","CLASS_NAME","CONST","ENUM","EXTENDS","FUNC","IN","IS","NAMESPACE","PRELOAD","SELF","SIGNAL","STATIC","SUPER","TRAIT","VAR","VOID","YIELD"]}
@dataclass
class Token:
    index:int; typ:int; arg:int; line:int; column:int|None

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
        nf=u32(b,p);p+=4;nc=nf&0x7fffffff;sf=u32(b,p);p+=4;sc=sf&0x7fffffff;absolute=bool(sf&0x80000000);p+=4
        names=[]
        for _ in range(nc+sc):
            n=u32(b,p);p+=4;raw=b[p:p+n];p=(p+n+3)&~3;names.append(raw.rstrip(b'\0').decode('utf-8','replace'))
        node='/'.join(names[:nc]); path=node+(':'+':'.join(names[nc:]) if sc else '')
        if absolute and not path.startswith('/'):path='/'+path
        elif not absolute:path='^'+path
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
    if dec_size and len(payload)!=dec_size:
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'in.zst';o=Path(td)/'out.bin';a.write_bytes(payload)
            r=subprocess.run(['zstd','-q','-d','-f',str(a),'-o',str(o)],
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if r.returncode:
                raise ValueError('zstd decompression failed: '+r.stderr.decode(errors='replace'))
            raw=o.read_bytes()
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
        n=u32(raw,p);p+=4;chars=[]
        for j in range(n):
            x=bytes(c^0xB6 for c in raw[p+4*j:p+4*j+4]);chars.append(chr(struct.unpack('<I',x)[0]))
        p+=4*n;ids.append(''.join(chars))
    constants=[]
    for _ in range(const_n):v,p=read_variant(raw,p);constants.append(v)
    lm={}
    for _ in range(line_n):i,line=struct.unpack_from('<II',raw,p);p+=8;lm[i]=line
    cm={}
    for _ in range(line_n):i,col=struct.unpack_from('<II',raw,p);p+=8;cm[i]=col
    toks=[]
    for i in range(tok_n):
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
        if isinstance(v,tuple) and v[0]=='NODEPATH':return '^'+quote_string(v[1][1:]) if v[1].startswith('^') else quote_string(v[1])
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

def reconstruct(ids,constants,line_map,tokens):
    """
    Reconstruct from the compiler's token line/column metadata.

    Important:
      * token.line is the authoritative source line
      * token.column is a 1-based character column for the first token on a line
      * columns cannot distinguish tabs from spaces, so indentation depth is
        reconstructed from the smallest common column step and emitted as tabs
      * physical line continuations are restored only when the expression
        requires a backslash; lines inside (), [], {} do not need one.
    """
    rows=[]
    cur_line=None
    parts=[]
    prev=''
    nesting=0
    first_col=None
    skip_equal=False
    line_first_text=''
    line_last_text=''
    line_nesting_start=0
    nodepath=False

    def flush(next_first=None, next_line=None):
        nonlocal parts,prev,nesting,cur_line,first_col,line_first_text,line_last_text,line_nesting_start
        if cur_line is None:
            return
        text=''.join(parts).rstrip()
        rows.append({
            'line':cur_line,
            'text':text,
            'col':first_col,
            'last':line_last_text,
            'nesting':line_nesting_start,
            'next_first':next_first,
        })
        parts=[];prev='';first_col=None;line_first_text='';line_last_text=''

    for pos,t in enumerate(tokens):
        n=TOK[t.typ]
        if n in ('NEWLINE','INDENT','DEDENT','TK_EOF'):
            continue

        # Some GDSC revisions lose/flatten token line numbers for statements
        # that follow a block header. Recover the boundary from GDScript syntax.
        if cur_line is not None and t.line == cur_line and nesting == 0 and parts:
            prev_name = TOK[tokens[pos-1].typ] if pos else ''
            current_text = ''.join(parts).rstrip()
            statement_start = n in (
                'IF','ELIF','ELSE','FOR','WHILE','MATCH','VAR','CONST','SIGNAL',
                'RETURN','BREAK','CONTINUE','FUNC','CLASS_NAME','ANNOTATION'
            )
            bare_expr_start = n == 'IDENTIFIER' and prev_name in (
                'PARENTHESIS_CLOSE','IDENTIFIER','LITERAL'
            )
            same_line_else_if = (
                n == 'IF'
                and re.sub(r'\s+', '', current_text).endswith('else:')
            )
            if (
                (current_text.endswith(':') and statement_start and not same_line_else_if)
                or bare_expr_start
            ):
                flush()
                cur_line=t.line
                line_nesting_start=nesting

        # Detect a source line transition before consuming this token.
        if cur_line is None:
            cur_line=t.line
            line_nesting_start=nesting
        elif t.line != cur_line:
            # We know the first token of the new source line now.
            next_text=token_text(t,ids,constants)
            flush(next_text,t.line)
            cur_line=t.line
            line_nesting_start=nesting

        if first_col is None and t.column is not None:
            first_col=t.column

        # := is represented by COLON + EQUAL in this GDSC token stream.
        if n=='COLON' and pos+1<len(tokens) and TOK[tokens[pos+1].typ]=='EQUAL':
            st=':='
            skip_equal=True
        elif skip_equal and n=='EQUAL':
            skip_equal=False
            continue
        else:
            skip_equal=False
            st=token_text(t,ids,constants)

        if not st:
            continue

        # `$Foo/Bar` is a NodePath: slash is part of the path, not division.
        # Keep NodePath mode through every identifier/path separator; leave it
        # only when a real operator/keyword follows (e.g. `as Type`).
        if st == '$':
            if prev in (':=', '=', '+=', '-=', '*=', '/=', '%=', '**='):
                parts.append(' ')
            nodepath=True
        elif nodepath and (st == '/' or n == 'IDENTIFIER'):
            pass
        elif nodepath:
            if needs_space(prev, st):
                parts.append(' ')
            nodepath=False
        elif needs_space(prev,st):
            parts.append(' ')
        parts.append(st)
        prev=st
        line_last_text=st
        if not line_first_text:
            line_first_text=st

        if st in ('(', '[', '{'):
            nesting += 1
        elif st in (')', ']', '}'):
            nesting=max(0,nesting-1)

    flush()
    if not rows:
        return ''

    # Infer indentation depth from source columns.
    unit=_indent_unit([r['col'] for r in rows])
    out=[]
    previous_line=None

    for i,r in enumerate(rows):
        line=r['line']
        if previous_line is not None and line > previous_line+1:
            out.extend(['']*(line-previous_line-1))

        col=r['col'] or 1
        depth=max(0,(col-1)//unit)
        text=r['text']

        # A token line with no column is often an explicit continuation.
        # Its indentation is derived from the owning statement.
        is_continuation = (
            i > 0 and rows[i-1]['line'] == line-1 and
            _needs_backslash(
                rows[i-1]['last'],
                text.lstrip().split(' ',1)[0] if text.strip() else '',
                rows[i-1]['nesting']
            )
        )

        if is_continuation:
            prev_depth=max(0,((rows[i-1]['col'] or 1)-1)//unit)
            # Conventional GDScript continuation indentation.
            depth=prev_depth+2

        # If this line starts an explicit continuation, append the backslash
        # to the PREVIOUS line, not to this line.
        if i > 0 and rows[i-1]['line'] == line-1 and _needs_backslash(
                rows[i-1]['last'],
                text.lstrip().split(' ',1)[0] if text.strip() else '',
                rows[i-1]['nesting']):
            if out and not out[-1].rstrip().endswith('\\'):
                out[-1]=out[-1].rstrip()+' \\'

        out.append('\t'*depth+text)
        previous_line=line

    return '\n'.join(out)+'\n'

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

def process_one(mode,path,stdout=False):
    if mode=='hexdump':
        # Hexdump the decoded GDSC payload, not the compressed GDSC container.
        _version, _header_field, raw = decode_payload(Path(path).read_bytes())
        return hexdump(raw)
    decoded=decode_file(path)
    if mode=='dcmp':return reconstruct(decoded[1],decoded[2],decoded[3],decoded[5])
    if mode=='consts':return const_report(path,decoded)
    if mode=='disasm':return disasm_report(path,decoded)
    if mode=='audit':return audit_report(path,decoded)
    raise ValueError(mode)

def main():
    ap=argparse.ArgumentParser(prog='OpenGDS.py')
    ap.add_argument('mode',choices=['dcmp','hexdump','audit','consts','disasm'])
    ap.add_argument('path')
    ap.add_argument('-o','--output',help='output file for single-file input, or output root for folder input')
    ap.add_argument('--outdir',help='output root for folder input')
    ap.add_argument('--continue-on-error',action='store_true',help='continue recursive processing after a bad GDC')
    args=ap.parse_args()
    p=Path(args.path)
    files=iter_files(p)
    if not files:
        raise SystemExit(f'No .gdc files found: {p}')
    is_folder=p.is_dir()
    if not is_folder:
        try:result=process_one(args.mode,p)
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
            result=process_one(args.mode,f)
            if args.mode=='consts':
                summaries.append(const_summary(f, decode_file(f)))
            elif args.mode=='audit':
                summaries.append(audit_summary(f, decode_file(f)))
            rel=f.resolve().relative_to(base)
            ext='.gd' if args.mode=='dcmp' else ('.hex' if args.mode=='hexdump' else f'.{args.mode}.txt')
            dest=root/rel
            dest=dest.with_suffix(ext)
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
        for s in summaries:
            print(s)
        print(f'Summary: {summary_path}')
    print(f'Processed: {ok}  Failed: {bad}  Output directory: {root}')
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
