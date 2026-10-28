@echo off
cd /d "%~dp0"
echo =================================================================
echo   DRIVER DROWSINESS DETECTION SYSTEM (LAPTOP SIMULATION)
echo =================================================================
echo   Press SPACE or S to acknowledge an alert
echo   Press Q or ESC in the video window to quit
echo =================================================================
echo.
py -3.12 main.py --simulate %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Process exited with code %ERRORLEVEL%.
    pause
)
