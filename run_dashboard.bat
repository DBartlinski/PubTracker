@echo off
setlocal
cd /d "%~dp0"

echo Installing dependencies...
python -m pip install -r requirements.txt || exit /b 1

echo.
echo Starting VA Publications Dashboard...
python -m streamlit run dashboard.py