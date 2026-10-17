import os
import re
import time
import socket
import sqlite3
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

try:
    from sqlalchemy import create_engine, text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

_POSTGRES_CHECKED = False
_POSTGRES_AVAILABLE = False
_SQLALCHEMY_ENGINE = None

def check_postgres_availability(dsn: str = settings.POSTGRES_DSN, max_retries: int = 10) -> bool:
    """
    Checks if Postgres is available, retrying with exponential backoff up to max_retries times.
    """
    global _POSTGRES_CHECKED, _POSTGRES_AVAILABLE
    if _POSTGRES_CHECKED:
        return _POSTGRES_AVAILABLE

    if not HAS_PSYCOPG or dsn.startswith("sqlite"):
        _POSTGRES_CHECKED = True
        _POSTGRES_AVAILABLE = False
        return False

    parsed = urlparse(dsn)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    is_local = host in ("127.0.0.1", "localhost")
    effective_retries = 2 if (is_local and "postgres" not in os.environ.get("POSTGRES_HOST", "")) else max_retries

    for attempt in range(1, effective_retries + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1 if is_local else 0.5)
                s.connect((host, port))
            
            conn = psycopg.connect(dsn, connect_timeout=2)
            conn.close()
            _POSTGRES_CHECKED = True
            _POSTGRES_AVAILABLE = True
            logger.info(f"Connected to PostgreSQL database at {host}:{port}")
            return True
        except Exception as e:
            if attempt == effective_retries:
                logger.warning(f"PostgreSQL connection to {host}:{port} failed after {effective_retries} attempts: {e}. Falling back to SQLite.")
                _POSTGRES_CHECKED = True
                _POSTGRES_AVAILABLE = False
                return False
            time.sleep(min(0.2 * (2 ** (attempt - 1)), 2.0))

    _POSTGRES_CHECKED = True
    _POSTGRES_AVAILABLE = False
    return False

def get_sqlalchemy_engine():
    global _SQLALCHEMY_ENGINE
    if _SQLALCHEMY_ENGINE is not None:
        return _SQLALCHEMY_ENGINE, not _POSTGRES_AVAILABLE

    if check_postgres_availability(settings.POSTGRES_DSN):
        try:
            _SQLALCHEMY_ENGINE = create_engine(settings.POSTGRES_DSN, pool_pre_ping=True)
            return _SQLALCHEMY_ENGINE, False
        except Exception as e:
            logger.warning(f"Failed to create SQLAlchemy Postgres engine: {e}")

    sqlite_url = f"sqlite:///{settings.SQLITE_PATH}"
    _SQLALCHEMY_ENGINE = create_engine(sqlite_url, connect_args={"timeout": 30.0})
    return _SQLALCHEMY_ENGINE, True

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

        self._conn = sqlite3.connect(self.sqlite_path, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA busy_timeout = 30000")
        except Exception:
            pass
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

EFFECTIVE_INSPECTIONS_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_effective_inspections AS
SELECT
    i.inspection_id,
    i.asset_id,
    w.well_type,
    w.area_id,
    a.name AS area_name,
    w.team_id,
    w.lat,
    w.lon,
    w.recorded_status,
    i.inspected_at,
    i.inspector_user_id,
    u.name AS inspector_name,
    i.method,
    i.ambient_temp_c,
    i.wellhead_temp_c AS raw_wellhead_temp_c,
    COALESCE(
        CAST((SELECT c.corrected_value FROM context_notes c
              WHERE c.inspection_id = i.inspection_id
                AND c.note_type = 'correction'
                AND c.field_overridden = 'wellhead_temp_c'
                AND COALESCE(c.verification_status, 'confirmed') != 'deleted_forgotten'
              ORDER BY c.created_at DESC LIMIT 1) AS REAL),
        i.wellhead_temp_c
    ) AS effective_wellhead_temp_c,
    (
        COALESCE(
            CAST((SELECT c.corrected_value FROM context_notes c
                  WHERE c.inspection_id = i.inspection_id
                    AND c.note_type = 'correction'
                    AND c.field_overridden = 'wellhead_temp_c'
                    AND COALESCE(c.verification_status, 'confirmed') != 'deleted_forgotten'
                  ORDER BY c.created_at DESC LIMIT 1) AS REAL),
            i.wellhead_temp_c
        ) - i.ambient_temp_c
    ) AS effective_temp_delta_c,
    COALESCE(
        (SELECT sr.numeric_value FROM scoped_rules sr
         WHERE sr.scope_type = 'WELL_TYPE'
           AND sr.scope_value = w.well_type
           AND sr.parameter_name = 'min_temp_delta_c'
         ORDER BY sr.is_user_override DESC, sr.id DESC LIMIT 1),
        CASE WHEN w.well_type = 'T350' THEN 20.0 ELSE 15.0 END
    ) AS min_temp_delta_c,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM context_notes c
            WHERE c.inspection_id = i.inspection_id
              AND c.note_type = 'correction'
              AND c.field_overridden = 'spill_detected'
              AND c.corrected_value = 'false'
              AND COALESCE(c.verification_status, 'confirmed') != 'deleted_forgotten'
        ) THEN 0
        ELSE i.spill_detected
    END AS effective_spill_detected,
    i.spill_est_volume_bbl AS raw_spill_volume_bbl,
    COALESCE(
        CAST((SELECT c.corrected_value FROM context_notes c
              WHERE c.inspection_id = i.inspection_id
                AND c.note_type = 'correction'
                AND c.field_overridden = 'spill_est_volume_bbl'
                AND COALESCE(c.verification_status, 'confirmed') != 'deleted_forgotten'
              ORDER BY c.created_at DESC LIMIT 1) AS REAL),
        i.spill_est_volume_bbl
    ) AS effective_spill_volume_bbl,
    i.notes AS inspector_notes
FROM inspections i
JOIN wells w ON i.asset_id = w.asset_id
JOIN areas a ON w.area_id = a.area_id
LEFT JOIN users u ON i.inspector_user_id = u.user_id;
"""

def init_database():
    """Initializes schema, governed views, and critical performance indexes."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    
    with get_db_connection() as conn:
        if conn.is_sqlite:
            cleaned_sql = sql_text
            cleaned_sql = re.sub(r'\bvector\(\d+\)', 'TEXT', cleaned_sql, flags=re.I)
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
            conn._conn.execute('CREATE INDEX IF NOT EXISTS idx_doc_emb_doc ON document_embeddings(doc_id)')
            # Governed SQL View
            conn._conn.execute("DROP VIEW IF EXISTS v_effective_inspections")
            conn._conn.execute(EFFECTIVE_INSPECTIONS_VIEW_SQL)
        else:
            # Postgres: enable vector extension first
            try:
                conn.cursor().execute("CREATE EXTENSION IF NOT EXISTS vector;")
            except Exception as e:
                logger.warning(f"Could not create vector extension in Postgres: {e}")
            conn.cursor().execute(sql_text)
            pg_view_sql = EFFECTIVE_INSPECTIONS_VIEW_SQL.replace("CREATE VIEW IF NOT EXISTS", "CREATE OR REPLACE VIEW")
            conn.cursor().execute(pg_view_sql)
        conn.commit()

if __name__ == "__main__":
    init_database()
    print("Database schema, governed view v_effective_inspections, and performance indexes initialized.")
