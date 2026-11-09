import sqlite3


def fetch_rows(table: str) -> list:
    con = sqlite3.connect("warehouse.db")
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]  # table names come from our own config
