"""Paths and targets.yaml, loaded into plain dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".work"            # osv-scanner binary, advisory DB, indexes, caches (gitignored)
WORKDIRS = ROOT / "workdirs"     # cloned target apps + remediation worktrees (gitignored)
LOCKS = ROOT / "locks"           # frozen runtime dependency sets (committed)
DATA = ROOT / "data"             # raw scanner output, findings, baselines, labels (committed)
RUNS = ROOT / "runs"             # cached agent run records per config (committed)
BENCH = ROOT / "bench"           # synthetic benchmark apps + labels (committed)
EVAL = ROOT / "eval"             # eval configs + results (committed)
ASSETS = ROOT / "assets"
SITE = ROOT / "site"
DOCS = ROOT / "docs"


@dataclass
class Target:
    name: str
    url: str
    ref: str
    commit: str
    framework: str
    python: str
    declared: dict
    runtime_install: list[str]
    test_install: list[str]
    test_cmd: str
    license: str = ""
    system_packages: list[str] = field(default_factory=list)
    app_dirs: list[str] = field(default_factory=list)   # first-party source dirs (code index + static analysis)
    test_dirs: list[str] = field(default_factory=list)

    @property
    def checkout(self) -> Path:
        return WORKDIRS / self.name

    @property
    def lockfile(self) -> Path:
        return LOCKS / f"{self.name}.runtime.txt"

    @property
    def test_lockfile(self) -> Path:
        return LOCKS / f"{self.name}.test-env.txt"

    @property
    def image(self) -> str:
        return f"rt-target-{self.name}:latest"


@dataclass
class Config:
    osv_scanner_version: str
    advisory_db: dict
    targets: list[Target]

    def target(self, name: str) -> Target:
        for t in self.targets:
            if t.name == name:
                return t
        raise SystemExit(f"unknown target {name!r}; known: {[t.name for t in self.targets]}")


def load(path: Path = ROOT / "targets.yaml") -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config(
        osv_scanner_version=raw["scanner"]["osv_scanner_version"],
        advisory_db=raw["advisory_db"],
        targets=[Target(**t) for t in raw["targets"]],
    )
