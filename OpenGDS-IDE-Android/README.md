# OpenGDS IDE 1.0.3

**Developer:** 0xbytecode  
**Package:** `com.ABDO10DZ.OpenGDS`  
**Version:** 1.0.3

OpenGDS IDE is an Android Godot/GDScript workbench for inspecting GDSC v101 bytecode, decompiling `.gdc` files to editable `.gd`, compiling edited scripts, rebuilding supported Godot PCK archives, and exporting rebuilt APK archive(s).

## Editor and file browser

- The Editor can start with no APK or imported project. Its rounded **+** menu creates a new GDScript, imports multiple `.gd` / `.gdc` files, imports a project folder, or opens an APK directly into an editable workspace.
- When no workspace is open, the Editor displays up to 12 recent projects. Reopen an entry, remove only its history record, or permanently delete that workspace and its full stored contents. Deletion is protected by a confirmation dialog.
- Standalone script workspaces use the same editor, GDSC v101 decompiler/compiler, save, batch operations, and folder export as APK-backed workspaces. APK repacking remains available only when an original APK baseline exists.
- New scripts are created as editable `.gd` files and can be compiled immediately to `.gdc`.
- Portrait phones use a full-width Files / Editor switch instead of squeezing the editor into a narrow split pane. Wider screens retain a two-pane layout. The editor can expand to fill the available editor area and collapse back to the file browser.
- The project browser is a folder tree. By default it shows `.gdc` and `.gd` files, including unsupported GDC files (clearly marked); **Show all files** exposes the rest of the workspace.
- Both the project filter and in-file search support literal matching and regular expressions. In-file **Prev / Next** controls jump to each match, select the active occurrence, and scroll it into view. Invalid patterns are reported without crashing the editor.
- The code editor derives gutter line numbers and search navigation from Compose's actual text layout, including wrapped visual rows. This avoids estimating source lines from scroll-pixel offsets and keeps the gutter aligned while scrolling or moving the cursor. The UI is locked to left-to-right English layout on Arabic and other RTL system locales.
- The GDScript editor highlights comments, strings (including triple-quoted strings), annotations, language keywords, literals, common built-in types/constants/functions, and numeric values. Search matches are highlighted independently.
- The editor uses the platform text-field editing behavior for selection, cursor movement, copy, paste, and undo. Syntax highlighting remains enabled for large files; the lexer scans source linearly and does not change source offsets or editor contents.
- Valid GDSC v101 files remain read-only until decompiled. Unsupported or invalid `.gdc` files remain visible for inspection/export and are clearly marked as not supported for decompilation.
- Editing and compiling a `.gd` saves the edited source before producing its `.gdc` output. Replacing an imported file or generated output is explicitly controlled by **Replace existing .gd/.gdc outputs** in Settings. Existing files are backed up as `.bak` before replacement.

## GDScript and GDSC v101

- The upstream compiler implementation is preserved. Its decoded output is regression-tested against the supplied 1,130-file Godot-produced corpus; the native `dbg` analyzer adds token-reference, source-map, source-line, and delimiter checks. A v101 header alone does not prove semantic acceptance by the target game parser; test changed scripts in the matching engine when possible.
- Inspect GDSC v101 metadata, audit findings, constants, token disassembly, and decoded-payload hex reports.
- Run the native **Debug GDC (static)** analyzer: validate token references, source-position maps, line ordering, and delimiter balance; resolve source-line breakpoints to token indices and inspect nearby tokens. It does not launch Godot.
- Decompile one or all supported GDC files and compile one or all GDScript files.
- Import multiple standalone `.gd` / `.gdc` files directly from the Editor, with no APK requirement.
- Repack automatically compiles workspace `.gd` files with overwrite enabled for the repack operation, then rebuilds all supported extracted PCKs.
- Chaquopy uses Python 3.11 and the bundled backend `OpenGDS.py` with `zstandard==0.15.2`.

## Godot PCK workflow

- Detect and extract standalone PCK v2–v4 files found in APK ZIP entries (for example, `assets/*.pck`).
- Preserve PCK format and engine version fields during reconstruction.
- Verify MD5 checksums and enforce path/size limits on extraction.
- A PCK with encrypted, delta, sparse, invalid, or otherwise skipped entries is marked non-rebuildable. APK repacking also stops if any `.pck` archive was not mapped successfully, preventing silent loss of resources.
- PCK data appended to native libraries/executables, encrypted Godot packages, and non-standard bundle layouts are not rebuilt by this version.

## APK repacking

- When an APK is opened, its original archive is retained as the repack baseline. Installed split apps retain the base APK and each split APK separately.
- Repack runs the sequence: save editor buffer → compile `.gd` → assemble generated Smali/DEX trees (when present) → rebuild extracted PCK archives → reconstruct APK ZIP archive(s) using the edited workspace files.
- Choose a default output folder in **Settings → APK repacking**. Single-APK projects export `app_name_repacked.apk`. Split APK projects export one `app_name_repacked.apks` ZIP collection containing `base.apk`, `split_1.apk`, `split_2.apk`, etc. under their original filenames, plus `META-INF/opengds-apk-set.json` with SHA-256 checksums. Enable **Always output unsigned APKs** to explicitly skip signing; a split set is named `app_name_repacked_unsigned.apks`. Otherwise OpenGDS signs every part with the same key. Any key-loading, signing, or signature-verification failure aborts export with the underlying error in Logs; it does not silently produce an unsigned file.
- Original APK entries are no longer filtered by OpenGDS workspace-only filename rules (for example `.tmp`, `.bak`, or reserved-looking folder names); only obsolete signature records are removed before re-signing. Workspace-generated backup/temp files are still excluded from new additions.
- Before export, OpenGDS verifies every retained and replaced archive entry by size and CRC. Logs report each source/output APK size, entry counts, uncompressed and compressed payload sizes, and GDC/PCK/native-library counts. This makes missing split files, PCKs, or other assets visible instead of silently producing an unchecked archive.
- **APK export:** The Editor has a separate **Export installable APK(s)** action in its three-dot menu; it is not the folder export. OpenGDS IDE verifies rebuilt archive contents before exporting. The default signing mode uses a persistent local Android Keystore identity; the optional unsigned mode skips signing. Unsigned files must be signed before installation. Split packages are bundled into one `.apks` collection. Extract the contained APKs and install the complete compatible set together, not just the base file. The OpenGDS `.apks` is a ZIP collection, not a Bundletool APK-set archive with `toc.pb`, so it is not directly installable by Android. The local export key differs from the original developer key, so signed exports cannot update the original installation.
- **Editor layout:** The code editor can expand to fill the workspace content area and collapse back to the file/project layout. Switching to a different file resets its text-field state immediately so a newly decompiled `.gd` buffer is shown without stale editor content.
- **GDScript editing:** The editor provides syntax coloring for large and normal-sized files, search highlighting, wrap-aware line numbers, standard text-field cursor/selection/clipboard behavior, and delta-based auto-pair insertion/skip-over/paired-backspace for delimiters and quotes.

- Folder-only imports do not contain an original APK baseline and therefore cannot use APK repacking.

## Other functionality

- Installed-app and APK discovery with Godot-first filtering and optional non-Godot visibility.
- Import APKs, APK folders, and project folders through Android's Storage Access Framework.
- Smali / DEX disassembly and assembly for imported non-Godot APK workspaces.
- Dark, light, and system themes; runtime logs; transactional backend updates. The visual layout remains LTR regardless of the Android system language or RTL setting.
- Explicit **Close project** saves the current editor buffer but retains the workspace. OpenGDS restores the last active workspace and selected file after process termination, and stores an atomic JSON editor-draft journal for unsaved-text recovery. Source saves use a same-directory temporary file, fsync, and replacement with a `.bak` copy.
- Long-running operations display progress and offer cancellation where the operation supports safe cancellation.
- Settings can reset `OpenGDS.py` to the bundled core, display project, separately imported APK, cache, backend, and other private-data usage; clean temporary/cache files; delete the imported APK library; or permanently delete all saved workspaces after an explicit confirmation. Individual workspace deletion is also available in Recent Projects. The editor action menu offers compile/decompile batches, PCK rebuild, APK/project export, DEX/Smali tools, and sharing of the current source through Android Sharesheet. The GitHub core is checked once per process after validated internet becomes available; updates are SHA-256 compared and compatibility-validated, then require user approval.

## Build requirements

- JDK 21 (JDK 17+ toolchain compatibility).
- Android SDK Platform 36 and Android Build Tools 36.0.0.
- Gradle 8.13, Android Gradle Plugin 8.13.2, Kotlin 2.2.10, Chaquopy 17.2.0.
- Python 3.11 for the build host and Chaquopy's Android wheel index.

The Gradle wrapper properties are included. The wrapper launcher/JAR are intentionally not bundled in this source archive. For the Termux Studio setup used during development, from the project root:

```bash
studio load "$PWD"
"$HOME/.studio/gradle/gradle-8.13/bin/gradle" \
  -p "$PWD" --no-daemon --max-workers=2 :app:assembleRelease
```

The GitHub Actions workflow builds a debug APK and an unsigned Android release APK at `app/build/outputs/apk/release/app-release-unsigned.apk`. This release build intentionally has no signing configuration. Invoke the Gradle binary directly; the `studio gradle` helper may apply its debug-keystore signing convenience to Release builds.

## Verification notes for this source archive

- Python backend and Android bridge pass `py_compile` syntax checks. Representative GDScript samples pass compile → decode → source reconstruction tests in both raw and zstd-compressed GDSC forms. Truncated token data and out-of-range line-map entries are rejected.
- `AndroidManifest.xml` parses successfully.
- Kotlin sources were parser-checked with the standalone Kotlin compiler; no Kotlin parser errors were reported. Full type-checking requires the Android/Compose dependency classpath.
- A full Gradle build, real Android Keystore signing, APK installation, and split-set installation were not run in this authoring environment because the Android SDK, Gradle executable, and Gradle wrapper JAR are unavailable. Signing failures now surface their original exception in Logs instead of triggering an unsigned fallback.
- The original 160 MiB test APK and failing 20 MiB repacked APK were not included. The new on-device APK audit is intended to reveal whether the size difference comes from missing archive entries, ZIP compression, or separate APK parts; the exact failure is still unverified until those outputs are tested on a device.

## Project layout

```text
OpenGDS/
├── app/
│   ├── src/main/assets/OpenGDS.py
│   ├── src/main/python/opengds_bridge.py
│   ├── src/main/java/com/ABDO10DZ/OpenGDS/
│   │   ├── core/       # APK/PCK reconstruction, backend, DEX/Smali, workspace
│   │   ├── data/       # app state and project operations
│   │   └── ui/         # Compose UI, file tree, editor, syntax highlighting
│   └── build.gradle.kts
├── gradle/wrapper/gradle-wrapper.properties
├── build.gradle.kts
└── settings.gradle.kts
```

## Validation boundary

The editor export pipeline compiles GDScript, rebuilds supported embedded PCK data, reconstructs and byte-audits APK archives, then signs each APK locally unless unsigned output is selected. APK signature verification is performed for signed exports using the base package minSdk across each split, because split manifests may omit their own `uses-sdk` element. Nested signer errors are included in failure diagnostics. Split packages are emitted as one OpenGDS `.apks` ZIP collection with original inner APK names; extract and install the complete compatible set together. Real-device testing is still required for PCK variants, large APKs, split APK installation, and target-app compatibility.


## Native GDSC debugger

The command-line backend includes an engine-independent structural debugger:

```sh
python OpenGDS.py dbg path/to/script.gdc
python OpenGDS.py dbg path/to/script.gdc --breakpoint 42
python OpenGDS.py dbg path/to/script.gdc --breakpoint 42 --show-tokens --max-tokens 400
python OpenGDS.py diff godot_compiled.gdc opengds_compiled.gdc
```

The upstream compiler regression runner can be used with a real corpus (no sample game files are bundled):

```sh
python tests/run_corpus_regression.py /path/to/extracted/assets
python -m unittest discover -s tests -v
```

`dbg` validates the GDSC v101 container and token structure, checks identifier/constant references, source maps, token line order, and matching parentheses/brackets/braces. A requested breakpoint is mapped to the first token starting on that source line, with a token context window. Folder input is recursive.

**Scope:** this is static bytecode/token analysis. GDSC v101 stores a tokenizer stream; it does not contain a directly executable instruction stream. The current debugger does not execute GDScript, pause a live game, evaluate expressions, or inspect live variables. Runtime debugging requires a compatible interpreter or engine-side debugging protocol and is a later milestone.
