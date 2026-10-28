import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

sftp = client.open_sftp()
with sftp.file("/home/soham/drowsy/test_pipe.py", "w") as f:
    f.write("""import os, cv2, numpy as np
print("Testing OpenCV cascade + Facemark...")
cascade = cv2.CascadeClassifier("/home/soham/drowsy/models/haarcascade_frontalface_default.xml")
facemark = cv2.face.createFacemarkLBF()
facemark.loadModel("/home/soham/drowsy/models/lbfmodel.yaml")

# Test on synthetic frame
frame = np.zeros((480, 640, 3), dtype=np.uint8)
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
faces = cascade.detectMultiScale(gray, 1.1, 4)
print("Cascade executed, found faces:", len(faces))
print("SUCCESS: Full OpenCV facial landmark pipeline initialized on Raspberry Pi 4!")
""")
sftp.close()

stdin, stdout, stderr = client.exec_command(
    "~/drowsy/venv/bin/python3 ~/drowsy/test_pipe.py", get_pty=True
)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
