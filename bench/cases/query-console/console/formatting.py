import sqlparse


def normalize(sql: str) -> str:
    """Strip comments so the audit log stores just the statement."""
    return sqlparse.format(sql, strip_comments=True, reindent=False).strip()
