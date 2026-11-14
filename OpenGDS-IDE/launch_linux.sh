#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python 3.10+ was not found. Set PYTHON=/path/to/python3 and retry." >&2
  exit 10
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || {
  echo "ERROR: OpenGDS-IDE requires Python 3.10 or newer." >&2
  exit 11
}

if [[ ! -x .venv/bin/python ]]; then
  echo "[1/3] Creating isolated Python environment..."
  "$PYTHON_BIN" -m venv .venv
fi

if ! .venv/bin/python -c 'import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, PySide6.QtNetwork, zstandard' >/dev/null 2>&1; then
  echo "[2/3] Installing PySide6, Zstandard and application dependencies..."
  echo "      An internet connection is required for the first installation."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

.venv/bin/python -c 'import PySide6; from PySide6.QtWidgets import QApplication; from PySide6.QtNetwork import QTcpSocket; print("PySide6", PySide6.__version__, "OK")'
echo "[3/3] Starting OpenGDS-IDE..."
exec .venv/bin/python main.py "$@"
