"""SQLite storage abstraction.

This module is intentionally simple in v0.1.
It provides a local persistence layer for benchmark testing.
"""

import sqlite3
from pathlib import Path


class FinanceDatabase:
    def __init__(self, db_path="finance.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)

    def execute(self, sql, params=None):
        cursor = self.conn.cursor()
        cursor.execute(sql, params or ())
        self.conn.commit()
        return cursor

    def close(self):
        self.conn.close()
