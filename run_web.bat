@echo off
echo.
echo  PubTracker Compliance Report - Web App (local)
echo  ------------------------------------------------
echo  Opening: http://localhost:8080
echo  Press Ctrl+C to stop.
echo.
cd /d "%~dp0docs"
start "" http://localhost:8080
python -m http.server 8080
