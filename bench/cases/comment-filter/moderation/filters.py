import bleach

ALLOWED = ["b", "i", "em", "strong", "a"]


def clean_comment(text: str) -> str:
    return bleach.clean(text, tags=ALLOWED, attributes={"a": ["href"]}, strip=True)


def linkify(text: str) -> str:
    return bleach.linkify(text)
