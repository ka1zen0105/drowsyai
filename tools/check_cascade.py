import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

py_code = """import os, cv2
path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
print('cascade path:', path)
print('exists:', os.path.exists(path))
"""

stdin, stdout, stderr = client.exec_command(f'~/drowsy/venv/bin/python3 -c "{py_code}"', get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
