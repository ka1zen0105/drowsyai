import paramiko
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "192.168.8.116"
USER = "soham"
PASSWORD = "soham"

print("=" * 65)
print("Connecting to Raspberry Pi to run Driver Calibration...")
print("=" * 65)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD)

# 1. Ensure background service is stopped so camera is released
print("[1] Releasing camera (stopping background service)...")
stdin, stdout, stderr = client.exec_command("systemctl --user stop drowsy.service", get_pty=True)
stdout.read()

# 2. Run calibration with 15 second duration on the connected display
print("[2] Running calibration (15 seconds) on Pi display...")
cmd = "export DISPLAY=:0; cd ~/drowsy && ~/drowsy/venv/bin/python3 calibrate.py --duration 15"
stdin, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=90)

while True:
    line = stdout.readline()
    if not line:
        break
    try:
        print(line, end="", flush=True)
    except Exception:
        print(line.encode("ascii", errors="replace").decode("ascii"), end="", flush=True)

exit_code = stdout.channel.recv_exit_status()
print(f"\n[Calibration exit code: {exit_code}]")

# 3. Read saved calibration.yaml
sftp = client.open_sftp()
with sftp.open("/home/soham/drowsy/calibration.yaml", "r") as f:
    cal_content = f.read().decode("utf-8")
    print("\n--- New calibration.yaml ---")
    print(cal_content)
# Download to local PC as well
with open("c:/drowsy/calibration.yaml", "w", encoding="utf-8") as lf:
    lf.write(cal_content)
sftp.close()

# 4. Restart drowsy.service with the fresh calibration
print("\n[4] Restarting drowsy.service with newly calibrated profile...")
stdin, stdout, stderr = client.exec_command("systemctl --user restart drowsy.service", get_pty=True)
stdout.read()

print("=" * 65)
print("Calibration Complete & Monitoring Resumed!")
print("=" * 65)

client.close()
