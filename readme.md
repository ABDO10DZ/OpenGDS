# OpenGDS v1.0 Beta

**A Godot 4.6.x GDScript decompiler, disassembler, and security auditor**  
By **ABDO10_DZ / 0xbytecode**

OpenGDS is a cross‑platform reverse‑engineering tool that reads compiled Godot `.gdc` files and reconstructs readable GDScript source code. It also includes a full disassembler, batch scanner, and automated security auditor. It runs natively on Android (Termux), Linux, Windows, and macOS.

> ⚠️ **Beta Release** – This version is stable for class‑structure extraction, disassembly, and security audits. Function‑body decompilation is functional but may produce imperfect code for complex scripts. A future release will deliver fully compilable output.

---

## 🚀 Current Features

| Feature | Description |
|---------|-------------|
| **Source Reconstruction** | Recovers `extends`, `class_name`, `enum`, `const`, `var`, `signal`, and function signatures. Function bodies are rebuilt as readable GDScript (quality varies; see limitations). |
| **Disassembler** | Full token dump with opcode mnemonics and register annotations. |
| **Identifier / Constant Dump** | Extract all variable names, function names, and constants (strings, numbers). |
| **Batch Scanner** | Recursively processes directories and aggregates identifiers & strings across all `.gdc` files. |
| **Security Auditor** | Automated scan for hardcoded URLs, IPs, API keys, debug flags, and secrets. |
| **Zstd Decompression** | Handles Godot 4.6.x compressed bytecode (v101) out‑of‑the‑box. |
| **Multi‑Platform** | Runs wherever Python 3 and `libzstd` are available – Termux, Linux, Windows, macOS. |

---

## 📋 Planned Features (Todo)

| Priority | Feature | Status |
|----------|---------|--------|
| 🔴 Highest | **Full compilable decompiler** – accurate expression folding, control‑flow reconstruction, variable naming. | Under active development |
| 🔴 High | **.gde encryption support** – cross‑platform AES key extraction and real‑time decryption. | Planned |
| 🟡 Medium | **.pck archive parsing** – unpack Godot asset packages and decompile scripts inside. | Planned |
| 🟡 Medium | **Godot 3.x support** – backwards compatibility for older bytecode formats. | Planned |
| 🟡 Medium | **Godot 4.7 coverage** – ensure compatibility with the next engine version. | Planned |
| 🟢 Low | **Advanced Security Audit** – deeper RPC analysis, data‑flow tracing, vulnerability scoring. | Planned |

---

## 📥 Installation

1. **Install Python 3.7+**  
   On Termux: `pkg install python`  
   On Linux/macOS: usually pre‑installed.

2. **Install libzstd**  
   - Termux: `pkg install zstd`  
   - Ubuntu/Debian: `sudo apt install libzstd-dev`  
   - Windows: use a pre‑compiled `libzstd.dll` (place in the same folder).

3. **Download OpenGDS**  
   Clone the repository or copy the script to your device. The script is a single file: `opengds.py`.

4. **Run it**  
   ```bash
   python3 opengds.py source myfile.gdc
   ```

---

## 📖 Usage

All commands accept a `.gdc` file or a directory (for batch/audit).

| Command | Description |
|---------|-------------|
| `source <file>` | Reconstruct GDScript source from the bytecode. |
| `disasm <file>` | Show annotated bytecode dump. |
| `ids <file>` | List all identifiers (variables, functions, classes). |
| `consts <file>` | Show all constants (strings, numbers). |
| `info <file>` | Display file metadata (version, counts, class info). |
| `batch <dir>` | Scan all `.gdc` files recursively and print top identifiers / strings. |
| `audit <dir>` | Search for hardcoded URLs, IPs, API keys, debug flags. |

### Examples

```bash
# Decompile a single script
python3 opengds.py source button_translate.gdc

# List all constants in a file
python3 opengds.py consts AndroidBilling.gdc

# Scan a whole game for secrets
python3 opengds.py audit ../game_assets/

# Batch‑analyse identifiers across the entire project
python3 opengds.py batch ../game_assets/ > all_strings.txt
```

---

## 💡 Important Notes

- **Beta limitations** – Function bodies may contain raw register names (`_rNN`) or incomplete expressions in complex scripts.  
  We are actively working on a full expression folder and control‑flow reconstruction for the next release.
- **Shaders** – Godot shader `.gdc` files are not yet fully supported; decompilation will produce low‑level listings.
- **Encrypted scripts (`.gde`)** – Not yet decrypted by this version. A separate key extraction tool is coming.
- **Godot 3.x / 4.7** – These formats differ; support is planned but not yet available.

---

## 🤝 Contributing & Support

OpenGDS is currently a solo project by **ABDO10_DZ / 0xbytecode**. If you find a bug, have a feature request, or want to help with development:

- Open an issue on the [GitHub repository](https://github.com/ABDO10DZ/opengds)  
- Email: `abdo10_dz@proton.me` (please include “OpenGDS” in the subject)

If this tool saved your project or helped you in your security research, consider **buying me a coffee** ☕  
[Ko-fi](https://ko-fi.com/0xbytecode)

---

## 📜 License

OpenGDS is released under the **MIT License**. See `LICENSE` file for details.

---

## 🏆 Credits

- **0xbytecode** – reverse‑engineering of the Godot 4.6.x bytecode format, opcode mapping, and initial proof‑of‑concept.
- **DeepSeek** – assisted with algorithm design and problem‑solving throughout development.
- **Claude (Anthropic)** – helped refine the decompiler logic and opcode table.
- All the open‑source Godot community for building an engine worth exploring.

---

*OpenGDS is provided for educational and security research purposes. Always respect the terms of service of the software you analyze.*
