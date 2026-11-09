import re

from git import Repo

TYPES = {"feat": "Features", "fix": "Fixes", "perf": "Performance"}


def commits_since(tag: str, path: str = "."):
    repo = Repo(path)
    return list(repo.iter_commits(f"{tag}..HEAD"))


def group(commits) -> dict:
    out = {v: [] for v in TYPES.values()}
    for c in commits:
        m = re.match(r"(\w+)(\(.+\))?: (.+)", c.summary)
        if m and m.group(1) in TYPES:
            out[TYPES[m.group(1)]].append(m.group(3))
    return out
