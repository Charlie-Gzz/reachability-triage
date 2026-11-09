import sys

from changelog.collect import commits_since, group

for section, items in group(commits_since(sys.argv[1])).items():
    if items:
        print(f"## {section}")
        print("\n".join(f"- {i}" for i in items))
