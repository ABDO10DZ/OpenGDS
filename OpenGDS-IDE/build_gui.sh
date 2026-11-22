#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python 3.10+ was not found. Set PYTHON=/path/to/python3." >&2
  exit 10
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || {
  echo "ERROR: OpenGDS-IDE requires Python 3.10 or newer." >&2
  exit 11
}

VENV_DIR=".build-venv-gui"
VENV_PY="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt "PyInstaller>=6.10,<7"

echo "[1/5] Checking source syntax..."
"$VENV_PY" - <<'PY'
from pathlib import Path
import py_compile

root = Path(".")
excluded = {".git", ".venv", ".build-venv-gui", "build", "dist", "__pycache__", "node_modules"}
sources = [
    path for path in root.rglob("*.py")
    if not any(part in excluded or part.startswith(".build-venv") for part in path.parts)
]
for source in sources:
    py_compile.compile(str(source), doraise=True)
print(f"Compiled {len(sources)} Python files.")
PY

echo "[2/5] Running the full test suite..."
QT_QPA_PLATFORM=offscreen "$VENV_PY" -m unittest discover -s tests -v

if [[ "$(uname -s)" == "Darwin" ]]; then
  echo "[3/5] Creating the macOS application icon..."
  command -v sips >/dev/null 2>&1 || { echo "ERROR: macOS sips utility is required." >&2; exit 12; }
  command -v iconutil >/dev/null 2>&1 || { echo "ERROR: macOS iconutil utility is required." >&2; exit 12; }
  SOURCE_ICON="assets/opengds-ide.png"
  ICONSET="build/opengds-ide.iconset"
  mkdir -p "$ICONSET"
  sips -z 16 16 "$SOURCE_ICON" --out "$ICONSET/icon_16x16.png" >/dev/null
  sips -z 32 32 "$SOURCE_ICON" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$SOURCE_ICON" --out "$ICONSET/icon_32x32.png" >/dev/null
  sips -z 64 64 "$SOURCE_ICON" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$SOURCE_ICON" --out "$ICONSET/icon_128x128.png" >/dev/null
  sips -z 256 256 "$SOURCE_ICON" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$SOURCE_ICON" --out "$ICONSET/icon_256x256.png" >/dev/null
  sips -z 512 512 "$SOURCE_ICON" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$SOURCE_ICON" --out "$ICONSET/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$SOURCE_ICON" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o build/opengds-ide.icns
else
  echo "[3/5] Linux packaging uses the application PNG and native desktop icon metadata."
fi

echo "[4/5] Building the platform-native application bundle..."
"$VENV_PY" -m PyInstaller --clean --noconfirm OpenGDS-IDE.spec

echo "[5/5] Smoke-testing the frozen executable and embedded OpenGDS core..."
"$VENV_PY" tests/smoke_frozen_bundle.py

echo
echo "BUILD SUCCESSFUL"
case "$(uname -s)" in
  Darwin) echo "Output: $SCRIPT_DIR/dist/OpenGDS-IDE.app" ;;
  *)      echo "Output: $SCRIPT_DIR/dist/OpenGDS-IDE/" ;;
esac
echo "The application bundle passed the embedded compile/inspect/decompile smoke test."
echo "Godot remains an external dependency for live engine, LSP and DAP workflows."
