import paramiko
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

# First stop drowsy.service so the camera /dev/video0 is not locked
stdin, stdout, stderr = client.exec_command("systemctl --user stop drowsy.service", get_pty=True)
stdout.read()

py_code = """
import cv2, time
import numpy as np
from vision import FaceMeshDetector, CameraReader, process_frame
from config import load_config

cfg = load_config()
det = FaceMeshDetector()
cam = CameraReader(cfg.camera).start()
time.sleep(0.5)

ears, mars, pitches, rolls, yaws = [], [], [], [], []
for f_id in range(60):
    ret, frame = cam.read()
    if not ret or frame is None: 
        time.sleep(0.02)
        continue
    rec = process_frame(det, frame, f_id)
    if rec.face_found:
        ears.append(rec.ear_avg)
        mars.append(rec.mar)
        pitches.append(rec.pitch_deg)
        rolls.append(rec.roll_deg)
        yaws.append(rec.yaw_deg)
    time.sleep(0.04)

cam.stop()
det.close()

if ears:
    print(f"Total face samples collected: {len(ears)}")
    print(f"EAR:   min={min(ears):.4f}, max={max(ears):.4f}, median={float(np.median(ears)):.4f}")
    print(f"MAR:   min={min(mars):.4f}, max={max(mars):.4f}, median={float(np.median(mars)):.4f}")
    print(f"Pitch: min={min(pitches):.2f}, max={max(pitches):.2f}, median={float(np.median(pitches)):.2f}")
    print(f"Roll:  min={min(rolls):.2f}, max={max(rolls):.2f}, median={float(np.median(rolls)):.2f}")
    print(f"Yaw:   min={min(yaws):.2f}, max={max(yaws):.2f}, median={float(np.median(yaws)):.2f}")
else:
    print("NO FACE FOUND in 80 frames!")
"""

sftp = client.open_sftp()
with sftp.open("/home/soham/drowsy/probe_tmp.py", "w") as f:
    f.write(py_code)
sftp.close()

stdin, stdout, stderr = client.exec_command("cd ~/drowsy && ~/drowsy/venv/bin/python3 ~/drowsy/probe_tmp.py", get_pty=True)
output = stdout.read().decode("utf-8", errors="replace")
print(output)

client.close()
