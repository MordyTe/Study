@echo off
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py -3
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Install Python 3.12 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during installation.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run - creating the environment...
  %PY% -m venv .venv || goto :err
)

rem (Re)install whenever requirements.txt changed since the last install.
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
  echo Installing / updating components, this takes a few minutes...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt || goto :err
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

start "" ".venv\Scripts\pythonw.exe" speaker_transcriber.py
exit /b 0

:err
echo Installation failed. See the messages above.
pause
exit /b 1
