@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo                 OpenGDS-IDE - Windows
echo ============================================================

set "PY_LAUNCHER=python"
where py >nul 2>nul
if not errorlevel 1 set "PY_LAUNCHER=py -3"

if exist ".venv\Scripts\python.exe" goto :venv_ready
echo [1/4] Creating an isolated Python environment...
%PY_LAUNCHER% -m venv .venv
if errorlevel 1 goto :python_error

:venv_ready
if not exist ".venv\Scripts\python.exe" goto :python_error
echo [1/4] Python environment ready.

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto :version_error

".venv\Scripts\python.exe" -c "import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, PySide6.QtNetwork, zstandard" >nul 2>nul
if not errorlevel 1 goto :dependencies_ready
echo [2/4] Installing OpenGDS-IDE dependencies: PySide6, Qt and Zstandard.
echo       An internet connection is required for the first installation.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 echo WARNING: pip could not be upgraded. Continuing with the bundled pip.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :pip_error

:dependencies_ready
echo [3/4] Verifying the GUI dependencies...
".venv\Scripts\python.exe" -c "import PySide6, zstandard; from PySide6.QtWidgets import QApplication; from PySide6.QtNetwork import QTcpSocket; print('PySide6', PySide6.__version__, 'OK; Zstandard', zstandard.__version__, 'OK')"
if errorlevel 1 goto :verify_error

if /I "%~1"=="--setup-only" goto :setup_complete

echo [4/4] Starting OpenGDS-IDE...
".venv\Scripts\python.exe" main.py %*
set "APP_EXIT=%ERRORLEVEL%"
if "%APP_EXIT%"=="0" exit /b 0
echo.
echo OpenGDS-IDE exited with code %APP_EXIT%.
echo Startup details are saved in: %USERPROFILE%\.opengds-ide\logs\startup-crash.log
echo Application logs are saved in: %USERPROFILE%\.opengds-ide\logs\opengds-ide.log
pause
exit /b %APP_EXIT%

:setup_complete
echo.
echo Setup complete. Start the IDE by double-clicking launch_windows.bat.
exit /b 0

:python_error
echo.
echo ERROR: Python 3 could not create the virtual environment.
echo Install Python 3.10 or newer and enable the Python Launcher or PATH option.
pause
exit /b 10

:version_error
echo.
echo ERROR: OpenGDS-IDE requires Python 3.10 or newer.
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
echo ERROR: PySide6 or Zstandard failed the import verification.
echo Try deleting the .venv folder and run launch_windows.bat again.
pause
exit /b 13
