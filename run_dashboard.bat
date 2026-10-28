@echo off
cd /d "%~dp0"
echo =================================================================
echo   DRIVER DROWSINESS DETECTION - UNIFIED WEB APP & DASHBOARD
echo =================================================================
echo   Opening live dashboard in your browser at http://127.0.0.1:8000
echo   Live camera feed, face dots, telemetry chart and log table
echo =================================================================
echo.
py -3.12 dashboard.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Process exited with code %ERRORLEVEL%.
    pause
)
