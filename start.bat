@echo off
setlocal enabledelayedexpansion
title GhostScribe - Bot-Free Meeting Recorder (Server-Fenster)
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

echo ============================================================
echo   🎙️  GHOSTSCRIBE - BOT-FREE AI MEETING RECORDER
echo ============================================================
echo.

:: 1. Pruefen, ob die Umgebung bereits eingerichtet ist
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Erster Start erkannt. Richte portable Umgebung automatisch ein...
    echo       (Es werden KEINE Administrator-Rechte benoetigt)
    echo.
    call "%~dp0install_requirements.bat"
    if %errorlevel% neq 0 (
        echo [FEHLER] Einrichtung fehlgeschlagen.
        pause
        exit /b 1
    )
) else if not exist ".venv\.installed" (
    echo [INFO] Fehlende Bibliotheken erkannt. Aktualisiere Pakete...
    echo.
    call "%~dp0install_requirements.bat"
    if %errorlevel% neq 0 (
        echo [FEHLER] Einrichtung fehlgeschlagen.
        pause
        exit /b 1
    )
)

:: 2. Sicherstellen, dass .env existiert
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
    )
)

:: 3. Notwendige Ordner anlegen
if not exist "meetings" mkdir "meetings"
if not exist "recordings" mkdir "recordings"

:: 4. GhostScribe starten
cls
echo ============================================================
echo   🎙️  GHOSTSCRIBE LÄUFT AKTIV!
echo ============================================================
echo.
echo   🌐 Web-Oberflaeche:  http://localhost:8765
echo   (Dein Browser oeffnet sich automatisch in Kuerze)
echo.
echo ------------------------------------------------------------
echo   🛑 SO BEENDEST DU GHOSTSCRIBE:
echo      * Schliesse einfach dieses Fenster (X oben rechts)
echo      * ODER druecke [Strg] + [C] in diesem Fenster
echo ------------------------------------------------------------
echo.
echo [SERVER-LOGS]:

.\.venv\Scripts\python.exe main.py

echo.
echo ============================================================
echo   🛑 GhostScribe Server wurde beendet.
echo ============================================================
echo.
echo Druecke eine beliebige Taste, um dieses Fenster zu schliessen...
pause >nul
