"""Tiny subprocess helpers. Every command is echoed so runs are auditable."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run(cmd: str | list[str], cwd: Path | None = None, env: dict | None = None,
        check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    shown = cmd if isinstance(cmd, str) else " ".join(cmd)
    print(f"+ {shown}" + (f"   (in {cwd})" if cwd else ""), file=sys.stderr)
    return subprocess.run(
        cmd, cwd=cwd, shell=isinstance(cmd, str), check=check, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, **(env or {})},
        capture_output=capture,
    )
