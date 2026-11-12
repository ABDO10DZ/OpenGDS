@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo                 OpenGDS - IDE - Windows
echo ============================================================

set "PY_LAUNCHER=python"
where py >nul 2>nul
if not errorlevel 1 set "PY_LAUNCHER=py -3"

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating an isolated Python environment...
    %PY_LAUNCHER% -m venv .venv
    if errorlevel 1 goto :python_error
) else (
    echo [1/4] Reusing the existing .venv environment.
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto :version_error

".venv\Scripts\python.exe" -c "import PySide6; import PySide6.QtCore; import PySide6.QtGui; import PySide6.QtWidgets; import PySide6.QtNetwork; import zstandard" >nul 2>nul
if errorlevel 1 (
    echo [2/4] Installing OpenGDS - IDE dependencies (PySide6 / Qt / Zstandard)...
    echo       An internet connection is required for the first installation.
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :pip_error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :pip_error
) else (
    echo [2/4] PySide6, Qt and Zstandard are already installed.
)

echo [3/4] Verifying the GUI dependency...
".venv\Scripts\python.exe" -c "import PySide6, zstandard; from PySide6.QtWidgets import QApplication; from PySide6.QtNetwork import QTcpSocket; print('PySide6', PySide6.__version__, 'OK; Zstandard', zstandard.__version__, 'OK')"
if errorlevel 1 goto :verify_error

if /I "%~1"=="--setup-only" (
    echo.
    echo Setup complete. Start the IDE by double-clicking launch_windows.bat.
    exit /b 0
)

echo [4/4] Starting OpenGDS - IDE...
".venv\Scripts\python.exe" main.py %*
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo OpenGDS - IDE exited with code %APP_EXIT%.
    echo Check the detailed logs in your user profile's .opengds-studio\logs folder.
    pause
)
exit /b %APP_EXIT%

:python_error
echo.
echo ERROR: Python 3 could not create the virtual environment.
echo Install Python 3.10 or newer and enable the Python Launcher or PATH option.
pause
exit /b 10

:version_error
echo.
echo ERROR: OpenGDS - IDE requires Python 3.10 or newer.
echo Install Python 3.10+ and rerun this launcher.
pause
exit /b 11

:pip_error
echo.
echo ERROR: Dependency installation failed.
echo Check your internet connection, proxy/firewall, and Python installation.
echo You can retry by running launch_windows.bat again.
pause
exit /b 12

:verify_error
echo.
echo ERROR: PySide6 / Zstandard installation did not pass the import check.
echo Try deleting the .venv folder and run launch_windows.bat again.
pause
exit /b 13
