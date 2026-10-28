import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

py_code = (
    "import os, mediapipe as mp; "
    "opts = mp.tasks.vision.FaceLandmarkerOptions("
    "base_options=mp.tasks.BaseOptions(model_asset_path='models/face_landmarker.task')); "
    "print('creating landmarker...'); "
    "d = mp.tasks.vision.FaceLandmarker.create_from_options(opts); "
    "print('SUCCESS!')"
)

cmd = f"cd ~/drowsy && GODEBUG=cpu.aes=off ~/drowsy/venv/bin/python3 -c \"{py_code}\""
stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
