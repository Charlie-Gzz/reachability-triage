from collections import Counter


def tokens(text: str) -> list:
    return [t.strip(".,;:!?\"'()").lower() for t in text.split() if t.strip(".,;:!?\"'()")]


def top_words(text: str, n: int = 20) -> list:
    return Counter(tokens(text)).most_common(n)
