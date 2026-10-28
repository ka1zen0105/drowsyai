"""Start the Driver Drowsiness Detection System on the Raspberry Pi over SSH."""

import sys
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOST = "192.168.8.116"
USER = "soham"
PASSWORD = "soham"


def main():
    print("=" * 65)
    print(f"Connecting to Raspberry Pi at {HOST}...")
    print("=" * 65)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=10)
        print("Connected!\n")
    except Exception as exc:
        print(f"Connection failed: {exc}")
        return 1

    try:
        # Check for camera devices
        stdin, stdout, stderr = client.exec_command("ls -l /dev/video*", get_pty=True)
        video_devs = stdout.read().decode("utf-8", errors="replace")
        print("Camera check (/dev/video*):")
        print(video_devs.strip() or "No /dev/video devices found.")

        # Launch command on the Pi screen
        extra_args = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "--skip-calibration --buzzer-active-low"
        if "--buzzer-active-low" not in extra_args:
            extra_args += " --buzzer-active-low"
        cmd = (
            "export DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000; "
            f"cd ~/drowsy && ~/drowsy/venv/bin/python3 main.py {extra_args}"
        )
        print(f"\n[Launching on Raspberry Pi]: {cmd}\n")

        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)

        for line in iter(stdout.readline, ""):
            print(line, end="", flush=True)

        exit_code = stdout.channel.recv_exit_status()
        print(f"\nProcess exited with code: {exit_code}")
        return exit_code
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
