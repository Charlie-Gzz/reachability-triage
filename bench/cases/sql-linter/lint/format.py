import sqlparse


def pretty(sql: str) -> str:
    return sqlparse.format(sql, reindent=True, keyword_case="upper", identifier_case="lower")


def statements(sql: str) -> list:
    return [s for s in sqlparse.split(sql) if s.strip()]
