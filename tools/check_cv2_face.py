import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

py_code = """
import cv2
print("cv2 version:", cv2.__version__)
print("has FaceDetectorYN:", hasattr(cv2, 'FaceDetectorYN'))
print("has dnn:", hasattr(cv2, 'dnn'))
print("has cv2.face:", hasattr(cv2, 'face'))
if hasattr(cv2, 'face'):
    print("cv2.face contents:", dir(cv2.face))
"""

stdin, stdout, stderr = client.exec_command(
    f'~/drowsy/venv/bin/python3 -c "{py_code}"', get_pty=True
)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
