@echo off
echo NGIMU GUI 빌드 시작...

pip install pyinstaller

pyinstaller --onefile --windowed --name "NGIMU GUI" xio_to_csv_gui.py

echo.
echo 완료! dist\NGIMU GUI.exe 를 확인하세요.
pause
