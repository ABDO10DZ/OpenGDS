# OpenGDS - IDE 1.0.2

**Developer:** 0xbytecode

A desktop workspace for GDScript and OpenGDS GDSC v101 tooling. It combines the OpenGDS Python core with Godot's own CLI, GDScript Language Server (LSP), Debug Adapter Protocol (DAP), and project/package utilities.

> **Scope statement:** this is a feature-rich development build, not a claim of complete parity with the Godot Editor or VS Code. The bundled OpenGDS compiler serializes a GDScript token buffer into GDSC v101; it is not a replacement for Godot's full parser, semantic analyzer, type checker, importer, or project exporter. Use Godot validation and the engine itself for engine-level correctness.

## Get started on Windows

1. Download and extract the complete ZIP into a normal writable folder. Do not run it from the ZIP preview.
2. Install Python 3.10 or newer.
3. Double-click **`launch_windows.bat`**.
4. On first run it creates `.venv`, installs PySide6 and the portable `zstandard` wheel, verifies Qt and Zstandard imports, and launches the IDE. A network connection is needed for the first dependency installation.
5. Later, double-click `launch_windows.bat` again.

The dependency set includes the portable `zstandard` Python wheel, avoiding the separate `libzstd.dll` dependency that caused compressed compilation to fail in some Windows setups. The bundled core can also use a system `libzstd` (or, as a final compatibility fallback, the `zstd` CLI) when used outside the standard launcher.

To install without opening the IDE, run `setup_windows.bat` or `launch_windows.bat --setup-only`.

**Avoid `python main.py` with your system Python on a fresh extraction.** That interpreter may not have PySide6 or Zstandard. After setup, use `.venv\Scripts\python.exe main.py` or the launcher.

## Linux and macOS

```bash
chmod +x launch_linux.sh
./launch_linux.sh
```

The launcher creates `.venv`, installs requirements, checks PySide6/Zstandard, then starts the IDE. Some Linux distributions may require OS-level Qt platform libraries. On macOS, configure the executable inside the Godot `.app` bundle, usually `Godot.app/Contents/MacOS/Godot`.

## Manual setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

## Project/workspace handling

The File menu can open:

- `file.ogds` or another `.ogds` descriptor;
- a Godot `project.godot` file;
- any directory, even when it contains neither descriptor.

When opening a plain directory, OpenGDS creates an in-memory workspace; it does not add files until you explicitly create/save a descriptor. Use **File → Create / Save OpenGDS Workspace (.ogds)** to write one. See [`docs/OGDS_FORMAT.md`](docs/OGDS_FORMAT.md) for the format.

### `.ogds` versus `project.godot`

`.ogds` is OpenGDS - IDE metadata: workspace root, compiler defaults, output paths, Godot executable, debug preferences and editor preferences. It can make a directory a first-class OpenGDS workspace without a Godot project. It **does not replace** `project.godot` for the Godot engine. Godot commands that require a project (`--path`, editor, project run, import, export and runtime debugging) still require a valid `project.godot` file. OpenGDS compilation, decompilation, inspection and static GDSC analysis do not require it.

## GDScript and GDSC workflows

OpenGDS menu and explorer context actions expose the bundled core:

| Action | Input | Result |
|---|---|---|
| Compile | `.gd` or a folder/project | GDSC v101 `.gdc` |
| Decompile | `.gdc` or a folder/project | reconstructed `.gd` source |
| Info / validate | `.gdc` | header, hash, compression, counts and supported-structure validation |
| Static debug | `.gdc` or `.gd` | token-context report and source-line breakpoint mapping |
| Audit | `.gdc` or folder | heuristic secret, URL and sensitive-API findings |
| Disassemble | `.gdc` or folder | token stream report |
| Constants | `.gdc` or folder | constant pool report |
| Hex dump | `.gdc` or folder | decoded payload hexadecimal report |
| Diff | two `.gdc` files | structural/token comparison |
| Advanced CLI | any core command/arguments | direct access to the bundled CLI options |

Double-clicking a `.gdc` file runs **OpenGDS info** automatically. The report tab has Decompile, Static Debug, Runtime Debug, Audit, Disassemble, Constants, Hex Dump and Compare actions. A `.gdc` is always treated as binary data; it is never decoded as editor UTF-8 text.

### Entire-project compile/decompile

- **Compile entire project** recursively scans `.gd` source and writes `.gdc` into the configured output directory (default `.opengds/compiled`), preserving relative folders.
- **Decompile all project GDSC** collects `.gdc` under the project and the configured compiled-output directory, including an output directory outside the project, and reconstructs `.gd` under the selected destination.
- Existing output files are skipped unless overwrite is enabled. Continue-on-error is configurable. Every file result is included in the operation summary/log.
- IDE debug-cache and decompile working areas are excluded from source scans to avoid accidental recursion.

The `OpenGDS.py` CLI currently exposes `info`, `comp`, `dcmp`, `hexdump`, `audit`, `consts`, `disasm`, `dbg`, and `diff`. OpenGDS is currently targeted at **GDSC v101**. The upstream compiler performs tokenizer and token-buffer serialization; it does not implement the complete Godot compiler or semantic checker. Decompiled output cannot restore comments that were discarded from bytecode or guarantee original formatting. See the upstream [OpenGDS project](https://github.com/ABDO10DZ/OpenGDS) for core behavior and format scope.

## Godot integration

Configure a Godot editor executable in **Tools → Settings → General**, or let the IDE search `PATH` for `godot` / `godot4`.

Available integration includes:

- Launch Godot Editor with the workspace and configured LSP/DAP ports.
- Godot LSP for server completion and diagnostics (default `127.0.0.1:6005`).
- Godot DAP for breakpoints, continue/pause, step over/into/out, call stack, scopes/variables and watch expressions (default `127.0.0.1:6006`).
- Godot local runtime run/debug; source breakpoints are forwarded with Godot's `--breakpoints=source::line` syntax.
- Godot `--check-only` parse validation for current or all `.gd` files. It is a parse check, not an OpenGDS `.gdc` compiler.
- Headless project import (`--import`), PCK export (`--export-pack`), debug build (`--export-debug`) and release build (`--export-release`), using existing export presets. These are Godot engine import/export operations; OpenGDS `comp` remains the operation that writes the separate GDSC v101 `.gdc` container.
- **Custom Godot CLI arguments** for additional engine options (conversion, doctool, benchmarking, custom headless jobs, etc.). The command is launched without a shell.
- OpenGDS core runtime debug with `--godot`, and lifecycle breakpoints with `--interrupt`. This is separate from LSP/DAP. When selecting a `.gd`, the IDE compiles an uncompressed temporary `.gdc` and passes the matching `res://` source mapping to OpenGDS. The engine owns runtime execution and stepping.

LSP/DAP require the project to be open in Godot Editor and the corresponding editor servers enabled. OpenGDS core runtime debugger also requires `project.godot`. A plain workspace can still use the OpenGDS compiler/decompiler/inspection tools.

Godot's CLI options are version/build dependent. `--check-only` is documented for use with `--script`; `--import`, export flags, `--debug`, and breakpoints are documented in the official [Godot command-line reference](https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html). The IDE's **Custom Godot CLI Arguments** entry is the escape hatch for flags not represented by a dedicated button.

## Packages and archives

- **PCK:** inspect and extract Godot PCK v2-v4, including standalone `.pck` and embedded PCK data appended to executables. Embedded scanning is not restricted to `.exe` suffixes. The parser validates directory metadata and entry bounds before extraction.
- **ZIP / APK:** list and extract ZIP-compatible packages, including APK containers.
- **Project snapshot:** make a ZIP of a project while excluding Git, Godot and IDE caches by default.

Extraction is path-traversal protected, verifies PCK entry MD5 values, uses temporary files before replacement, and enforces per-file and total extraction limits. Encrypted PCK directories cannot be listed without the authorized key; encrypted, removal and delta entries are not extracted. APK signing, rebuilding, decryption and Android package analysis are not implemented. This is a package reader/extractor, not a full Android reverse-engineering toolkit.

## Settings

Settings are divided into General, Editor, Language Server, Debugging, Compiler and Advanced:

- theme, font, font size, tab width, autosave and interval;
- editor auto-pairs, auto-indent, completion, line numbers, breakpoint gutter and word wrap;
- OpenGDS core path and Godot executable path;
- LSP/DAP endpoints, auto-connect, remote debugger port;
- legacy runtime debugger headless/interrupt/frame callbacks, scene, source override, extra Godot args, dry-run;
- static debug context/token limits;
- GDSC compression, tokenizer tab size, overwrite, continue-on-error, output directory and optional Godot validation;
- hidden-file visibility, command timeout and log viewer record limit.

## Explorer colors and file actions

- `.gd` source: green
- `.gdc` compiled GDSC: red
- `project.godot`, `.ogds`, `.godot` metadata/cache: blue

Double-click folders to expand their tree. Right-click files/folders for create, rename, delete, reveal/copy path, compile/decompile, inspect and debugger actions.

## Detailed logging

The bottom log view supports category filtering, text search and a clear-view action. Clear-view does not delete saved logs. Logs are under `~/.opengds-studio/logs/` by default; set `OPENGDS_LOG_DIR` to override it.

- `studio.log`: GUI operations, Python/Qt errors, OpenGDS subprocess output, Godot stdout/stderr, diagnostics, LSP and DAP.
- `core.log`: raw OpenGDS core records/tracebacks. Newly appended core records are merged into the GUI log stream after commands finish.

The log files rotate at 8 MiB with up to eight backups. Categories use distinct colors: CORE, GUI, GODOT_ENGINE, GODOT_ENGINE_ERR, GODOT_DEBUG, GDSCRIPT, GDSC, PYTHON, LOGIC, LSP, DAP, BUILD, FILE, ARCHIVE and SYSTEM.

Godot output is captured when the IDE launches the engine/editor; DAP output events are recorded when attached. An unrelated engine process not launched by or connected to this IDE cannot be monitored.

## Verification

Run from the extracted project root:

```bash
python -m py_compile *.py tests/*.py
python -m unittest discover -s tests -v
bash -n launch_linux.sh
```

The included tests cover compiler/decompiler round trips, info reports, core error logs, zstandard adapter behavior, project discovery/descriptors, batch compile/decompile, LSP/DAP framing, PCK/ZIP safety and helper command construction. This build environment does not have PySide6 or a Godot executable, so an actual GUI launch, Windows launcher run, live Godot import/export, and real LSP/DAP/runtime-debug session still need a desktop smoke test.

## Known compatibility boundaries

- GDSC support is v101; other bytecode versions and encrypted `.gde` scripts are not supported by this bundled core.
- OpenGDS compilation is not Godot's full parser/type checker. Validate `.gd` source with Godot as a separate step.
- Decompilation reconstructs tokenized source; comments and formatting may be lost.
- Encrypted PCK directories, encrypted PCK entries, delta/removal patches, APK signature manipulation and package decryption are not supported.
- Godot integration depends on the installed engine version and export templates/presets. A configured executable does not guarantee a target export template exists.
- No local runtime smoke test was possible in the packaging environment.
