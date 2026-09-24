@echo off
setlocal
cd /d "%~dp0"

echo Installing dependencies...
python -m pip install -r requirements.txt || exit /b 1

if not exist "output\combined_dashboard\combined_publications.parquet" (
    echo.
    echo Building combined dataset cache - this can take a few minutes on first run...
    python build_combined_dashboard_data.py || exit /b 1
)

echo.
echo Starting Combined VA Publications Dashboard...
python -m streamlit run combined_dashboard.py
