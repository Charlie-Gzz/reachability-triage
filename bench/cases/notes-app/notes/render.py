import bleach
import markdown

TAGS = ["p", "a", "b", "i", "ul", "ol", "li", "code", "pre", "noscript", "style", "h1", "h2", "h3"]
ATTRS = {"a": ["href", "title"]}


def render_note(source: str) -> str:
    html = markdown.markdown(source)
    return bleach.clean(html, tags=TAGS, attributes=ATTRS, strip=False)
