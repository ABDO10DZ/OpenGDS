@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=OpenGDS-IDE"
set "ICON_FILE=%CD%\assets\opengds-ide.ico"
set "VENV_DIR=.build-venv-gui"
set "DIST_DIR=dist"

echo ============================================================
echo OpenGDS-IDE - Windows x64 single-file GUI build
echo Output: %DIST_DIR%\%APP_NAME%.exe
echo ============================================================

echo.
echo [1/7] Checking the Windows Python build environment...
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python 3 was not found on PATH.
    echo Install 64-bit Python 3.10 or newer.
    goto :fail
)
python -c "import struct,sys; print(sys.version); print('Architecture:',struct.calcsize('P')*8); sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize('P')*8==64 else 1)"
if errorlevel 1 goto :fail

if not exist "%ICON_FILE%" (
    echo ERROR: Windows application icon is missing: %ICON_FILE%
    goto :fail
)
if not exist "main.py" goto :missing_source
if not exist "OpenGDS.py" goto :missing_source
if not exist "requirements.txt" goto :missing_source
if not exist "LICENSE" goto :missing_source

echo.
echo [2/7] Creating the isolated GUI build environment...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    python -m venv "%VENV_DIR%"
    if errorlevel 1 goto :fail
)
set "BUILD_PY=%CD%\%VENV_DIR%\Scripts\python.exe"

echo.
echo [3/7] Installing application and packaging dependencies...
"%BUILD_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%BUILD_PY%" -m pip install -r requirements.txt "PyInstaller>=6.10,<7" pefile
if errorlevel 1 goto :fail

echo.
echo [4/7] Checking Python syntax and running the full test suite...
"%BUILD_PY%" -c "import pathlib,py_compile; excluded={'.venv','build','dist','__pycache__','.git','node_modules','.tox'}; files=sorted(p for p in pathlib.Path('.').rglob('*.py') if not any(part in excluded or part.startswith('.build-venv') for part in p.parts)); print('Checking',len(files),'Python files'); [py_compile.compile(str(p),doraise=True) for p in files]; print('Python syntax check passed')"
if errorlevel 1 goto :fail
"%BUILD_PY%" -m unittest discover -s tests -v
if errorlevel 1 (
    echo ERROR: Project tests failed. Fix the failing test before packaging.
    goto :fail
)

echo.
echo [5/7] Building the Windows one-file GUI executable from the shared spec...
"%BUILD_PY%" -m PyInstaller --clean --noconfirm OpenGDS-IDE.spec
if errorlevel 1 goto :fail
if not exist "%DIST_DIR%\%APP_NAME%.exe" (
    echo ERROR: PyInstaller did not create the expected executable.
    goto :fail
)

echo.
echo [6/7] Verifying the embedded Windows icon resource...
"%BUILD_PY%" -c "import pefile,sys; p=pefile.PE(r'%DIST_DIR%\%APP_NAME%.exe'); ok=hasattr(p,'DIRECTORY_ENTRY_RESOURCE') and any(e.id==14 for e in p.DIRECTORY_ENTRY_RESOURCE.entries); print('GROUP_ICON resource:', 'FOUND' if ok else 'MISSING'); p.close(); sys.exit(0 if ok else 1)"
if errorlevel 1 goto :fail

echo.
echo [7/7] Smoke-testing the frozen application and embedded GDSC core...
"%BUILD_PY%" tests\smoke_frozen_bundle.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo BUILD SUCCESSFUL
echo Output: %CD%\%DIST_DIR%\%APP_NAME%.exe
echo Format: single-file GUI executable
echo Icon: embedded and verified
echo Core: compile, inspect and decompile smoke-tested
echo ============================================================
goto :success

:missing_source
echo ERROR: A required source file is missing from the project folder.
goto :fail

:fail
echo.
echo BUILD FAILED. See the first error above.
if /I not "%CI%"=="true" pause
exit /b 1

:success
if /I not "%CI%"=="true" pause
exit /b 0
