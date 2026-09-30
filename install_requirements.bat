@echo off
setlocal
cd /d "%~dp0"

rem GhostScribe setup: creates .venv and installs the Python dependencies.
rem Runs from start.bat ("/nopause") or on its own via double-click.

echo ============================================================
echo   GhostScribe - Einrichtung
echo ============================================================
echo.

rem Python 3.11+ suchen. Zuerst der py-Launcher, weil "python" auch der
rem Microsoft-Store-Platzhalter ohne echte Installation sein kann.
set "PYTHON_CMD="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD goto :no_python
for /f "delims=" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [1/3] %%v gefunden.

if exist ".venv\Scripts\python.exe" goto :install
echo [2/3] Erstelle die virtuelle Umgebung .venv ...
%PYTHON_CMD% -m venv .venv || goto :failed

:install
echo [3/3] Installiere die Bibliotheken, beim ersten Mal dauert das 1-2 Minuten ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check || goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check || goto :failed
copy /y requirements.txt ".venv\installed-requirements.txt" >nul
if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo Einrichtung abgeschlossen. GhostScribe startet mit start.bat
if /i not "%~1"=="/nopause" pause
exit /b 0

:no_python
echo [FEHLER] Python 3.11 oder neuer wurde nicht gefunden.
echo.
echo Download: https://www.python.org/downloads/
echo Im Installer "Add python.exe to PATH" anhaken, oder in PowerShell:
echo   winget install Python.Python.3.12
goto :end_failed

:failed
echo.
echo [FEHLER] Die Einrichtung ist fehlgeschlagen. Bitte die Internetverbindung
echo pruefen und das Skript erneut starten.

:end_failed
if /i not "%~1"=="/nopause" pause
exit /b 1
