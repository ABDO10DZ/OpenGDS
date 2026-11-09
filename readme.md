# OpenGDS 1.0.2 — release

**GDSC inspector, decompiler, tokenizer-buffer compiler, static debugger, and Godot-backed runtime debugger for Godot 4.x**  
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
- compare two GDSC files at both the compressed-container and decoded-payload levels;
- launch a real Godot project with script breakpoints derived directly from GDSC token line data;
- automatically interrupt startup lifecycle callbacks (`_static_init`, `_init`, `_enter_tree`, `_ready`) and hand execution to Godot's local debugger.

OpenGDS remains an independent file-format tool for inspection and compilation. Its runtime-debug mode delegates execution, stepping, stack inspection, and variable inspection to the supplied Godot editor/debug executable; OpenGDS does not implement a replacement GDScript virtual machine.

## 2. Important scope and compatibility

OpenGDS currently targets **GDSC bytecode version 101**. The version field is checked before interpreting the payload; unsupported versions are rejected rather than silently decoded as v101.

The compiler (`comp`) is a Python implementation of the GDScript tokenizer-buffer serialization path. It creates the GDSC token container; it does **not** run Godot's complete GDScript parser, static type checker, project importer, linker, or runtime. Consequently:

- successful `comp` output means tokenization, serialization, and OpenGDS structural validation succeeded;
- it does not prove that every generated script passes Godot's parser or type checker;
- it does not prove that a game accepts, loads, or executes the generated script correctly;
- validate edited scripts with the target Godot version and test them in the target project/game.

`dcmp` reconstructs source from information retained in the compiled token buffer. Comments and some original formatting are not stored in GDSC and therefore cannot always be recovered exactly. Reconstructed source is intended to preserve the token stream and its positional information, not the original editor formatting byte-for-byte.

Runtime debugging is different from `comp`: it does **not** compile or decompile the target script. It starts the supplied Godot executable with `--path`, `--debug`, and `--breakpoints`, using the project’s normal ResourceLoader/remap setup. The selected project scene must actually load the target script for its breakpoints to be reached.

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

### 5.9 `dbg` — classic static debugger or Godot runtime debugger

`dbg` has two backends. The default remains the original static debugger for backward compatibility.

#### Classic static mode

```bash
python OpenGDS.py dbg script.gdc --classic
python OpenGDS.py dbg assets/ --classic
python OpenGDS.py dbg script.gdc --breakpoint 42
python OpenGDS.py dbg script.gdc -b 42 -b 75 --show-tokens
python OpenGDS.py dbg script.gdc -b 42 --context 8 --show-tokens --max-tokens 500
```

Omitting `--classic` and all runtime options also selects Classic mode. It works directly from the compiled token stream and does not need the original `.gd` file or a Godot executable.

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

#### Godot-backed runtime mode

```bash
python OpenGDS.py dbg path/to/Managers/NakamaManager.gdc \
  --godot /path/to/Godot \
  --project /path/to/your/godot/project \
  --scene res://Main.tscn
```

This launches the **real Godot engine** with its local stdout debugger. OpenGDS passes the target script’s source path and breakpoints to Godot; Godot runs the project and owns all execution state.

To stop automatically at the startup lifecycle functions:

```bash
python OpenGDS.py dbg path/to/NakamaManager.gdc \
  --interrupt \
  --godot /path/to/Godot \
  --project /path/to/your/project \
  --scene res://Main.tscn
```

`--interrupt` finds the first executable token line for each lifecycle function defined in the selected GDC, then passes those source-line breakpoints to Godot:

1. `_static_init()` — script/class initialization;
2. `_init()` — instance construction;
3. `_enter_tree()` — Node enters the SceneTree;
4. `_ready()` — Node becomes ready after its children.

Only lifecycle methods actually present in the selected GDC produce automatic breakpoints. If none are found, `--interrupt` stops with a clear error; add a manual `--breakpoint LINE` or use `--godot` without `--interrupt` for a general runtime-debug session.

Additional runtime examples:

```bash
# Manually break at source lines 42 and 75.
python OpenGDS.py dbg script.gdc --godot /path/to/Godot \
  --project /path/to/project -b 42 -b 75

# Use a non-default scene and run without a window.
python OpenGDS.py dbg script.gdc --interrupt --godot /path/to/Godot \
  --project /path/to/project --scene res://scenes/test.tscn --headless

# Inspect the generated launch command without starting Godot.
python OpenGDS.py dbg script.gdc --interrupt --godot /path/to/Godot \
  --project /path/to/project --dry-run

# Also include recurring/frame and other lifecycle callbacks.
python OpenGDS.py dbg script.gdc --interrupt --include-frame-callbacks \
  --godot /path/to/Godot --project /path/to/project
```

Runtime options:

| Option | Purpose |
|---|---|
| `--interrupt` | Add startup lifecycle breakpoints from GDSC token lines. Requires `--godot` and `--project`. |
| `--godot PATH` | Godot executable path or command available on `PATH`; enables real engine debugging. |
| `--project DIR` | Godot project root containing `project.godot`. Required for runtime mode. |
| `--source-path res://...gd` | Override the script resource path used by Godot’s breakpoint list. Useful when the `.gdc` file is outside the project or its remap/source path is non-standard. |
| `--scene res://...tscn` | Run a specific project scene; otherwise Godot uses the configured main scene. |
| `--headless` | Pass `--headless` to Godot. |
| `--breakpoint LINE` | Add one or more manual source-line breakpoints. Runtime mode verifies that each line contains a token. |
| `--include-frame-callbacks` | With `--interrupt`, also include `_process`, `_physics_process`, `_exit_tree`, `_notification`, `_input`, `_unhandled_input`, `_unhandled_key_input`, and `_draw`. Recurring callbacks can pause repeatedly. |
| `--godot-arg ARG` | Pass an additional argument to Godot; repeatable. |
| `--dry-run` | Print the Godot command and resolved breakpoints without launching the engine. |

**Project/path requirements:**

- The selected `.gdc` must be inside the supplied project directory, unless `--source-path res://...` is specified explicitly.
- By default, OpenGDS converts the project-relative `.gdc` path to its corresponding `.gd` resource path. The supplied path override can select another resource path when required by a project's export/remap layout.
- The target script must actually be loaded by the selected scene or its dependencies. Setting a breakpoint does not instantiate a resource by itself.
- Use an editor/debug Godot executable that advertises both `--debug` and `--breakpoints`. OpenGDS checks `--version` and `--help` before launch and refuses a binary that does not expose those options. Release export templates may not support the debugger.
- Godot's documented breakpoint syntax is `source::line`, with multiple entries separated by commas. OpenGDS URL-escapes spaces and commas in resource paths before passing them to Godot.

At a break, Godot’s local stdout debugger accepts commands such as `help`, `c`/`continue`, `s`/`step`, `n`/`next`, `o`/`out`, `bt` (backtrace), `lv` (locals), `mv` (members), `gv` (globals), and `p expression` (evaluate an expression). These commands are implemented by Godot, not by an OpenGDS interpreter.

**Runtime boundary:** lifecycle-line discovery is token-level and does not emulate execution. Actual callback order, stepping, locals, stack frames, signals, await/coroutines, objects, and scene lifecycle are all handled by the supplied Godot runtime. The project must load the selected script and the engine must be a debug-capable build. OpenGDS does not implement a GDScript VM or a DAP client in this release.

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
| `-b`, `--breakpoint LINE` | `dbg` only: map a requested source line to a token in Classic mode, or set a Godot breakpoint in runtime mode. Repeatable. |
| `--context N` | Classic `dbg` only: tokens shown before/after a resolved breakpoint; default is 4. |
| `--show-tokens` | Classic `dbg` only: include a token listing. |
| `--max-tokens N` | Classic `dbg` only: maximum token rows displayed when `--show-tokens` is used; default is 200. |
| `--classic` | `dbg` only: force the original static debugger. This remains the default when no runtime options are supplied. |
| `--interrupt` | `dbg` only: derive startup lifecycle breakpoints and run the real Godot debugger. |
| `--godot PATH` / `--project DIR` | `dbg` runtime only: select the Godot executable and project. |
| `--source-path`, `--scene`, `--headless`, `--godot-arg` | `dbg` runtime launch configuration. |
| `--include-frame-callbacks` | `dbg --interrupt` only: include recurring and extra lifecycle callbacks. |
| `--dry-run` | `dbg` runtime only: display the launch plan without starting Godot. |

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
python OpenGDS.py dbg extracted/assets/ --classic --outdir reports/dbg/
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
- Fixed raw-string scanning so ordinary characters after a backslash are preserved. For example, `r"\n"` retains a literal backslash followed by `n`.
- Fixed numeric lookahead at end-of-input by using tuple membership for one-character checks. This prevents empty-string lookahead from being treated as a match and correctly handles decimal integers ending in zero, including `10`, `100`, and `1200`.
- Preserved the original static debugger and made it explicit as `dbg --classic` (also remains the default for backward compatibility).
- Added `dbg --interrupt`, which derives startup lifecycle breakpoints from GDSC token positions and passes them to the real Godot runtime.
- Added `dbg --godot`, `--project`, `--source-path`, `--scene`, `--headless`, `--godot-arg`, and `--dry-run` for Godot-backed debugging.
- Added opt-in frame/extra lifecycle callbacks and validation of user-specified runtime breakpoint lines.
- Added Godot executable preflight checks for `--version`, `--debug`, and `--breakpoints` support.

## 11. Full-corpus and runtime-debugger validation

Test input: supplied `compiled_scripts.zip`, extracted to a separate test directory. The archive contains **1,130 `.gdc` files** and passed ZIP CRC validation. The original archive was not modified.

Archive SHA-256:

```text
f94abece8e03cd0d1e2dc2e7e4b76263cd2aff1b49ba1eb6120c6cb2cd8fdb63
```

OpenGDS.py SHA-256 for this build:

```text
bff4ac5b1d431cb491dc7a733396f22706bb0b7a186aeb26e92b333229981281
```

### Full corpus operations

| Test | Result |
|---|---:|
| `info` | 1,130 / 1,130 passed |
| `dcmp` | 1,130 / 1,130 passed |
| `hexdump` | 1,130 / 1,130 passed |
| `consts` | 1,130 / 1,130 passed |
| `audit` | 1,130 / 1,130 passed |
| `disasm` | 1,130 / 1,130 passed |
| `dbg --classic` | 1,130 / 1,130 passed; zero structural diagnostics in every report |
| `comp` on the 1,130 freshly decompiled sources | 1,130 / 1,130 compiled |
| decoded payload after `dcmp → comp` | **1,130 / 1,130 byte-identical** |
| complete GDSC container after `dcmp → comp` | 1,129 / 1,130 byte-identical |
| `diff` comparison function | 1,130 / 1,130 pairs passed |

The one complete-container difference is `assets/Managers/NakamaManagement/NakamaManager.gdc`. Its decoded payload is identical to the original; only the Zstandard container representation differs.

### Runtime debugger validation

| Test | Result |
|---|---:|
| Lifecycle resolver over full corpus | 1,130 / 1,130 scanned; zero resolver errors |
| Scripts with startup lifecycle methods | 614 |
| Scripts without startup lifecycle methods | 516 (expected; `--interrupt` reports that no automatic startup breakpoint is available) |
| Automatic startup breakpoints discovered | 767 |
| `--interrupt --dry-run` launch-plan tests | 614 / 614 passed |
| Runtime launcher tests with a mock Godot executable | passed |
| `--classic` legacy CLI and explicit `--classic` | passed |
| Godot debugger/lifecycle unit tests | 20 / 20 passed |
| Lexer regression tests on this build | 16 / 16 passed |
| `--version` | passed; expected output and exit code 0 |
| Python syntax compilation | passed (`python -m py_compile OpenGDS.py`) |

The mock executable verifies that OpenGDS runs the engine preflight, passes the generated `--debug`/`--breakpoints` arguments, forwards scene/headless/extra arguments, and propagates the engine exit code. It does **not** emulate GDScript execution.

**Real-engine test limitation:** no Godot executable was installed in the validation environment. Therefore, actual breakpoint hits, Godot's interactive stepping, runtime stack/locals, project-specific loading, and behavior of the selected game were **not** tested here. The runtime launcher is integrated with Godot's documented CLI flags, but must still be exercised with the user's own debug-capable Godot executable and project. The selected scene must load the target resource.

### What these results establish

- All static/file-format modes processed every supplied GDSC v101 file without an OpenGDS failure.
- The unmodified decompile/recompile path preserved all 1,130 decoded token payloads byte-for-byte.
- The `--classic` debugger remains operational.
- Lifecycle callbacks were found and mapped in all applicable files; command construction worked for every one of those files.
- Godot runtime process invocation and argument forwarding were exercised with a mock process.

### What these results do not establish

- Semantic acceptance of arbitrary edited GDScript by Godot's parser/type checker.
- Actual runtime breakpoint hits or step/locals/backtrace correctness in the target project (real Godot binary not available here).
- Compatibility with GDSC versions other than v101 or language syntax/features outside the tested files.

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

### `Godot runtime debugging requires --godot /path/to/Godot`

Pass the path to the Godot editor executable or a debug-capable engine binary. `--interrupt` also requires `--project` pointing to a directory that contains `project.godot`.

### `this Godot build does not advertise required debugger options`

Use an editor/debug executable whose `--help` output includes both `--debug` and `--breakpoints`. A release export template may omit local debugger support.

### `target is outside project` or breakpoints do not hit

Place the `.gdc` under the Godot project root or provide `--source-path res://...gd`. The selected scene must load the target script. Check the project's `.gd.remap` mapping and use the resource path Godot sees for that script.

### `no supported lifecycle methods were found in this GDC`

That script does not define one of `_static_init`, `_init`, `_enter_tree`, or `_ready`. Use a manual `--breakpoint LINE`, or start a general runtime session with `--godot` without `--interrupt`.

### Godot pauses on every frame

`--include-frame-callbacks` intentionally includes `_process` and `_physics_process`. Remove this option to restrict automatic interrupts to startup callbacks.

## 13. Responsible use

Only inspect or modify game/app files that you own or are authorized to analyze. Keep backups of original APK/PCK/project assets, preserve resource-path and remap relationships, and test changes in an isolated copy before distributing a modified build.
