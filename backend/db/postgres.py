import os
import re
import sqlite3
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from backend.config import settings

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

_POSTGRES_CHECKED = False
_POSTGRES_AVAILABLE = False

def check_postgres_availability(dsn: str) -> bool:
    global _POSTGRES_CHECKED, _POSTGRES_AVAILABLE
    if _POSTGRES_CHECKED:
        return _POSTGRES_AVAILABLE
    _POSTGRES_CHECKED = True
    if not HAS_PSYCOPG or dsn.startswith("sqlite"):
        _POSTGRES_AVAILABLE = False
        return False
    # Quick socket check on port 5432 to avoid multi-second TCP timeout on Windows
    try:
        import socket
        s = socket.socket()
        s.settimeout(0.05)
        s.connect(('127.0.0.1', 5432))
        s.close()
    except Exception:
        _POSTGRES_AVAILABLE = False
        return False

    try:
        conn = psycopg.connect(dsn, connect_timeout=1)
        conn.close()
        _POSTGRES_AVAILABLE = True
        return True
    except Exception:
        _POSTGRES_AVAILABLE = False
        return False

class DictRowCursor:
    """Cursor wrapper that normalizes queries and returns dict rows across Postgres & SQLite."""
    def __init__(self, cursor, is_sqlite: bool):
        self._cur = cursor
        self.is_sqlite = is_sqlite

    def _translate_query(self, query: str) -> str:
        if not self.is_sqlite:
            return query
        q = query
        q = re.sub(r'::timestamptz', '', q, flags=re.I)
        q = re.sub(r'::date', '', q, flags=re.I)
        q = re.sub(r'::jsonb', '', q, flags=re.I)
        q = re.sub(r'\bNOW\(\)', 'CURRENT_TIMESTAMP', q, flags=re.I)
        q = re.sub(r'\bTRUE\b', '1', q, flags=re.I)
        q = re.sub(r'\bFALSE\b', '0', q, flags=re.I)
        q = q.replace('%s', '?')
        return q

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None):
        t_query = self._translate_query(query)
        if params is None:
            return self._cur.execute(t_query)
        if self.is_sqlite:
            clean_params = []
            for p in params:
                if isinstance(p, bool):
                    clean_params.append(1 if p else 0)
                else:
                    clean_params.append(p)
            params = tuple(clean_params)
        return self._cur.execute(t_query, params)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        row = self._cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class DBConnection:
    """Context manager for DB connections supporting Postgres with SQLite fallback."""
    def __init__(self, dsn: str = settings.POSTGRES_DSN, sqlite_path: str = settings.SQLITE_PATH):
        self.dsn = dsn
        self.sqlite_path = sqlite_path
        self._conn = None
        self.is_sqlite = False

    def __enter__(self):
        if check_postgres_availability(self.dsn):
            self._conn = psycopg.connect(self.dsn, row_factory=dict_row)
            self.is_sqlite = False
            return self

        self._conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self.is_sqlite = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
            self._conn.close()

    def cursor(self):
        return DictRowCursor(self._conn.cursor(), self.is_sqlite)

    def commit(self):
        if self._conn:
            self._conn.commit()


def get_db_connection() -> DBConnection:
    return DBConnection()


def init_database():
    """Initializes schema and critical performance indexes."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    
    with get_db_connection() as conn:
        if conn.is_sqlite:
            cleaned_sql = sql_text
            cleaned_sql = re.sub(r'\bDOUBLE PRECISION\b', 'REAL', cleaned_sql, flags=re.I)
            cleaned_sql = re.sub(r'\bTIMESTAMPTZ\b', 'TEXT', cleaned_sql, flags=re.I)
            cleaned_sql = re.sub(r'\bSERIAL PRIMARY KEY\b', 'INTEGER PRIMARY KEY AUTOINCREMENT', cleaned_sql, flags=re.I)
            cleaned_sql = re.sub(r'\bBOOLEAN DEFAULT FALSE\b', 'INTEGER DEFAULT 0', cleaned_sql, flags=re.I)
            cleaned_sql = re.sub(r'\bBOOLEAN DEFAULT TRUE\b', 'INTEGER DEFAULT 1', cleaned_sql, flags=re.I)
            cleaned_sql = re.sub(r'\bBOOLEAN\b', 'INTEGER', cleaned_sql, flags=re.I)
            conn._conn.executescript(cleaned_sql)
            # Performance indexes
            conn._conn.execute('CREATE INDEX IF NOT EXISTS idx_ins_asset_date ON inspections(asset_id, inspected_at DESC)')
            conn._conn.execute('CREATE INDEX IF NOT EXISTS idx_mnt_asset_date ON maintenance(asset_id, started_at DESC)')
            conn._conn.execute('CREATE INDEX IF NOT EXISTS idx_ctx_asset ON context_notes(asset_id)')
            conn._conn.execute('CREATE INDEX IF NOT EXISTS idx_ctx_ins ON context_notes(inspection_id)')
            conn._conn.execute('CREATE INDEX IF NOT EXISTS idx_reg_asset ON regulatory_events(asset_id)')
            conn._conn.execute('CREATE INDEX IF NOT EXISTS idx_reg_ins ON regulatory_events(related_inspection_id)')
        else:
            conn.cursor().execute(sql_text)
        conn.commit()

if __name__ == "__main__":
    init_database()
    print("Database schema and performance indexes initialized.")
