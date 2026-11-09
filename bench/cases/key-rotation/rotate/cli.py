import argparse
from pathlib import Path

from rotate.keys import generate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("host")
    p.add_argument("--dir", default="~/.ssh/rotated")
    args = p.parse_args()
    pub = generate(Path(args.dir).expanduser() / args.host)
    print(pub)


if __name__ == "__main__":
    main()
