@echo off
title Hotel Manager Server
cd /d "%~dp0"
echo ========================================
echo   Hotel Manager - Starting Server...
echo ========================================
echo.
echo  URL: http://localhost:8000
echo  Username: admin
echo  Password: admin1234
echo.
echo  Press Ctrl+C to stop the server
echo ========================================
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
