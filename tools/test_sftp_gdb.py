import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

sftp = client.open_sftp()
with sftp.file("/home/soham/drowsy/test_lm.py", "w") as f:
    f.write("""import mediapipe as mp
print("Testing FaceLandmarker...")
opts = mp.tasks.vision.FaceLandmarkerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path='models/face_landmarker.task')
)
detector = mp.tasks.vision.FaceLandmarker.create_from_options(opts)
print("SUCCESS: FaceLandmarker created on Raspberry Pi 4!")
detector.close()
""")
sftp.close()

stdin, stdout, stderr = client.exec_command(
    "gdb -batch -ex 'run' -ex 'bt' --args ~/drowsy/venv/bin/python3 ~/drowsy/test_lm.py",
    get_pty=True
)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
