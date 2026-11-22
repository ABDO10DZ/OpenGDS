# Platform-aware PyInstaller build for OpenGDS-IDE.
# Windows: one-file GUI executable.
# Linux: one-folder GUI application.
# macOS: one-folder .app bundle (not a one-file app bundle).
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()
sys.path.insert(0, str(ROOT))

from app_info import APP_NAME, VERSION  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

if IS_WINDOWS:
    ICON_FILE = ROOT / "assets" / "opengds-ide.ico"
    if not ICON_FILE.is_file():
        raise SystemExit(f"Required Windows icon not found: {ICON_FILE}")
elif IS_MACOS:
    # build_gui.sh and CI generate this from the checked-in PNG when iconutil is available.
    candidate = ROOT / "build" / "opengds-ide.icns"
    ICON_FILE = candidate if candidate.is_file() else None
else:
    ICON_FILE = None

icon_arg = str(ICON_FILE) if ICON_FILE is not None else None

datas = []
binaries = []
hiddenimports = [
    "OpenGDS",
    "backend",
    "app_info",
    "ai_agent",
    "ai_panel",
    "ai_providers",
    "ai_models",
    "ide_control",
    "project_tasks",
    "task_planner",
    "project_index",
    "project_analysis",
    "project_debug",
    "project_review",
    "project_validation",
    "git_service",
    "git_panel",
    "archive_tools",
    "language_service",
    "lsp_client",
    "dap_client",
    "protocol",
    "logging_system",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    "shiboken6",
    "zstandard",
    "keyring",
]

# Collect native Qt libraries/plugins and dynamically loaded keyring backends.
for package in ("PySide6", "shiboken6", "zstandard", "keyring"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

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

if IS_WINDOWS:
    # Windows uses a single-file GUI executable.
    app = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
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
        icon=icon_arg,
    )
else:
    # Linux and macOS use one-folder bundles for faster startup and transparent
    # native-library layout. PyInstaller documents one-file macOS app bundles as
    # inefficient because they unpack the complete app on every launch.
    executable = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
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
        icon=icon_arg,
    )
    collected = COLLECT(
        executable,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
    if IS_MACOS:
        app = BUNDLE(
            collected,
            name=f"{APP_NAME}.app",
            icon=icon_arg,
            bundle_identifier="com.ABDO10DZ.OpenGDSIDE",
            version=VERSION,
            info_plist={
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleIdentifier": "com.ABDO10DZ.OpenGDSIDE",
                "CFBundleVersion": VERSION,
                "CFBundleShortVersionString": VERSION,
                "NSHighResolutionCapable": True,
            },
        )
