@echo off
setlocal enabledelayedexpansion
title GhostScribe - Portables ZIP-Paket erstellen
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   📦 GHOSTSCRIBE - PORTABLES ZIP-PAKET ERSTELLEN
echo ============================================================
echo.

if exist ".venv\Scripts\python.exe" (
    .\.venv\Scripts\python.exe create_portable_zip.py
) else (
    python create_portable_zip.py
)

if %errorlevel% neq 0 (
    echo.
    echo [FEHLER] Paket-Erstellung fehlgeschlagen.
    pause
    exit /b 1
)

echo.
echo Druecke eine beliebige Taste zum Beenden...
pause >nul
