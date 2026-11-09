from nltk import pos_tag, word_tokenize


def tag(text: str) -> list:
    tokens = word_tokenize(text)
    return [{"token": t, "pos": p} for t, p in pos_tag(tokens)]
