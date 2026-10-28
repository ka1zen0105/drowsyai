import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

sftp = client.open_sftp()
with sftp.file("/home/soham/drowsy/probe.py", "w") as f:
    f.write("""import cv2
print("cv2 version:", cv2.__version__)
print("has FaceDetectorYN:", hasattr(cv2, 'FaceDetectorYN'))
print("has dnn:", hasattr(cv2, 'dnn'))
print("has cv2.face:", hasattr(cv2, 'face'))
if hasattr(cv2, 'face'):
    print("createFacemarkLBF:", hasattr(cv2.face, 'createFacemarkLBF'))
    print("createFacemarkKazemi:", hasattr(cv2.face, 'createFacemarkKazemi'))
""")
sftp.close()

stdin, stdout, stderr = client.exec_command(
    "~/drowsy/venv/bin/python3 ~/drowsy/probe.py", get_pty=True
)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
