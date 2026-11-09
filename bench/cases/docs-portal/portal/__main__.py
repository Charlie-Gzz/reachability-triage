import json
import sys

from portal.render import build

if __name__ == "__main__":
    build(json.load(open(sys.argv[1])))
