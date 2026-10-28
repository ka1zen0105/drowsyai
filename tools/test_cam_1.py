import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

sftp = client.open_sftp()
with sftp.file("/home/soham/drowsy/probe_cam.py", "w") as f:
    f.write("""
import cv2

for idx in [1, 0, 2]:
    print(f"Testing index {idx}:")
    cap = cv2.VideoCapture(idx)
    opened = cap.isOpened()
    ret, frame = cap.read() if opened else (False, None)
    print(f"  opened={opened}, ret={ret}, shape={frame.shape if ret else None}")
    cap.release()
""")
sftp.close()

stdin, stdout, stderr = client.exec_command("~/drowsy/venv/bin/python3 ~/drowsy/probe_cam.py")
print(stdout.read().decode())
client.close()
