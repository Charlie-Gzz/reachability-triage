"""Download the pinned osv-scanner release binary for this OS into .work/bin."""
from __future__ import annotations

import os
import platform
import stat
import subprocess
import sys

import httpx

from ..config import WORK


def install_osv_scanner(version: str) -> str:
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}[platform.system()]
    arch = {"AMD64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}[platform.machine()]
    suffix = ".exe" if system == "windows" else ""
    dest = WORK / "bin" / f"osv-scanner{suffix}"
    if not dest.exists():
        url = (f"https://github.com/google/osv-scanner/releases/download/v{version}/"
               f"osv-scanner_{system}_{arch}{suffix}")
        print(f"downloading {url}", file=sys.stderr)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        if os.name != "nt":
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    out = subprocess.run([str(dest), "--version"], capture_output=True, text=True).stdout
    print(out.strip())
    return str(dest)
