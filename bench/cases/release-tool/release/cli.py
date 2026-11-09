import argparse

import pkg_resources

from release.bump import bump


def main():
    p = argparse.ArgumentParser()
    p.add_argument("part", choices=["major", "minor", "patch"])
    args = p.parse_args()
    current = pkg_resources.get_distribution("release-tool").version
    print(bump(current, args.part))


if __name__ == "__main__":
    main()
