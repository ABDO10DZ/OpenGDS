# OpenGDS v1.0 Beta

**A Godot GDScript bytecode decompiler, disassembler, constant extractor, and security auditor**  
By **ABDO10_DZ / 0xbytecode**

OpenGDS reads compiled Godot `.gdc` files and reconstructs readable GDScript. It also provides bytecode/token disassembly, hexadecimal dumps, constant extraction, recursive batch processing, and security auditing.

The current implementation has been tested against **Godot GDSC v101** files from both a **Godot 4.6.2 corpus** and supplied **Godot 4.7.1** source/decompilation pairs.

> ⚠️ **Beta Release** – The decompiler is substantially functional, but exact source recovery is not possible for information discarded during compilation, especially comments. When original source is available, the recommended validation method is a byte-level/hash comparison after removing comments.

---

## 🚀 Current Features

| Feature | Description |
|---------|-------------|
| **GDScript Reconstruction (`dcmp`)** | Reconstructs readable GDScript including class declarations, inheritance, variables, constants, functions, expressions, control flow, casts, calls, NodePaths, and nested statements. |
| **Disassembler (`disasm`)** | Displays the decoded bytecode/token stream for low-level reverse engineering. |
| **Hex Dump (`hexdump`)** | Produces a hexadecimal representation of the raw `.gdc` data. |
| **Constant Dump (`consts`)** | Extracts and displays constants contained in the compiled script. |
| **Security Audit (`audit`)** | Scans scripts for potentially sensitive material such as hardcoded URLs, IP addresses, credentials, API keys, tokens, debug indicators, and other suspicious strings. |
| **Recursive Batch Processing** | A file path processes one `.gdc`; a directory recursively processes `.gdc` files in all subdirectories. |
| **GDSC v101 Validation** | Rejects unsupported GDSC versions instead of silently interpreting incompatible data. |
| **Zstandard Support** | Handles compressed GDSC v101 data used by the tested Godot 4.x files. |
| **Multi-Platform** | Designed for Python 3 environments including Termux/Android, Linux, Windows, and macOS. |

---

## 🧪 Validation Status

OpenGDS has been tested using the fix → test → compare → fix regression workflow.

### Godot 4.7.1 source pairs

The supplied compiled/source pairs were tested with hash and byte-level comparison:

| Pair | Result |
|------|--------|
| `game.gdc` → `game.gd` | ✅ Exact byte match |
| `bullet.gdc` → `bullet.gd` | ✅ Exact byte match |
| `gun.gdc` → `gun.gd` | ✅ Exact after comment removal |
| `player.gdc` → `player.gd` | ✅ Exact after comment removal |

Comments are not reliably recoverable from compiled GDSC token data, so comment-containing files are validated after removing comments and comment-only blank lines.

### Godot 4.6.2 corpus

The supplied ZIP contains **693 `.gdc` files**. A representative 20-file validation set was processed successfully across all five modes:

```text
20 × 5 modes = 100 operations
100 successful
0 failures
```

The corpus was identified as **GDSC v101** in the tested files.

> The 693-file corpus does not include original `.gd` sources, so byte-for-byte source equivalence cannot be proven for those files. Successful decoding is verified; exact reconstruction requires the corresponding original source.

---

## 📋 Current CLI

```text
python OpenGDS.py <mode> <file-or-folder>
```

### Modes

| Command | Description |
|---------|-------------|
| `dcmp` | Decompile/reconstruct GDScript. |
| `hexdump` | Produce a hexadecimal dump. |
| `consts` | Dump constants. |
| `audit` | Run the security audit. |
| `disasm` | Show the decoded/disassembled token stream. |

Every mode accepts either:

- **A single `.gdc` file**
- **A directory**, recursively scanning its subdirectories for `.gdc` files

### Examples

```bash
# Decompile one file
python3 OpenGDS.py dcmp assets/game.gdc

# Recursively decompile a directory
python3 OpenGDS.py dcmp assets/

# Hex dump
python3 OpenGDS.py hexdump assets/game.gdc

# Extract constants
python3 OpenGDS.py consts assets/game.gdc

# Security audit
python3 OpenGDS.py audit assets/

# Disassemble
python3 OpenGDS.py disasm assets/game.gdc
```

For recursive operations, OpenGDS reports each successfully processed file and the output directory.

---

## 📂 Batch Output

When a directory is supplied, OpenGDS recursively finds `.gdc` files and preserves their relative structure in the generated output.

Example:

```text
assets/
├── game.gdc
└── player/
    └── player.gdc
```

produces output equivalent to:

```text
assets.dcmp/
├── game.gd
└── player/
    └── player.gd
```

The same recursive model is used by the other output-producing modes.

---

## 🔐 Security Audit

`audit` is intended for defensive reverse engineering and security research.

It can flag patterns such as:

- URLs
- IPv4 addresses
- API keys
- access tokens
- JWT-like strings
- private-key material
- passwords/credentials
- debug/development indicators
- suspicious embedded strings

Audit findings should be treated as **indicators for manual review**, not proof of a vulnerability. Values that resemble secrets may be false positives.

---

## ⚙️ Installation

### Python

Python 3.7+ is recommended.

### Termux / Android

```bash
pkg install python
pkg install zstd
```

### Linux

Install Python 3 and the system Zstandard library/development package appropriate for your distribution.

### Windows / macOS

Install Python 3 and make sure the required Zstandard runtime/library is available to the Python environment used by OpenGDS.

Then copy `OpenGDS.py` to your working directory.

---

## 🧬 GDSC Compatibility

The current tested target is:

```text
GDSC version: 101
```

This has been tested with:

- **Godot 4.6.2** compiled scripts
- **Godot 4.7.1** compiled scripts

The fact that both tested releases use GDSC v101 does **not** mean every future Godot 4.x release is automatically compatible. OpenGDS explicitly validates the GDSC version and should reject unsupported versions rather than attempting unsafe interpretation.

### Not currently guaranteed

- Godot 3.x bytecode
- Unsupported/unknown GDSC versions
- Encrypted `.gde` scripts
- Arbitrary future Godot bytecode changes

---

## ⚠️ Limitations

### Comments

Original comments may be absent from compiled GDSC data. Therefore:

```text
original source
        ≠
decompiled source
```

can differ only because of comments even when the executable GDScript reconstruction is otherwise exact.

For source validation, compare:

1. raw SHA-256 first;
2. if different, remove comments/comment-only blank lines from both;
3. compare SHA-256 again;
4. if still different, perform a byte-level diff.

### Source formatting

OpenGDS reconstructs source from compiled information. Formatting that was discarded by compilation cannot always be recovered exactly. The goal is syntactically valid, semantically faithful GDScript rather than preservation of every original whitespace choice.

---

## 🛠️ Development / Regression Testing

The recommended development loop is:

```text
GDC
 ↓
decompile
 ↓
compare with original GD
 ↓
SHA-256 / byte diff
 ↓
identify first divergence
 ↓
fix decoder/reconstructor
 ↓
rerun regression tests
```

Known source pairs should remain regression tests whenever the decompiler is modified.

---

## 📋 Planned Features

| Priority | Feature | Status |
|----------|---------|--------|
| 🟡 Medium | Expanded Godot version coverage | Planned |
| 🟡 Medium | `.pck` archive parsing/unpacking | Planned |
| 🟡 Medium | Godot 3.x support | Planned |
| 🟡 Medium | Richer control-flow reconstruction | Planned |
| 🟢 Low | Advanced data-flow/security analysis | Planned |
| 🟢 Low | Improved source formatting recovery | Planned |
| 🟢 Low | Encrypted `.gde` research/support | Planned |

---

## 🤝 Contributing & Support

OpenGDS is currently a solo project by **ABDO10_DZ / 0xbytecode**.

- GitHub: https://github.com/ABDO10DZ/opengds
- Email: `abdo10_dz@proton.me`
- Ko-fi: https://ko-fi.com/0xbytecode

Bug reports should include:

- OpenGDS version
- GDSC version
- Godot version, if known
- the relevant command
- terminal output/error
- a minimal `.gdc` sample when legally shareable

---

## 📜 License

OpenGDS is released under the **MIT License**. See `LICENSE` for details.

---

## 🏆 Credits

- **0xbytecode / ABDO10_DZ** – reverse engineering of the Godot GDSC format, opcode mapping, parser, reconstruction, and security tooling.
- **DeepSeek** – assisted with algorithm design and problem-solving during development.
- **Claude (Anthropic)** – assisted with decompiler logic, regression analysis, and opcode reconstruction.
- **chatGPT** - did the last touches and fixed many remaining issues. 
- **Godot community** – for the open-source engine and publicly available implementation details.

---

*OpenGDS is provided for educational, interoperability, and authorized security research. Only analyze software you have permission to reverse engineer.*
