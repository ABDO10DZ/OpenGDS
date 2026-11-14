# PyInstaller one-file build for OpenGDS-IDE (Windows x64).
# Run from the project root with: python -m PyInstaller --clean --noconfirm OpenGDS-IDE.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()
ICON_FILE = ROOT / "assets" / "opengds-ide.ico"

if not ICON_FILE.is_file():
    raise SystemExit(f"Required Windows icon not found: {ICON_FILE}")

datas = []
binaries = []
hiddenimports = [
    "OpenGDS",                 # Embedded CLI/compiler/decompiler module.
    "backend",
    "app_info",
    "ai_agent",
    "ai_panel",
    "git_service",
    "git_panel",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    "shiboken6",
    "zstandard",
]

# collect_all adds the native Qt DLLs, platform plugins (including qwindows),
# metadata and Python extension modules needed by the one-file application.
for package in ("PySide6", "shiboken6", "zstandard"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

# Runtime assets are embedded in the executable and unpacked only into the
# standard temporary _MEI directory used internally by PyInstaller one-file.
datas += [
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "LICENSE"), "."),
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OpenGDS-IDE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE),
)
