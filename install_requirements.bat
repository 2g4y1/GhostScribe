@echo off
setlocal enabledelayedexpansion
title GhostScribe - Installation ^& Requirements Setup
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   🎙️  GHOSTSCRIBE - INSTALLATION ^& SETUP DER BIBLIOTHEKEN
echo ============================================================
echo.

:: 1. Prüfen, ob Python vorhanden ist
set "PYTHON_CMD="
python --version >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
) else (
    py --version >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py"
    )
)

if "%PYTHON_CMD%"=="" (
    echo [FEHLER] Python wurde auf diesem Computer nicht gefunden!
    echo.
    echo GhostScribe benoetigt Python (empfohlen: Version 3.10 oder 3.11).
    echo.
    echo Installations-Optionen:
    echo  1) Direkt herunterladen: https://www.python.org/downloads/
    echo     WICHTIG: Setze beim Installer den Haken bei:
    echo     [x] "Add python.exe to PATH"
    echo.
    where winget >nul 2>nul
    if %errorlevel% equ 0 (
        echo  2) Automatische Windows-Installation via winget:
        echo     Fuehre in PowerShell oder CMD aus:
        echo     winget install Python.Python.3.11
    )
    echo.
    echo ============================================================
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do set "PY_VER=%%v"
echo [OK] Gefundenes Python: %PY_VER%
echo.

:: 2. Virtuelle Umgebung (.venv) anlegen, falls noch nicht vorhanden
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Erstelle isolierte Python-Umgebung in .venv ...
    %PYTHON_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [FEHLER] Konnte virtuelle Umgebung nicht erstellen.
        pause
        exit /b 1
    )
    echo      Erfolgreich erstellt.
) else (
    echo [1/3] Virtuelle Umgebung (.venv) ist bereits vorhanden.
)
echo.

:: 3. Pip aktualisieren & Requirements installieren
echo [2/3] Installiere benoetigte Bibliotheken (Audio, KI-SDK, Web-Server)...
echo      Dies kann beim ersten Mal 1-2 Minuten dauern. Bitte warten...
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\pip.exe install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [FEHLER] Paket-Installation fehlgeschlagen!
    echo Bitte Internetverbindung pruefen und dieses Skript erneut starten.
    pause
    exit /b 1
)

:: Marker-Datei schreiben
echo installed on %DATE% %TIME% > .venv\.installed
echo      Alle Pakete erfolgreich installiert.
echo.

:: 4. .env Datei vorbereiten, falls noch nicht vorhanden
echo [3/3] Pruefe Konfigurationsdateien...
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo      .env Konfigurationsdatei aus Vorlage (.env.example) erstellt.
    )
) else (
    echo      .env Datei bereits vorhanden.
)

:: Ordner anlegen
if not exist "meetings" mkdir "meetings"
if not exist "recordings" mkdir "recordings"

echo.
echo ============================================================
echo   ✅ INSTALLATION ERFOLGREICH ABGESCHLOSSEN!
echo ============================================================
echo.
echo GhostScribe ist jetzt einsatzbereit.
echo Du kannst die App nun jederzeit starten mit:
echo   -> start.bat
echo.
pause
