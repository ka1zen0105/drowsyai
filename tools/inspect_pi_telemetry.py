import paramiko
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.8.116", username="soham", password="soham")

py_code = """
import csv

with open('/home/soham/drowsy/logs/telemetry.csv', 'r') as f:
    r = csv.DictReader(f)
    rolls = []
    yaws = []
    pitches = []
    flags = []
    for row in r:
        if row.get('face_found') in ('1', 'True'):
            try:
                rolls.append(float(row['roll_deg']))
                yaws.append(float(row['yaw_deg']))
                pitches.append(float(row['pitch_deg']))
                flags.append(int(row['head_flag']))
            except Exception:
                pass

if rolls:
    print(f"Total face samples: {len(rolls)}")
    print(f"Roll  min={min(rolls):.1f}, max={max(rolls):.1f}, avg={sum(rolls)/len(rolls):.1f}")
    print(f"Yaw   min={min(yaws):.1f}, max={max(yaws):.1f}, avg={sum(yaws)/len(yaws):.1f}")
    print(f"Pitch min={min(pitches):.1f}, max={max(pitches):.1f}, avg={sum(pitches)/len(pitches):.1f}")
    print(f"Head flag count: {sum(flags)}")
else:
    print("No face samples found")

with open('/home/soham/drowsy/calibration.yaml', 'r') as f:
    print('Pi calibration.yaml:')
    print(f.read())
"""

sftp = client.open_sftp()
with sftp.open('/home/soham/drowsy/inspect_tmp.py', 'w') as f:
    f.write(py_code)
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /home/soham/drowsy/inspect_tmp.py", get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
