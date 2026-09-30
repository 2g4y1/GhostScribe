@echo off
setlocal
cd /d "%~dp0"

rem GhostScribe setup: creates .venv and installs the Python dependencies.
rem Runs from start.bat ("/nopause") or on its own via double-click.

echo ============================================================
echo   GhostScribe - Setup
echo ============================================================
echo.

rem Look for Python 3.11+. The py launcher comes first because "python"
rem can also be the Microsoft Store placeholder without a real installation.
set "PYTHON_CMD="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD goto :no_python
for /f "delims=" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [1/3] Found %%v.

if exist ".venv\Scripts\python.exe" goto :install
echo [2/3] Creating the virtual environment .venv ...
%PYTHON_CMD% -m venv .venv || goto :failed

:install
echo [3/3] Installing the libraries, the first time takes 1-2 minutes ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check || goto :failed
rem Every package is pinned with its checksum: a changed or tampered download is rejected
".venv\Scripts\python.exe" -m pip install --require-hashes -r requirements.txt --disable-pip-version-check || goto :failed
copy /y requirements.txt ".venv\installed-requirements.txt" >nul
if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo Setup complete. Start GhostScribe with start.bat
if /i not "%~1"=="/nopause" pause
exit /b 0

:no_python
echo [ERROR] Python 3.11 or newer was not found.
echo.
echo Download: https://www.python.org/downloads/
echo In the installer, tick "Add python.exe to PATH", or run in PowerShell:
echo   winget install Python.Python.3.12
goto :end_failed

:failed
echo.
echo [ERROR] Setup failed. Please check the internet connection and run
echo this script again.

:end_failed
if /i not "%~1"=="/nopause" pause
exit /b 1
