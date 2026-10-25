@echo off
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py -3
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during installation.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run - installing, this takes a few minutes...
  %PY% -m venv .venv || goto :err
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
)

start "" ".venv\Scripts\pythonw.exe" speaker_transcriber.py
exit /b 0

:err
echo Installation failed. See the messages above.
pause
exit /b 1
