import paramiko

COMMANDS = {"kernel": "uname -r", "uptime": "uptime -p", "disk": "df -h /"}


def collect(host: str, user: str) -> dict:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.load_system_host_keys()
    client.connect(host, username=user, timeout=10)
    try:
        out = {}
        for name, cmd in COMMANDS.items():
            _, stdout, _ = client.exec_command(cmd)
            out[name] = stdout.read().decode().strip()
        return out
    finally:
        client.close()
