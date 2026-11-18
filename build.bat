@echo off
setlocal
cd /d "%~dp0"
echo === PC Free Space: generando el .exe ===
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo No se encuentra Python. Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv || goto :error
)
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller || goto :error
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name PCFreeSpace --icon assets\icon.ico --add-data "assets\icon.ico;." --collect-data customtkinter app\main.py || goto :error
echo.
echo Listo: %CD%\dist\PCFreeSpace.exe
pause
exit /b 0
:error
echo Ha fallado la compilacion. Revisa los mensajes de arriba.
pause
exit /b 1
