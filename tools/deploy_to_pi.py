"""Remote deploy and setup script for Raspberry Pi over SSH."""

import sys
import time
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOST = "192.168.8.116"
USER = "soham"
PASSWORD = "soham"


def run_command(client: paramiko.SSHClient, cmd: str, sudo: bool = False, timeout: int = 900) -> int:
    display_cmd = cmd
    print(f"\n[SSH >>>] {display_cmd}")
    
    if sudo:
        full_cmd = f"echo '{PASSWORD}' | sudo -S -p '' bash -c '{cmd}'"
    else:
        full_cmd = cmd

    stdin, stdout, stderr = client.exec_command(full_cmd, timeout=timeout, get_pty=True)

    while True:
        line = stdout.readline()
        if not line:
            break
        # Print safely with UTF-8 replacement
        try:
            print(line, end="", flush=True)
        except Exception:
            print(line.encode("ascii", errors="replace").decode("ascii"), end="", flush=True)

    exit_code = stdout.channel.recv_exit_status()
    print(f"\n[Exit code: {exit_code}]")
    return exit_code


def main() -> int:
    print("=" * 65)
    print(f"Connecting to Raspberry Pi at {HOST} as '{USER}'...")
    print("=" * 65)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=15)
        print("Connected successfully!\n")
    except Exception as exc:
        print(f"Failed to connect to {HOST}: {exc}")
        return 1

    try:
        # Step 1: Wait for any background dpkg lock to release, then update & install system packages
        print("=== STEP 1: Installing system packages (apt) ===")
        # Wait for any apt lock in case user had an apt command open
        run_command(
            client,
            "while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do echo 'Waiting for dpkg lock...'; sleep 2; done; "
            "apt update && apt install -y git python3-pip python3-venv python3-gpiozero python3-lgpio libgl1 libglib2.0-0",
            sudo=True,
            timeout=600,
        )

        # Step 2: Clone or pull git repo
        print("\n=== STEP 2: Cloning or updating repository ===")
        run_command(
            client,
            "if [ -d ~/drowsy/.git ]; then cd ~/drowsy && git pull; else cd ~ && git clone https://github.com/ka1zen0105/drowsy.git; fi",
        )

        # Step 3: Setup virtual environment
        print("\n=== STEP 3: Setting up Python virtual environment ===")
        run_command(
            client,
            "if [ ! -d ~/drowsy/venv ]; then python3 -m venv --system-site-packages ~/drowsy/venv; fi",
        )

        # Step 4: Install pip dependencies
        print("\n=== STEP 4: Installing requirements via pip ===")
        run_command(
            client,
            "~/drowsy/venv/bin/pip install --upgrade pip --progress-bar off && "
            "~/drowsy/venv/bin/pip install -r ~/drowsy/requirements.txt --progress-bar off",
            timeout=900,
        )

        # Step 5: Run tests on Raspberry Pi
        print("\n=== STEP 5: Running pytest suite on Raspberry Pi ===")
        test_code = run_command(
            client,
            "cd ~/drowsy && ~/drowsy/venv/bin/pytest tests/ -v",
            timeout=180,
        )

        print("\n" + "=" * 65)
        if test_code == 0:
            print(">>> DEPLOYMENT & TESTING SUCCESSFUL ON RASPBERRY PI 4! <<<")
        else:
            print("Deployment completed with test exit code:", test_code)
        print("=" * 65)
        return test_code

    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
