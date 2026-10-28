import sys
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

cmd = sys.argv[1] if len(sys.argv) > 1 else "uname -a"
stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
out = stdout.read().decode("utf-8", errors="replace")
print(out)
client.close()
