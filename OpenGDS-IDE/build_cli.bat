@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=OpenGDS-cli"
set "ICON_FILE=%CD%\assets\opengds-ide.ico"
set "VENV_DIR=.build-venv-cli"
set "DIST_DIR=dist"
set "WORK_DIR=build\OpenGDS-cli"
set "SMOKE_DIR=build\opengds-cli-smoke"

echo ============================================================
echo OpenGDS Core CLI - Windows x64 single-EXE build
echo Output: %DIST_DIR%\%APP_NAME%.exe
echo Console: ENABLED
echo EXE icon: %ICON_FILE%
echo ============================================================

echo.
echo [1/8] Checking Windows Python build environment...
where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python Launcher for Windows was not found.
    echo Install 64-bit Python 3.12 and enable the py launcher.
    exit /b 1
)
py -3.12 -c "import struct,sys; print(sys.version); print('Architecture: ' + str(struct.calcsize('P')*8) + '-bit'); sys.exit(0 if struct.calcsize('P')*8==64 else 1)"
if errorlevel 1 (
    echo ERROR: 64-bit Python 3.12 is required.
    exit /b 1
)

if not exist "OpenGDS.py" (
    echo ERROR: OpenGDS.py was not found beside this BAT file.
    exit /b 1
)
if not exist "logging_system.py" (
    echo ERROR: logging_system.py was not found beside this BAT file.
    exit /b 1
)
if not exist "%ICON_FILE%" (
    echo ERROR: Windows icon is missing: %ICON_FILE%
    echo Restore assets\opengds-ide.ico before building.
    exit /b 1
)

echo [2/8] Creating isolated CLI build environment...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    py -3.12 -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b 1
)
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 exit /b 1

echo.
echo [3/8] Installing PyInstaller, Zstandard and PE validation tools...
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install --upgrade "PyInstaller>=6.10,<7" "zstandard>=0.23,<1" pefile
if errorlevel 1 exit /b 1
python -c "import PyInstaller,zstandard,logging_system,pefile; print('PyInstaller:',PyInstaller.__version__); print('Zstandard:',zstandard.__version__)"
if errorlevel 1 exit /b 1

echo.
echo [4/8] Validating the ICO and checking core source syntax...
python -c "import pathlib,struct,sys; p=pathlib.Path(r'%ICON_FILE%'); b=p.read_bytes(); h=struct.unpack_from('<HHH',b); ok=h[0]==0 and h[1]==1 and h[2]>0; print('ICO directory:',h); sys.exit(0 if ok else 1)"
if errorlevel 1 (
    echo ERROR: %ICON_FILE% is not a valid Windows ICO file.
    exit /b 1
)
python -m py_compile OpenGDS.py logging_system.py
if errorlevel 1 exit /b 1

if not exist "build" mkdir "build"
if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
if exist "%SMOKE_DIR%" rmdir /s /q "%SMOKE_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"

echo.
echo [5/8] Building the standalone console executable with the icon...
echo       --onefile  = all Python code and dependencies inside one EXE
echo       --console  = keep command prompt / terminal output enabled
echo       --icon     = embed the OpenGDS Windows icon resource

echo.
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --icon "%ICON_FILE%" ^
    --name "%APP_NAME%" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%WORK_DIR%" ^
    --specpath "build" ^
    --hidden-import=logging_system ^
    --hidden-import=zstandard ^
    --collect-all zstandard ^
    "OpenGDS.py"
if errorlevel 1 (
    echo ERROR: PyInstaller failed.
    exit /b 1
)

if not exist "%DIST_DIR%\%APP_NAME%.exe" (
    echo ERROR: Expected output was not created: %DIST_DIR%\%APP_NAME%.exe
    exit /b 1
)

echo.
echo [6/8] Verifying the Windows EXE contains a GROUP_ICON resource...
python -c "import pefile,sys; p=pefile.PE(r'%DIST_DIR%\%APP_NAME%.exe'); ok=hasattr(p,'DIRECTORY_ENTRY_RESOURCE') and any(e.id==14 for e in p.DIRECTORY_ENTRY_RESOURCE.entries); print('Embedded EXE icon resource:', 'FOUND' if ok else 'MISSING'); sys.exit(0 if ok else 1)"
if errorlevel 1 (
    echo ERROR: The built CLI EXE does not contain a Windows icon resource.
    exit /b 1
)

echo.
echo [7/8] Smoke-testing the EXE (version, compression, inspect, decompile)...
"%DIST_DIR%\%APP_NAME%.exe" --version
if errorlevel 1 (
    echo ERROR: EXE version check failed.
    exit /b 1
)
mkdir "%SMOKE_DIR%" 2>nul
(
    echo extends Node
    echo.
    echo func _ready^(^):
    echo     print^("OpenGDS CLI embedded-core smoke test"^)
) > "%SMOKE_DIR%\cli_smoke.gd"
"%DIST_DIR%\%APP_NAME%.exe" comp "%SMOKE_DIR%\cli_smoke.gd" --force
if errorlevel 1 (
    echo ERROR: EXE compiler or bundled Zstandard compression failed.
    exit /b 1
)
"%DIST_DIR%\%APP_NAME%.exe" info "%SMOKE_DIR%\cli_smoke.gdc"
if errorlevel 1 (
    echo ERROR: EXE GDSC inspection/decompression failed.
    exit /b 1
)
"%DIST_DIR%\%APP_NAME%.exe" dcmp "%SMOKE_DIR%\cli_smoke.gdc" --output "%SMOKE_DIR%\cli_roundtrip.gd"
if errorlevel 1 (
    echo ERROR: EXE decompiler failed.
    exit /b 1
)
findstr /C:"OpenGDS CLI embedded-core smoke test" "%SMOKE_DIR%\cli_roundtrip.gd" >nul
if errorlevel 1 (
    echo ERROR: Compile/decompile round-trip verification failed.
    exit /b 1
)

echo.
echo [8/8] Build verification complete.
echo.
echo SUCCESS: %CD%\%DIST_DIR%\%APP_NAME%.exe
echo The CLI core, logging module, Zstandard, and Windows icon are inside this EXE.
echo Console mode is enabled. Use OpenGDS-cli.exe --help for command usage.
echo No Python installation or separate .py/.dll files are needed at runtime.
echo Godot is still external for Godot-engine runtime debugging workflows.
echo.
exit /b 0
