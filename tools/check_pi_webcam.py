import sys
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

print("=" * 65)
print("Raspberry Pi 4 - Webcam Hardware Diagnostic")
print("=" * 65)

# 1. lsusb
print("\n[1] USB Devices (lsusb):")
stdin, stdout, stderr = client.exec_command("lsusb", get_pty=True)
for line in stdout:
    if any(k in line.lower() for k in ["cam", "video", "sonix", "logi", "uvc", "device"]):
        print("  " + line.strip())

# 2. /dev/video*
print("\n[2] Video Device Nodes (/dev/video*):")
stdin, stdout, stderr = client.exec_command("ls -l /dev/video[0-1]* 2>/dev/null", get_pty=True)
print(stdout.read().decode("utf-8", errors="replace").strip())

# 3. OpenCV frame grab test
print("\n[3] Live OpenCV Frame Capture Test (/dev/video0):")
py_test = """
import cv2, numpy as np
cap = cv2.VideoCapture(0)
opened = cap.isOpened()
ret, frame = cap.read() if opened else (False, None)
cap.release()

print(f"  • VideoCapture(0) Opened : {opened}")
print(f"  • Frame Captured (ret)  : {ret}")
if ret and frame is not None:
    print(f"  • Resolution            : {frame.shape[1]}x{frame.shape[0]} (Channels: {frame.shape[2]})")
    print(f"  • Mean Pixel Brightness : {np.mean(frame):.2f} / 255.0")
else:
    print("  • Error: Could not read a frame from /dev/video0")
"""

sftp = client.open_sftp()
with sftp.file("/home/soham/drowsy/cam_test.py", "w") as f:
    f.write(py_test)
sftp.close()

stdin, stdout, stderr = client.exec_command(
    "~/drowsy/venv/bin/python3 ~/drowsy/cam_test.py", get_pty=True
)
print(stdout.read().decode("utf-8", errors="replace"))

print("=" * 65)
client.close()
