from pathlib import Path

import paramiko


def generate(path: Path, bits: int = 3072) -> str:
    key = paramiko.RSAKey.generate(bits)
    path.parent.mkdir(parents=True, exist_ok=True)
    key.write_private_key_file(str(path))
    return f"{key.get_name()} {key.get_base64()}"
