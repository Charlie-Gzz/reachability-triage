import argparse

from deployctl.settings import load_settings, write_settings


def main(argv=None):
    p = argparse.ArgumentParser(prog="deployctl")
    p.add_argument("env")
    p.add_argument("--set", nargs=2, action="append", default=[])
    args = p.parse_args(argv)
    settings = load_settings(args.env)
    for key, value in args.set:
        settings[key] = value
    write_settings(args.env, settings)
    print(f"{args.env}: {len(settings)} keys")


if __name__ == "__main__":
    main()
