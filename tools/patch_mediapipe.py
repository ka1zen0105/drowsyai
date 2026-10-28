import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

patch_code = """
path = '/home/soham/drowsy/venv/lib/python3.13/site-packages/mediapipe/tasks/c/libmediapipe.so'
arm64_ret = b'\\xc0\\x03\\x5f\\xd6'

# 1. Patch setup_dl_debug_hook at 0x04613260 with RET
offset = 0x04613260
with open(path, 'r+b') as f:
    f.seek(offset)
    orig = f.read(4)
    print(f'setup_dl_debug_hook at 0x{offset:x}: {orig.hex()}')
    f.seek(offset)
    f.write(arm64_ret)
    print('Patched setup_dl_debug_hook with RET!')

# 2. Patch cpu_feature_fail_fast at 0x045c10a0 with RET
offset_fail_fast = 0x045c10a0
with open(path, 'r+b') as f:
    f.seek(offset_fail_fast)
    f.write(arm64_ret)
    print('Patched cpu_feature_fail_fast with RET!')
"""

stdin, stdout, stderr = client.exec_command(f"python3 -c \"{patch_code}\"", get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))

# Now test FaceLandmarker!
test_code = (
    "import mediapipe as mp; "
    "opts = mp.tasks.vision.FaceLandmarkerOptions("
    "base_options=mp.tasks.BaseOptions(model_asset_path='models/face_landmarker.task')); "
    "print('Creating FaceLandmarker after both patches...'); "
    "detector = mp.tasks.vision.FaceLandmarker.create_from_options(opts); "
    "print('FaceLandmarker CREATED SUCCESSFULLY ON RASPBERRY PI 4!'); "
    "detector.close()"
)

cmd = f"cd ~/drowsy && ~/drowsy/venv/bin/python3 -c \"{test_code}\""
stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))

client.close()
