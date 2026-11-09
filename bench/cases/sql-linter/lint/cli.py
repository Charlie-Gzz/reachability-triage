import sys

from lint.format import pretty, statements


def main():
    sql = open(sys.argv[1]).read()
    for stmt in statements(sql):
        print(pretty(stmt))
        print()


if __name__ == "__main__":
    main()
