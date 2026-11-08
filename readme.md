# OpenGDS 1.0.2 — release

**GDSC inspector, decompiler, tokenizer-buffer compiler, and static debugger for Godot 4.x**  
**Current format target:** GDSC v101  
**Version command:** `python OpenGDS.py --version`

---

## 1. What OpenGDS does

OpenGDS is a standalone Python command-line utility for examining Godot's compiled GDScript token-buffer files (`.gdc`). It can:

- inspect and validate GDSC container metadata;
- reconstruct readable `.gd` source from compiled token data;
- tokenize and serialize `.gd` text into a GDSC v101 token buffer;
- display decoded payload bytes, constants, and token streams;
- run heuristic string/URL/security-oriented scans;
- perform static structural checks and map source-line breakpoints to token indices;
- compare two GDSC files at both the compressed-container and decoded-payload levels.

OpenGDS is an independent file-format tool. It does **not** launch Godot, load a game, run scripts, or provide a live runtime debugger.

## 2. Important scope and compatibility

OpenGDS currently targets **GDSC bytecode version 101**. The version field is checked before interpreting the payload; unsupported versions are rejected rather than silently decoded as v101.

The compiler (`comp`) is a Python implementation of the GDScript tokenizer-buffer serialization path. It creates the GDSC token container; it does **not** run Godot's complete GDScript parser, static type checker, project importer, linker, or runtime. Consequently:

- successful `comp` output means tokenization, serialization, and OpenGDS structural validation succeeded;
- it does not prove that every generated script passes Godot's parser or type checker;
- it does not prove that a game accepts, loads, or executes the generated script correctly;
- validate edited scripts with the target Godot version and test them in the target project/game.

`dcmp` reconstructs source from information retained in the compiled token buffer. Comments and some original formatting are not stored in GDSC and therefore cannot always be recovered exactly. Reconstructed source is intended to preserve the token stream and its positional information, not the original editor formatting byte-for-byte.

## 3. Requirements

- Python **3.10 or later** (the release regression suite was run with Python 3.13.5).
- For reading compressed GDSC files: the `zstd` command-line executable must be available on `PATH`.
- For compressed compilation: a loadable `libzstd` shared library must be discoverable by Python's `ctypes.util.find_library('zstd')`.
- For uncompressed compilation (`--no-compress`), the Zstandard compression library is not needed. Reading a raw/uncompressed GDSC file does not require the `zstd` executable.

### Termux / Android

```bash
pkg update
pkg install python zstd
```

Confirm the tools are visible:

```bash
python --version
zstd --version
python OpenGDS.py --version
```

The `zstd` package should provide the CLI and the shared library required for compressed output on the supported Termux setup. If Python cannot locate `libzstd`, install/repair the matching system Zstandard package and check the library search path.

## 4. Installation and version

Place `OpenGDS.py` in a working directory and invoke it with Python:

```bash
python OpenGDS.py --version
```

Expected output:

```text
OpenGDS 1.0.2 - release
```

To see the complete command-line options:

```bash
python OpenGDS.py --help
```

## 5. Command reference

General syntax:

```text
python OpenGDS.py <mode> <file-or-folder> [options]
```

The analysis modes accept either one `.gdc` file or a directory. Directory scans are recursive. `comp` accepts `.gd` source files or a directory containing them. `diff` accepts exactly two individual `.gdc` files.

### 5.1 `info` — inspect and validate a GDC

```bash
python OpenGDS.py info script.gdc
python OpenGDS.py info assets/
python OpenGDS.py info script.gdc -o script.info.txt
```

Reports the GDSC signature, bytecode version, file/header/payload sizes, compression mode, declared decoded size, SHA-256, decoded identifiers/constants/maps/token counts, and a structural decode validation result.

For a directory, output files are written under `assets.info/` by default, with a `.info.txt` extension.

### 5.2 `dcmp` — decompile/reconstruct GDScript

```bash
python OpenGDS.py dcmp script.gdc
python OpenGDS.py dcmp assets/
python OpenGDS.py dcmp script.gdc -o script.gd
python OpenGDS.py dcmp assets/ --outdir reconstructed/
```

Reconstructs readable GDScript from the decoded identifiers, constants, token stream, line map, and column map.

For a directory, output files are written under `assets.dcmp/` by default and retain the input's relative directory structure. The output extension is `.gd`.

**Formatting note:** compiled token buffers do not preserve comments and all original whitespace choices. Do not use source-file byte equality as the sole correctness criterion for a decompiled script.

### 5.3 `comp` — compile `.gd` to GDSC v101

```bash
python OpenGDS.py comp script.gd
python OpenGDS.py comp assets_gd/
python OpenGDS.py comp assets_gd/ --outdir compiled/
python OpenGDS.py comp script.gd -o script.gdc --force
```

`comp` tokenizes a GDScript source file and writes a GDSC v101 tokenizer buffer. The file is decoded and structurally validated again before it is written. Writes use a temporary file and then replace the destination.

Default output:

- one file: `script.gdc` beside `script.gd`;
- a directory: `assets_gd.comp/`, preserving relative paths.

The compiler deduplicates identifier and constant table entries, writes source-position maps, serializes token records and wraps the payload in a GDSC v101 header. Compressed output uses Zstandard level 3.

This is **not** the full Godot script compiler. It does not perform full grammar parsing, static type resolution, engine class/member checks, resource linking, or runtime checks.

### 5.4 `--no-compress` — write a raw GDSC payload

```bash
python OpenGDS.py comp script.gd --no-compress
python OpenGDS.py comp assets_gd/ --no-compress --outdir compiled_raw/
```

Writes the same GDSC v101 payload without a Zstandard frame. The header's decoded-size field is zero, which marks the payload as uncompressed. This is useful for diagnostics and isolating compression from token-data issues; it is usually larger than compressed output.

### 5.5 `hexdump` — dump decoded payload bytes

```bash
python OpenGDS.py hexdump script.gdc
python OpenGDS.py hexdump assets/
```

Produces a hexadecimal and printable-ASCII view of the **decoded payload**, not merely the compressed bytes in the outer container. Directory output is stored under `assets.hexdump/` with a `.hex` extension.

### 5.6 `consts` — list constants

```bash
python OpenGDS.py consts script.gdc
python OpenGDS.py consts assets/
```

Lists constant table entries and their decoded Python-side types/values. Directory mode also writes `SUMMARY.txt`, containing a compact per-file count of constant types.

### 5.7 `disasm` — display token stream

```bash
python OpenGDS.py disasm script.gdc
python OpenGDS.py disasm assets/
```

Displays token index, source line, column (when present), token type, token argument/reference, and reconstructed token text. Directory output is stored under `assets.disasm/` with a `.disasm.txt` extension.

### 5.8 `audit` — heuristic static string/security scan

```bash
python OpenGDS.py audit script.gdc
python OpenGDS.py audit assets/
```

Scans decoded string constants and token text for selected indicators, including:

- private-key header patterns;
- JWT-like strings;
- common API-key, secret, access-token, password, and credential assignments;
- AWS access-key and GitHub-token patterns;
- embedded HTTP/HTTPS URLs;
- references to selected dynamic/external execution APIs.

Possible secret values are redacted in the report; URLs may be printed for review. Directory mode also writes `SUMMARY.txt`.

**Audit is heuristic.** It can produce false positives and false negatives. A clean report is not proof that a script or project is secure.

### 5.9 `dbg` — native static GDSC debugger

```bash
python OpenGDS.py dbg script.gdc
python OpenGDS.py dbg assets/
python OpenGDS.py dbg script.gdc --breakpoint 42
python OpenGDS.py dbg script.gdc -b 42 -b 75 --show-tokens
python OpenGDS.py dbg script.gdc -b 42 --context 8 --show-tokens --max-tokens 500
```

The debugger works directly from the compiled token stream; it does not need the original `.gd` file or a Godot executable.

Structural checks include:

- GDSC v101 support;
- consistency of line-map and column-map token indices;
- valid token indices and positive source positions;
- line-map values matching token line values;
- identifier and constant references staying within their tables;
- monotonically increasing token line positions;
- balanced parentheses, brackets, and braces;
- detection of tokenizer `ERROR` tokens and version-control conflict markers.

A source-line breakpoint maps to the first token whose stored line equals the requested line. If no token starts on that exact line, the report marks the breakpoint unresolved and shows the nearest available previous/next token lines.

Directory reports are written under `assets.dbg/` with a `.dbg.txt` extension.

**Debugger boundary:** this is static token/structure analysis. It does not execute GDScript, pause a live process, inspect variables, step through runtime instructions, or validate semantic correctness.

### 5.10 `diff` — compare two GDC files

```bash
python OpenGDS.py diff godot.gdc opengds.gdc
python OpenGDS.py diff godot.gdc opengds.gdc -o comparison.txt
```

Compares:

- complete container bytes;
- decoded payload bytes and payload hashes;
- identifier and constant tables;
- line and column maps;
- token sequences and the first reported differences.

The report distinguishes a compression/container-only difference from a decoded token-payload difference. A `diff` command returning successfully means the comparison ran; it does **not** mean the two files are identical. Read the report's `CONTAINER BYTE-IDENTICAL` and `DECODED PAYLOAD BYTE-IDENTICAL` fields.

## 6. Options

| Option | Purpose |
|---|---|
| `--version` | Print `OpenGDS 1.0.2 - release` and exit. |
| `-h`, `--help` | Show CLI usage/options. |
| `-o`, `--output PATH` | Output file for single-file operations, or output root for directory operations. |
| `--outdir DIR` | Explicit output root for folder operations; for single-file `comp`, a destination directory. |
| `--continue-on-error` | Continue recursive processing after an individual file fails. Without it, processing stops at the first failure. |
| `--tab-size N` | Tab width used when measuring source columns during compilation; default is 4. |
| `--no-compress` | `comp` only: write an uncompressed GDSC payload. |
| `--force` | `comp` only: overwrite an existing destination file. |
| `-b`, `--breakpoint LINE` | `dbg` only: map a requested source line to a token. Repeatable. |
| `--context N` | `dbg` only: number of tokens shown before/after a resolved breakpoint; default is 4. |
| `--show-tokens` | `dbg` only: include a token listing. |
| `--max-tokens N` | `dbg` only: maximum token rows displayed when `--show-tokens` is used; default is 200. |

`--context` must be non-negative and `--max-tokens` must be at least 1.

## 7. Output directories and naming

When a directory is passed without an explicit output path, OpenGDS creates a sibling directory named `<input-folder>.<mode>`.

| Mode | Default output directory | Per-file extension |
|---|---|---|
| `info` | `<folder>.info/` | `.info.txt` |
| `dcmp` | `<folder>.dcmp/` | `.gd` |
| `hexdump` | `<folder>.hexdump/` | `.hex` |
| `consts` | `<folder>.consts/` | `.consts.txt` |
| `audit` | `<folder>.audit/` | `.audit.txt` |
| `disasm` | `<folder>.disasm/` | `.disasm.txt` |
| `dbg` | `<folder>.dbg/` | `.dbg.txt` |
| `comp` | `<folder>.comp/` | `.gdc` |

Relative subdirectories are preserved. `consts` and `audit` also create a directory-level `SUMMARY.txt`.

Use `--outdir` to keep all generated files outside the input tree. This is recommended when processing an extracted game/project asset directory.

## 8. Recommended workflows

### Inspect an asset collection

```bash
python OpenGDS.py info extracted/assets/ --outdir reports/info/
python OpenGDS.py dbg extracted/assets/ --outdir reports/dbg/
python OpenGDS.py audit extracted/assets/ --outdir reports/audit/
```

### Reconstruct, edit, and rebuild one script

```bash
python OpenGDS.py dcmp path/to/Example.gdc -o Example.gd
# Edit Example.gd with your editor.
python OpenGDS.py comp Example.gd -o rebuilt/Example.gdc
python OpenGDS.py info rebuilt/Example.gdc
python OpenGDS.py dbg rebuilt/Example.gdc --show-tokens
python OpenGDS.py diff path/to/Example.gdc rebuilt/Example.gdc
```

Then validate the rebuilt file with the exact Godot version used by the target project and test the application at runtime.

### Rebuild a complete directory tree

```bash
python OpenGDS.py dcmp extracted/assets/ --outdir work/source/
python OpenGDS.py comp work/source/ --outdir work/rebuilt/
```

Keep the original extracted assets unchanged so they remain available for comparison and rollback.

## 9. GDSC v101 container overview

The supported GDSC container begins with a 12-byte header:

| Field | Size | Meaning |
|---|---:|---|
| Signature | 4 bytes | ASCII `GDSC` |
| Bytecode version | 4 bytes | Little-endian integer; currently 101 |
| Decoded payload size | 4 bytes | Little-endian size of the token payload before compression; zero indicates raw/uncompressed payload |

When the decoded-size field is non-zero, the stored payload is a Zstandard frame. When it is zero, the remaining bytes are the raw payload.

The decoded payload stores counts and tables for identifiers, constants, source line/column maps, and token records. OpenGDS validates table references and selected structural relationships before reporting success.

This summary is intentionally format-level documentation; it is not a replacement for the Godot engine source or a complete formal GDSC specification.

## 10. Version 1.0.2 release notes

- Added `--version`, reporting `OpenGDS 1.0.2 - release`.
- Fixed raw-string scanning so ordinary characters after a backslash are preserved. For example, `r"\\n"` retains a literal backslash followed by `n`.
- Fixed numeric lookahead at end-of-input by using tuple membership for one-character checks. This prevents empty-string lookahead from being treated as a match and correctly handles decimal integers ending in zero, including `10`, `100`, and `1200`.
- Retained the GDSC v101 inspector, reconstruction, compiler, static debugger, audit, disassembler, and diff functionality.

## 11. Full-corpus regression results for this release

Test input: supplied `compiled_scripts.zip`, extracted read-only.  
Archive SHA-256: `f94abece8e03cd0d1e2dc2e7e4b76263cd2aff1b49ba1eb6120c6cb2cd8fdb63`  
Input files: **1,130 GDC files**  
OpenGDS.py SHA-256: `67cffa59b037009c2fa228d48bad12c59deebe21d037a115911f254c2d3ec525`

| Test | Result |
|---|---:|
| `info` | 1,130 / 1,130 passed |
| `dcmp` | 1,130 / 1,130 passed |
| `hexdump` | 1,130 / 1,130 passed |
| `consts` | 1,130 / 1,130 passed |
| `audit` | 1,130 / 1,130 passed |
| `disasm` | 1,130 / 1,130 passed |
| `dbg` | 1,130 / 1,130 passed; 0 diagnostics in every report |
| `comp` after decompilation | 1,130 / 1,130 compiled |
| decoded payload after `dcmp → comp` | **1,130 / 1,130 byte-identical** |
| complete GDSC container after `dcmp → comp` | 1,129 / 1,130 byte-identical |
| `diff` comparison routine | 1,130 / 1,130 comparisons completed |
| current-source Lexer regression checks | 16 / 16 passed |
| `--version` | passed; expected output and exit code 0 |
| Python syntax compilation | passed (`python -m py_compile OpenGDS.py`) |

The single full-container difference is:

```text
assets/Managers/NakamaManagement/NakamaManager.gdc
```

Its decoded payload is byte-for-byte identical to the original. The difference is in the Zstandard/container representation only; it does not represent a difference in identifiers, constants, source maps, or token bytes.

The `diff` command was also smoke-tested through the CLI for both an identical file pair and the compression-only-different NakamaManager pair. The comparison function completed for all 1,130 original/rebuilt pairs.

**What this corpus result establishes:** successful processing of the supplied v101 corpus by the listed OpenGDS modes, full decoded-payload identity after reconstructing/recompiling those unchanged scripts, and successful static structural checks on every original file.

**What it does not establish:** Godot parser/type-checker acceptance of arbitrary newly edited GDScript, game runtime compatibility, or correctness for GDSC versions and syntax features outside the tested corpus. The regression compiles unchanged reconstructed sources; it is not a full Godot runtime test.

## 12. Troubleshooting

### `zstd is required to decode compressed GDSC files`

Install the Zstandard command-line tool and ensure `zstd` is on `PATH`. Confirm with `zstd --version`.

### `libzstd not found`

The compiler cannot locate the shared Zstandard library. Install the system Zstandard development/runtime package supported by your platform and ensure the library is discoverable by Python.

### `unsupported GDSC version`

The file's bytecode version is not v101. Do not force it through the v101 decoder. Compatibility must be added deliberately for the corresponding format/tokenizer version.

### `Output exists`

Choose a different destination or pass `--force` to `comp` when intentionally replacing the existing file.

### `No .gdc files found` / `No .gd files found`

Check that the input path is correct and contains files with the required extension. `comp` takes `.gd`; the analysis modes take `.gdc`.

### OpenGDS succeeds but Godot rejects a rebuilt script

OpenGDS's compiler does not run Godot's full parser/type checker. Inspect the rebuilt file with `dbg`, compare it against the original using `diff`, then validate it with the target Godot editor/export/runtime. A zero-error `dbg` report means structural checks passed; it is not proof of semantic validity.

## 13. Responsible use

Only inspect or modify game/app files that you own or are authorized to analyze. Keep backups of original APK/PCK/project assets, preserve resource-path and remap relationships, and test changes in an isolated copy before distributing a modified build.
