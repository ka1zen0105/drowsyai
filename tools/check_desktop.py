import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

sftp = client.open_sftp()
with sftp.file("/home/soham/drowsy/env_check.py", "w") as f:
    f.write("""
import os, glob

for p in glob.glob('/proc/[0-9]*/environ'):
    try:
        data = open(p, 'rb').read().decode(errors='ignore').split('\\0')
        d = dict(item.split('=', 1) for item in data if '=' in item)
        if 'WAYLAND_DISPLAY' in d or 'DISPLAY' in d:
            print(f"PID {p.split('/')[2]}: DISPLAY={d.get('DISPLAY')} WAYLAND_DISPLAY={d.get('WAYLAND_DISPLAY')} XDG_RUNTIME_DIR={d.get('XDG_RUNTIME_DIR')}")
            break
    except Exception:
        pass
""")
sftp.close()

stdin, stdout, stderr = client.exec_command("~/drowsy/venv/bin/python3 ~/drowsy/env_check.py")
print(stdout.read().decode())
print(stderr.read().decode())
client.close()
