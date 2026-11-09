"""Resolve a poetry.lock into a pinned requirements list for one dependency group.

poetry.lock v2 doesn't say which packages are dev-only, so we walk the dependency
graph ourselves from the groups declared in pyproject.toml, honouring extras and
environment markers for the target interpreter.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.markers import Marker


def canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _roots(pyproject: dict, group: str) -> dict[str, set[str]]:
    """Top-level deps for a group -> requested extras."""
    poetry = pyproject["tool"]["poetry"]
    tables = [poetry.get("dependencies", {})]
    if group == "all":
        tables += [g.get("dependencies", {}) for g in poetry.get("group", {}).values()]
        tables.append(poetry.get("dev-dependencies", {}))
    elif group != "main":
        tables = [poetry["group"][group]["dependencies"]]
    roots: dict[str, set[str]] = {}
    for table in tables:
        for name, spec in table.items():
            if name == "python":
                continue
            extras = set(spec.get("extras", [])) if isinstance(spec, dict) else set()
            roots.setdefault(canon(name), set()).update(extras)
    return roots


def _applies(spec, env: dict) -> bool:
    if isinstance(spec, list):                      # multiple constraints for different envs
        return any(_applies(s, env) for s in spec)
    if isinstance(spec, dict):
        if spec.get("optional"):
            return False
        if m := spec.get("markers"):
            return Marker(m).evaluate(env)
    return True


def export(project_dir: Path, group: str = "main", python: str = "3.11") -> list[str]:
    pyproject = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((project_dir / "poetry.lock").read_text(encoding="utf-8"))
    pkgs = {canon(p["name"]): p for p in lock["package"]}
    env = {"python_version": python, "python_full_version": f"{python}.0",
           "sys_platform": "linux", "platform_system": "Linux", "os_name": "posix",
           "platform_machine": "x86_64", "implementation_name": "cpython",
           "platform_python_implementation": "CPython", "extra": ""}

    seen: set[str] = set()
    stack = list(_roots(pyproject, group).items())
    while stack:
        name, extras = stack.pop()
        pkg = pkgs.get(name)
        if pkg is None:
            continue                                  # declared but not locked for this env
        first_visit = name not in seen
        seen.add(name)
        deps = {canon(d): s for d, s in pkg.get("dependencies", {}).items() if _applies(s, env)} if first_visit else {}
        for extra in extras:                          # "uvicorn[standard]" pulls extra deps
            for req in pkg.get("extras", {}).get(extra, []):
                deps[canon(re.split(r"[\s(;\[<>=!~]", req, maxsplit=1)[0])] = None
        for dep in deps:
            if dep not in seen:
                stack.append((dep, set()))
    return sorted(f"{pkgs[n]['name']}=={pkgs[n]['version']}" for n in seen)
