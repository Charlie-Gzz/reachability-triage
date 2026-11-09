import sys

from corpus.stats import top_words

for word, count in top_words(open(sys.argv[1]).read()):
    print(f"{count:>6}  {word}")
