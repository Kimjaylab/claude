@echo off
echo Building NGIMU GUI...

python -m pip install pyinstaller

python -m PyInstaller --onefile --windowed --name "NGIMU GUI" xio_to_csv_gui.py

echo.
echo Done! Check dist\NGIMU GUI.exe
pause
