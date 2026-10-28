import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

sftp = client.open_sftp()
with sftp.file("/home/soham/drowsy/test_lbf.py", "w") as f:
    f.write("""import cv2
print("OpenCV:", cv2.__version__)
facemark = cv2.face.createFacemarkLBF()
print("Loading lbfmodel.yaml...")
facemark.loadModel("/home/soham/drowsy/models/lbfmodel.yaml")
print("SUCCESS: lbfmodel.yaml loaded cleanly on Raspberry Pi 4!")
""")
sftp.close()

stdin, stdout, stderr = client.exec_command(
    "~/drowsy/venv/bin/python3 ~/drowsy/test_lbf.py", get_pty=True
)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
