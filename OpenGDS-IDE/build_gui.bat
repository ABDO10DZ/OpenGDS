@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=OpenGDS-IDE"
set "ICON_FILE=%CD%\assets\opengds-ide.ico"
set "VENV_DIR=.build-venv"
set "DIST_DIR=dist"
set "BUILD_DIR=build\pyinstaller-gui"

 echo ============================================================
 echo OpenGDS-IDE - Windows x64 single-file GUI build
 echo Output: %DIST_DIR%\%APP_NAME%.exe
 echo Icon: %ICON_FILE%
 echo ============================================================

echo.
echo [1/8] Checking Windows Python build environment...
where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python Launcher for Windows was not found.
    echo Install 64-bit Python 3.12 and enable the py launcher.
    goto :fail
)
py -3.12 -c "import struct,sys; print(sys.version); print('Architecture:',struct.calcsize('P')*8); sys.exit(0 if struct.calcsize('P')*8==64 else 1)"
if errorlevel 1 (
    echo ERROR: 64-bit Python 3.12 is required.
    goto :fail
)

if not exist "%ICON_FILE%" (
    echo ERROR: Existing project icon is missing: %ICON_FILE%
    goto :fail
)
if not exist "main.py" goto :missing_source
if not exist "OpenGDS.py" goto :missing_source
if not exist "backend.py" goto :missing_source
if not exist "app_info.py" goto :missing_source
if not exist "requirements.txt" goto :missing_source
if not exist "LICENSE" goto :missing_source

 echo.
echo [2/8] Creating isolated GUI build environment...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    py -3.12 -m venv "%VENV_DIR%"
    if errorlevel 1 goto :fail
)
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 goto :fail

 echo.
echo [3/8] Installing GUI and packaging dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
python -m pip install -r requirements.txt "PyInstaller>=6.10,<7" pefile
if errorlevel 1 goto :fail

 echo.
echo [4/8] Validating icon, source syntax and embedded-core wiring...
python -c "import pathlib,struct,sys; p=pathlib.Path(r'%ICON_FILE%'); b=p.read_bytes(); h=struct.unpack_from('<HHH',b); print('ICO directory:',h); sys.exit(0 if h[0]==0 and h[1]==1 and h[2]>0 else 1)"
if errorlevel 1 (
    echo ERROR: The existing ICO file is invalid.
    goto :fail
)
findstr /C:"--opengds-cli" backend.py >nul
if errorlevel 1 (
    echo ERROR: backend.py does not relaunch the embedded CLI through this executable.
    goto :fail
)
findstr /C:"_logged_cli_main" main.py >nul
if errorlevel 1 (
    echo ERROR: main.py is missing the embedded CLI dispatcher.
    goto :fail
)
python -c "import pathlib,py_compile; excluded={'.venv','build','dist','__pycache__','.git','node_modules','.tox'}; files=sorted(p for p in pathlib.Path('.').rglob('*.py') if not any(part in excluded or part.startswith('.build-venv') for part in p.parts)); print('Checking',len(files),'Python files'); [py_compile.compile(str(p),doraise=True) for p in files]; print('Python syntax check passed')"
if errorlevel 1 goto :fail

 echo.
echo [5/8] Running full project test suite...
where git >nul 2>nul
if errorlevel 1 echo NOTE: Git was not found. Git integration tests will be skipped; Git is optional for building OpenGDS-IDE.
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo ERROR: Project tests failed. Fix the failing test before packaging.
    goto :fail
)

 echo.
echo [6/8] Building the one-file GUI executable...
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if not exist "build\spec" mkdir "build\spec"

python -m PyInstaller --clean --noconfirm --onefile --windowed --name "%APP_NAME%" --icon "%ICON_FILE%" --distpath "%DIST_DIR%" --workpath "%BUILD_DIR%" --specpath "build\spec" --add-data "%CD%\assets;assets" --add-data "%CD%\LICENSE;." --collect-all PySide6 --collect-all shiboken6 --collect-all zstandard --hidden-import OpenGDS --hidden-import backend --hidden-import app_info --hidden-import archive_tools --hidden-import project_manager --hidden-import project_ops --hidden-import language_service --hidden-import lsp_client --hidden-import dap_client --hidden-import protocol --hidden-import logging_system --hidden-import ai_agent --hidden-import ai_panel --hidden-import git_service --hidden-import git_panel main.py
if errorlevel 1 goto :fail
if not exist "%DIST_DIR%\%APP_NAME%.exe" (
    echo ERROR: PyInstaller did not create the expected executable.
    goto :fail
)

 echo.
echo [7/8] Verifying embedded Windows icon resource...
python -c "import pefile,sys; p=pefile.PE(r'%DIST_DIR%\%APP_NAME%.exe'); ok=hasattr(p,'DIRECTORY_ENTRY_RESOURCE') and any(e.id==14 for e in p.DIRECTORY_ENTRY_RESOURCE.entries); print('GROUP_ICON resource:', 'FOUND' if ok else 'MISSING'); p.close(); sys.exit(0 if ok else 1)"
if errorlevel 1 (
    echo ERROR: The built executable does not contain the icon resource.
    goto :fail
)

 echo.
echo [8/8] Smoke-testing embedded OpenGDS compiler, inspector and decompiler...
if not exist "build\smoke" mkdir "build\smoke"
(
    echo extends Node
    echo.
    echo func _ready^(^):
    echo     print^("OpenGDS-IDE embedded-core smoke test"^)
) > "build\smoke\embedded_core_smoke.gd"
"%DIST_DIR%\%APP_NAME%.exe" --opengds-cli comp "build\smoke\embedded_core_smoke.gd" --no-compress --force > "build\smoke\compile.log" 2>&1
if errorlevel 1 (
    type "build\smoke\compile.log"
    echo ERROR: Embedded compiler smoke test failed.
    goto :fail
)
"%DIST_DIR%\%APP_NAME%.exe" --opengds-cli info "build\smoke\embedded_core_smoke.gdc" > "build\smoke\info.log" 2>&1
if errorlevel 1 (
    type "build\smoke\info.log"
    echo ERROR: Embedded GDSC inspection smoke test failed.
    goto :fail
)
"%DIST_DIR%\%APP_NAME%.exe" --opengds-cli dcmp "build\smoke\embedded_core_smoke.gdc" --output "build\smoke\roundtrip.gd" > "build\smoke\decompile.log" 2>&1
if errorlevel 1 (
    type "build\smoke\decompile.log"
    echo ERROR: Embedded decompiler smoke test failed.
    goto :fail
)
findstr /C:"OpenGDS-IDE embedded-core smoke test" "build\smoke\roundtrip.gd" >nul
if errorlevel 1 (
    echo ERROR: Embedded compile/decompile round trip failed.
    goto :fail
)

echo.
echo ============================================================
echo BUILD SUCCESSFUL
echo Output: %CD%\%DIST_DIR%\%APP_NAME%.exe
echo One-file: YES
echo Console: NO - GUI subsystem
echo Icon: Embedded and verified
echo OpenGDS core: Embedded and smoke-tested
echo Qt and Zstandard: Bundled
echo ============================================================
goto :success

:missing_source
echo ERROR: A required source file is missing from the project root.
goto :fail

:fail
echo.
echo BUILD FAILED. See the first error above.
pause
exit /b 1

:success
pause
exit /b 0
