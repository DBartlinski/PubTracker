@echo off
setlocal
cd /d "%~dp0"

echo Installing dependencies...
python -m pip install -r requirements.txt || exit /b 1
python -m playwright install chromium || exit /b 1

echo.
echo Starting VA Dimensions batch export...
python dimensions_batch_export.py

if errorlevel 1 (
    echo.
    echo Export did not complete. Review the message above, then run this file again to resume.
    pause
    exit /b 1
)

echo.
echo Export complete. See output\dimensions_batches\dimensions_merged.csv
pause