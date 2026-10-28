#!/bin/bash
# Driver Drowsiness Detection Auto-Start Launcher
sleep 3
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/$(id -u)

for i in {1..15}; do
    if ls /dev/video* 1> /dev/null 2>&1; then
        break
    fi
    sleep 1
done

cd /home/soham/drowsy
exec /home/soham/drowsy/venv/bin/python3 main.py --skip-calibration --buzzer-active-low >> /home/soham/drowsy/logs/autostart.log 2>&1
