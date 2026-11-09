from corpus.stats import tokens

from nltk.tokenize import word_tokenize


def test_counts_close_to_nltk():
    text = "The quick brown fox jumps over the lazy dog."
    assert abs(len(tokens(text)) - len([t for t in word_tokenize(text) if t.isalpha()])) <= 1
