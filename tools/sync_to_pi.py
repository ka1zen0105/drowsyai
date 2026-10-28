import sys
from pathlib import Path
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "192.168.8.116"
USER = "soham"
PASSWORD = "soham"

files_to_sync = [
    "features.py",
    "config.py",
    "config.yaml",
    "calibration.yaml",
    "fusion.py",
    "vision.py",
    "calibrate.py",
    "main.py",
    "alert.py",
]

print("Connecting to Pi...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD)

sftp = client.open_sftp()
for fname in files_to_sync:
    local_p = Path(fname)
    remote_p = f"/home/soham/drowsy/{fname}"
    if local_p.exists():
        print(f"Uploading {fname} -> {remote_p} ...")
        sftp.put(str(local_p), remote_p)
sftp.close()

print("Sync completed successfully.")
client.close()
