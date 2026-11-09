import json
import sys

from inventory.collect import collect

print(json.dumps({h: collect(h, "ops") for h in sys.argv[1:]}, indent=2))
