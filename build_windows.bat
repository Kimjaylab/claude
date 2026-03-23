@echo off
echo Building NGIMU GUI...

where python >nul 2>&1
if %errorlevel% == 0 (
    set PY=python
) else (
    where py >nul 2>&1
    if %errorlevel% == 0 (
        set PY=py
    ) else (
        echo ERROR: Python not found. Install from https://python.org
        echo Make sure to check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
)

echo Using: %PY%
%PY% -m pip install pyinstaller
%PY% -m PyInstaller --onefile --windowed --name "NGIMU GUI" xio_to_csv_gui.py

echo.
echo Done! Check dist\NGIMU GUI.exe
pause
