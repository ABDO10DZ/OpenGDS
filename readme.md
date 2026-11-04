OpenGDS v1.0 Beta

A Python-based Godot GDScript bytecode compiler, decompiler, disassembler, inspector, and security auditor.

By ABDO10_DZ / 0xbytecode

OpenGDS is a reverse-engineering and interoperability tool for Godot's compiled GDScript binary-token format (GDSC).

It provides a bidirectional workflow for GDSC v101: inspect compiled scripts, reconstruct readable GDScript, and compile ".gd" source files back into Godot-compatible ".gdc" token containers.

Unlike tools that depend on launching the Godot editor, OpenGDS implements GDSC v101 tokenization and serialization directly in Python, using Godot's publicly available engine implementation as a reference.

OpenGDS also includes token disassembly, hexadecimal inspection, constant extraction, recursive batch processing, and static security auditing.

«Beta Release: OpenGDS has achieved byte-identical GDSC v101 round trips across a supplied corpus of 1,130 original compiled files. This result is specific to the tested corpus and the current position-preserving "dcmp" → "comp" workflow. General GDScript semantic validation and exhaustive support for every possible language construct are not claimed.»

---

🚀 Current Features

Feature| Command| Description
GDScript Reconstruction| "dcmp"| Reconstructs readable GDScript from compiled GDSC token data while preserving available line and column metadata.
GDScript Compilation| "comp"| Converts ".gd" source files into Godot-compatible GDSC v101 ".gdc" files using a native Python tokenizer and serializer.
File Information| "info"| Displays GDSC signature, bytecode version, file size, payload size, compression, SHA-256, and structural metadata.
Disassembler| "disasm"| Displays the decoded token stream, including token types, arguments, source lines, columns, and reconstructed token text.
Hex Dump| "hexdump"| Displays the hexadecimal representation of the decoded GDSC payload.
Constant Extractor| "consts"| Extracts and displays constants stored in the compiled script.
Security Auditor| "audit"| Scans decoded scripts for potential hardcoded credentials, secret patterns, URLs, and security-sensitive API references.
Recursive Batch Processing| All modes| Processes matching files recursively while preserving directory structure.
GDSC v101 Validation| "info" and other analysis modes| Validates supported GDSC v101 containers and rejects unsupported versions during decoding.
Zstandard Support| "comp" / analysis| Supports compressed and uncompressed GDSC token containers.
Python-Native Implementation| "comp"| Generates GDSC v101 containers without requiring the Godot editor executable.

---

🔄 Bidirectional GDSC Workflow

OpenGDS now supports both directions:

       GDSC v101 (.gdc)
               |
        +------+------+
        |             |
      dcmp           info
        |             |
        v             v
   GDScript (.gd)   Metadata
        |
       comp
        |
        v
   GDSC v101 (.gdc)

The compiler implements the GDSC v101 tokenizer-buffer generation and serialization process in Python.

The workflow includes:

- GDScript tokenization.
- Identifier table generation.
- Constant pool generation and deduplication.
- Variant serialization.
- Token type and argument encoding.
- Token line and column metadata.
- GDSC v101 header generation.
- Zstandard compression.

This allows OpenGDS to reconstruct, inspect, and regenerate the tested GDSC v101 files without launching Godot.

---

🧪 Validation Status

OpenGDS has been tested using a full-corpus regression workflow:

Original GDC
     |
     v
    info
     |
     v
    dcmp
     |
     v
 Fresh GD sources
     |
     v
    comp
     |
     v
 Rebuilt GDC
     |
     v
 SHA-256 comparison
     |
     v
 Original vs Rebuilt

Godot 4.7.1 corpus — Full round-trip validation

The supplied original archive contained 1,130 ".gdc" files.

All 1,130 files were inspected, decompiled, and recompiled using the updated OpenGDS implementation.

Operation| Result
Original GDC files| 1,130
"info" validations| 1,130 / 1,130
"dcmp" operations| 1,130 / 1,130
"comp" operations| 1,130 / 1,130
Exact SHA-256 matches| 1,130 / 1,130
Compilation failures| 0
Hash mismatches| 0
File-size differences| 0

Every rebuilt ".gdc" file was compared against its corresponding original using SHA-256.

All 1,130 rebuilt files produced identical hashes and file sizes.

No Godot editor executable was used during this test.

Important distinction: Original source archives

Two different source sets were tested.

The older supplied ".gd" archive was compiled successfully:

Compilation:       1,130 / 1,130
Exact SHA-256:        28 / 1,130

The older decompiler output did not preserve all token-position metadata required for byte-identical reconstruction.

The updated "dcmp" implementation preserves the required metadata:

Fresh dcmp output:  1,130 files
Compilation:        1,130 files
Exact SHA-256:      1,130 / 1,130

This distinction is important: "comp" cannot recover metadata that is absent from an arbitrary input ".gd" file.

Godot 4.6.2 corpus

The previously supplied corpus contained 693 ".gdc" files.

A representative 20-file validation set was processed successfully across the five original analysis modes:

20 files × 5 modes = 100 operations
100 successful
0 failures

The tested files were identified as GDSC v101.

This was a representative test, not a complete 693-file round-trip validation.

PR #1 regression

The same-line "else: if" reconstruction issue reported in PR #1 was reviewed against the latest implementation.

The current token-position-driven reconstruction already handles the reported case.

The regression was tested without requiring another modification to the verified decompiler.

---

📋 Command-Line Interface

python3 OpenGDS.py <mode> <file-or-folder> [options]

Available commands

Command| Input| Description
"info"| ".gdc"| Inspect GDSC file information and validate supported structures.
"comp"| ".gd"| Compile GDScript into GDSC v101.
"dcmp"| ".gdc"| Decompile/reconstruct GDScript.
"hexdump"| ".gdc"| Dump decoded payload bytes.
"consts"| ".gdc"| Extract constants.
"audit"| ".gdc"| Perform static security analysis.
"disasm"| ".gdc"| Disassemble the token stream.

Basic usage

Inspect a compiled file

python3 OpenGDS.py info assets/game.gdc

Compile a GDScript file

python3 OpenGDS.py comp game.gd

Compile a directory recursively

python3 OpenGDS.py comp ./scripts/

Decompile a compiled file

python3 OpenGDS.py dcmp assets/game.gdc

Recursively decompile a directory

python3 OpenGDS.py dcmp assets/

Extract constants

python3 OpenGDS.py consts assets/game.gdc

Disassemble

python3 OpenGDS.py disasm assets/game.gdc

Hex dump

python3 OpenGDS.py hexdump assets/game.gdc

Security audit

python3 OpenGDS.py audit assets/

---

⚙️ Compilation Options

The "comp" command supports additional controls:

Option| Description
"--no-compress"| Generate an uncompressed GDSC v101 container.
"--force"| Overwrite existing compilation outputs.
"--tab-size N"| Set the tab width used when measuring source columns. Default: 4.
"-o", "--output PATH"| Specify the output file or output directory.
"--outdir PATH"| Specify an output directory.
"--continue-on-error"| Continue recursive processing after an individual file fails.

Examples:

# Compile without Zstandard compression
python3 OpenGDS.py comp game.gd --no-compress

# Overwrite an existing output
python3 OpenGDS.py comp game.gd --force

# Compile a folder with a custom tab width
python3 OpenGDS.py comp ./scripts/ --tab-size 4

# Continue processing after errors
python3 OpenGDS.py comp ./scripts/ --continue-on-error

# Choose an output directory
python3 OpenGDS.py comp ./scripts/ --outdir ./build/

By default, compilation refuses to overwrite existing ".gdc" files.

---

📂 Recursive Batch Processing

OpenGDS accepts both individual files and directories.

For directory input, matching files are discovered recursively, and their relative directory structure is preserved.

Compilation example

Input:

scripts/
├── player.gd
├── game.gd
└── entities/
    ├── enemy.gd
    └── boss.gd

Output:

scripts.comp/
├── player.gdc
├── game.gdc
└── entities/
    ├── enemy.gdc
    └── boss.gdc

Decompilation example

Input:

assets/
├── player.gdc
└── entities/
    └── enemy.gdc

Output:

assets.dcmp/
├── player.gd
└── entities/
    └── enemy.gd

The other analysis commands use the same recursive processing model.

---

ℹ️ File Information ("info")

The "info" command provides metadata without requiring manual inspection of the binary format.

Example output fields:

FORMAT: Godot GDScript binary-token container (GDSC)
SIGNATURE: GDSC
BYTECODE VERSION: 101
ENGINE RELEASE: Not encoded in the GDSC header
FILE SIZE: ...
HEADER SIZE: 12 bytes
STORED PAYLOAD: ...
COMPRESSION: Zstandard
DECLARED DECODED SIZE: ...
SHA-256: ...

VALIDATION: PASS (GDSC v101 structure and payload decoded)
DECODED PAYLOAD: ...
IDENTIFIERS: ...
CONSTANTS: ...
TOKEN LINE ENTRIES: ...
TOKEN COLUMN ENTRIES: ...
TOKENS: ...

The command reports the actual bytecode version stored in the header.

For unsupported versions, it can display available header information but does not attempt to decode an unsupported payload.

---

🔐 Security Audit

The "audit" command is designed for defensive reverse engineering and static security inspection.

It scans decoded constants and token data for patterns such as:

- Private-key material.
- JWT-like strings.
- API-key and credential assignments.
- AWS access-key patterns.
- GitHub token patterns.
- Generic secret/token assignments.
- Embedded URLs.
- References to potentially security-sensitive dynamic execution APIs.

Secret-like values are redacted in the report rather than printed.

HTTP URLs are assigned a higher informational severity than HTTPS URLs.

Audit results are heuristic indicators for manual investigation, not proof of a vulnerability or confirmation that a secret is active.

The absence of findings does not establish that a script is secure.

---

🧬 GDSC Compatibility

Current supported target:

Format:          GDSC
Bytecode version: 101
Compression:     Zstandard / Uncompressed

Tested material includes:

- Godot 4.6.2 compiled-script corpus.
- Supplied Godot 4.7.1 GDSC v101 corpus.
- A complete 1,130-file byte-identical round-trip test.

The fact that multiple tested Godot releases use GDSC v101 does not guarantee compatibility with every future Godot release.

OpenGDS checks the bytecode version and rejects unsupported versions during decoding instead of silently interpreting incompatible data.

Not currently guaranteed

- Godot 3.x bytecode.
- GDSC versions other than v101.
- Encrypted ".gde" scripts.
- Every possible GDScript language construct.
- Future changes to Godot's tokenizer or binary serialization.
- Full semantic equivalence for arbitrary scripts without Godot's parser and type checker.

---

⚠️ Technical Scope and Limitations

1. Tokenizer-buffer generation versus full semantic compilation

The "comp" command generates Godot-compatible GDSC v101 tokenizer buffers.

It implements tokenization and binary serialization, but it does not replace Godot's complete GDScript parser, semantic analysis, type checker, or project compiler.

A successfully generated ".gdc" therefore means that OpenGDS generated and validated a supported tokenizer-buffer structure. It does not independently certify that an arbitrary script is valid in a complete Godot project.

2. Comments

Comments are not reliably recoverable from compiled GDSC token data.

Consequently:

Original source
       ≠
Decompiled source

may differ because comments and other source-only information were discarded during compilation.

3. Source positions and formatting

GDSC stores token-position metadata.

OpenGDS preserves this information during its updated decompilation process, enabling the verified byte-identical round trip across the supplied corpus.

However, arbitrary ".gd" files do not necessarily contain the metadata required to reproduce an original compiled file byte-for-byte.

4. Compiler coverage

The Python tokenizer is based on the supported GDScript token model and the GDSC v101 serialization format.

The 1,130-file validation demonstrates exact compatibility with the supplied corpus, not exhaustive coverage of every possible GDScript construct.

---

🛠️ Installation

Requirements

- Python 3.10 or newer.
- Zstandard command-line utility for decoding compressed GDSC files.
- System "libzstd" shared library for compressed compilation.

Uncompressed compilation using "--no-compress" does not require the Zstandard compression library.

Termux / Android

pkg update
pkg install python zstd

Linux

Install Python 3, Zstandard, and the system Zstandard shared library.

For Debian/Ubuntu-based systems:

sudo apt install python3 zstd libzstd1

Windows

Install Python 3 and make the Zstandard command-line utility and compatible "libzstd" runtime available to the environment.

macOS

Install Python 3 and Zstandard, for example through Homebrew:

brew install python zstd

Copy "OpenGDS.py" into your working directory.

No Godot editor executable is needed for the implemented GDSC v101 compilation workflow.

---

🧪 Development / Regression Testing

OpenGDS uses a regression-driven development workflow.

Original GDC
     |
     v
 Decompile
     |
     v
 Compare source
     |
     v
 Compile
     |
     v
 SHA-256 comparison
     |
     v
 Identify divergence
     |
     v
 Fix implementation
     |
     v
 Rerun complete corpus

Whenever the tokenizer, serializer, decoder, or reconstruction logic changes, the complete supplied regression corpus should be tested again.

The acceptance condition for a byte-identical round trip is:

[
SHA256(GDC_{\text{original}})

SHA256(GDC_{\text{rebuilt}})
]

A successful compilation count alone is not sufficient to establish byte-identical compatibility.

Regression evidence

The full-corpus test report and per-file SHA-256 results document the 1,130-file validation.

Each CSV record contains:

- Relative file path.
- Original file size.
- Rebuilt file size.
- Original SHA-256.
- Rebuilt SHA-256.
- Match result.

---

📋 Changelog

v1.0 Beta — GDSC v101 Bidirectional Support

Added

- "info" command: Inspect GDSC metadata, including signature, bytecode version, compression, file size, payload size, SHA-256, and structural information.
- "comp" command: Compile ".gd" source files into GDSC v101 ".gdc" files.
- Python-native GDSC v101 tokenizer-buffer generation and serialization.
- Recursive directory compilation with preserved directory structure.
- Compressed and uncompressed GDSC output.
- Compilation options: "--no-compress", "--force", and "--tab-size".

Improved

- Decompiler reconstruction using original token line and column metadata.
- Preservation of identifier pools, constant pools, token data, and source-position metadata.
- GDSC v101 round-trip compatibility.
- File handling with mode-specific ".gdc" and ".gd" input support.

Fixed / Verified

- Reviewed the same-line "else: if" reconstruction issue reported in PR #1.
- Verified that the updated reconstruction algorithm preserves the reported structure.
- Corrected NodePath Variant decoding and encoding behavior.

Full-corpus validation

Test| Result
"info"| 1,130 / 1,130
"dcmp"| 1,130 / 1,130
"comp"| 1,130 / 1,130
Exact SHA-256 matches| 1,130 / 1,130
Compilation failures| 0
Hash mismatches| 0

The exact round-trip result was obtained by compiling sources freshly generated using the updated "dcmp" implementation.

---

📋 Planned Features

Priority| Feature| Status
🟡 Medium| Expanded Godot version coverage| Planned
🟡 Medium| ".pck" archive parsing and unpacking| Planned
🟡 Medium| Godot 3.x support| Planned
🟡 Medium| Richer GDScript reconstruction| Planned
🟢 Low| Advanced data-flow and security analysis| Planned
🟢 Low| Improved source formatting recovery| Planned
🟢 Low| Encrypted ".gde" research/support| Planned

---

🤝 Contributing & Support

OpenGDS is currently a solo project by ABDO10_DZ / 0xbytecode.

- GitHub: https://github.com/ABDO10DZ/OpenGDS
- Email: "abdo10_dz@proton.me"
- Ko-fi: https://ko-fi.com/0xbytecode

Bug reports should include:

- OpenGDS version.
- GDSC bytecode version.
- Godot version, if known.
- The command used.
- Terminal output and error messages.
- A minimal ".gdc" or ".gd" sample when legally shareable.

Contributions, format research, regression samples, and compatibility testing are welcome.

---

📜 License

OpenGDS is released under the MIT License. See "LICENSE" for details.

---

🏆 Credits

- ABDO10_DZ / 0xbytecode — Project author, GDSC format reverse engineering, tokenizer, compiler, decoder, reconstruction, and security tooling.
- DeepSeek — Assisted with algorithm design and problem-solving during development.
- Claude (Anthropic) — Assisted with decompiler logic, regression analysis, and token reconstruction.
- ChatGPT (OpenAI) — Assisted with compiler serialization, round-trip verification, regression testing, and implementation improvements.
- Godot community — For the open-source engine and publicly available implementation details.

---

OpenGDS is provided for educational, interoperability, and authorized security research. Only analyze software you have permission to reverse engineer.