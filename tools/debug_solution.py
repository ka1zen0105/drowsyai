import sys
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

test_script = """
import mediapipe as mp
print('testing mp.solutions.face_mesh...')
try:
    fm = mp.solutions.face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    print('mp.solutions.face_mesh created OK!')
except Exception as e:
    print('Error:', e)
"""

stdin, stdout, stderr = client.exec_command(
    f"cd ~/drowsy && ~/drowsy/venv/bin/python3 -c \"{test_script}\"", get_pty=True
)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
