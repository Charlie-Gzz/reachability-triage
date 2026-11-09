import sys

from reader.feeds import fetch, parse_items

for item in parse_items(fetch(sys.argv[1])):
    print(f"{item['title']}  {item['link']}")
