#!/usr/bin/env bash
# Genera PC Free Space para macOS (.app) o Linux (binario único).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null || { echo "No se encuentra Python 3.10+"; exit 1; }
"$PY" -c "import tkinter" 2>/dev/null || {
  echo "Falta tkinter. En Ubuntu/Debian: sudo apt install python3-tk  ·  En macOS: brew install python-tk"; exit 1; }
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt pyinstaller pillow
if [ "$(uname)" = "Darwin" ]; then
  .venv/bin/python -m PyInstaller --noconfirm --clean --windowed --name PCFreeSpace \
    --icon assets/icon.png --add-data "assets/icon.png:." --collect-data customtkinter app/main.py
  echo "Listo: $PWD/dist/PCFreeSpace.app"
else
  .venv/bin/python -m PyInstaller --noconfirm --clean --onefile --windowed --name PCFreeSpace \
    --add-data "assets/icon.png:." --collect-data customtkinter app/main.py
  echo "Listo: $PWD/dist/PCFreeSpace"
fi
