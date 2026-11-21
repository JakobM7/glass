@echo off
rem Glass-Fenster unter Windows: Doppelklick genuegt.
rem Beim ersten Start werden Python (falls noetig, per winget) und PySide6 eingerichtet,
rem in %LOCALAPPDATA%\GlassWindow\venv. Glass selbst installiert das Fenster bei Bedarf.
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\GlassWindow\venv"
set "VPY=%VENV%\Scripts\python.exe"

if exist "%VPY%" "%VPY%" -c "import PySide6.QtWebEngineWidgets, segno" >nul 2>&1 && goto run

echo Glass wird einmalig eingerichtet ...
call :findpy
if defined PY goto havepy
echo Python 3 wurde nicht gefunden.
choice /C JN /M "Jetzt mit winget installieren"
if errorlevel 2 goto nopy
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :findpy
if not defined PY goto nopy

:havepy
if not exist "%VPY%" %PY% -m venv "%VENV%" || goto fail
echo Installiere PySide6 (ca. 200 MB) ...
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%VPY%" -m pip install --disable-pip-version-check PySide6 segno || goto fail

:run
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0glass-window.py" %*
exit /b 0

:findpy
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3" && exit /b 0
python -c "import sys" >nul 2>&1 && set "PY=python" && exit /b 0
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
exit /b 0

:nopy
echo Ohne Python 3 startet das Glass-Fenster nicht: https://www.python.org/downloads/
pause
exit /b 1

:fail
echo Einrichtung fehlgeschlagen, siehe Meldungen oben.
pause
exit /b 1
