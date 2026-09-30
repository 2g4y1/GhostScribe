@echo off
setlocal
cd /d "%~dp0"
title GhostScribe
set "PYTHONUTF8=1"

rem Einrichtung beim ersten Start und immer dann, wenn sich requirements.txt geaendert hat
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul || call "%~dp0install_requirements.bat" /nopause || goto :failed

".venv\Scripts\python.exe" main.py || pause
exit /b

:failed
echo.
echo GhostScribe konnte nicht eingerichtet werden.
pause
exit /b 1
