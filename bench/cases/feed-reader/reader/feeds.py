import urllib.request

from lxml import etree


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read()


def parse_items(xml: bytes) -> list:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(xml, parser)
    return [{"title": i.findtext("title"), "link": i.findtext("link")} for i in root.iter("item")]
