@echo off
setlocal
cd /d "%~dp0"
title GhostScribe
set "PYTHONUTF8=1"

rem Run the setup on the first start and whenever requirements.txt has changed
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul || call "%~dp0install_requirements.bat" /nopause || goto :failed

".venv\Scripts\python.exe" -m ghostscribe %* || pause
exit /b

:failed
echo.
echo GhostScribe could not be set up.
pause
exit /b 1
