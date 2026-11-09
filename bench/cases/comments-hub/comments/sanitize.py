from lxml.html.clean import Cleaner

_cleaner = Cleaner(scripts=True, javascript=True, style=True, forms=False, safe_attrs_only=True)


def sanitize(html: str) -> str:
    if not html.strip():
        return ""
    return _cleaner.clean_html(html)
