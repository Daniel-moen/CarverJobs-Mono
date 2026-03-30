import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite only — no PostgreSQL. Optional absolute path for the DB file (e.g. mounted volume).
_sqlite_override = os.getenv("CARVER_SQLITE_PATH", "").strip()
if _sqlite_override:
    DB_PATH = Path(_sqlite_override).resolve()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DB_DIR = Path(__file__).resolve().parent.parent / "data"
    DB_DIR.mkdir(exist_ok=True)
    DB_PATH = DB_DIR / "carver.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
  db = SessionLocal()
  try:
    yield db
  finally:
    db.close()


def run_migrations() -> None:
  """Add any missing columns to existing tables (idempotent).

  Uses a raw sqlite3 connection so SQLAlchemy's connection pool is never
  left in an error/rollback state by a failed DDL statement.
  """
  with sqlite3.connect(str(DB_PATH)) as conn:
    def _existing(table: str) -> set[str]:
      cur = conn.cursor()
      cur.execute(f"PRAGMA table_info({table})")
      return {row[1] for row in cur.fetchall()}

    def _add(table: str, col: str, definition: str, existing: set[str]) -> None:
      if col not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

    users_cols = _existing("users")
    _add("users", "is_subscribed", "BOOLEAN NOT NULL DEFAULT 0", users_cols)

    ae_cols = _existing("analytics_events")
    _add("analytics_events", "error_code", "VARCHAR(20)", ae_cols)
    _add("analytics_events", "client_ts",  "VARCHAR(30)", ae_cols)

    jobs_cols = _existing("jobs")
    _add("jobs", "source", "VARCHAR(50) DEFAULT 'manual'", jobs_cols)
    _add("jobs", "content_hash", "VARCHAR(64)", jobs_cols)
    _add("jobs", "job_fingerprint", "VARCHAR(64)", jobs_cols)

    # scrape_watermarks — tracks newest post timestamp per source URL so
    # Apify runs only fetch posts newer than the last successful scrape.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_watermarks (
            source_url TEXT PRIMARY KEY,
            last_post_at TEXT
        )
    """)

    # WhatsApp bot tables — additive, no effect on existing tables.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_sessions (
            phone_number VARCHAR(30) PRIMARY KEY,
            mode VARCHAR(20) NOT NULL DEFAULT 'onboarding',
            history TEXT NOT NULL DEFAULT '[]',
            partial_profile TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            updated_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_magic_tokens (
            token VARCHAR(32) PRIMARY KEY,
            phone_number VARCHAR(30) NOT NULL,
            expires_at DATETIME NOT NULL,
            used BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_magic_tokens_phone ON whatsapp_magic_tokens (phone_number)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            level VARCHAR(10) NOT NULL DEFAULT 'error',
            status_code INTEGER,
            crv_code VARCHAR(20),
            method VARCHAR(10),
            path VARCHAR(300),
            module VARCHAR(60),
            message TEXT NOT NULL,
            traceback TEXT,
            request_id VARCHAR(20),
            client_ip VARCHAR(60),
            ai_analysis TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_error_logs_created_at ON error_logs (created_at)"
    )

    wmt_cols = _existing("whatsapp_magic_tokens")
    _add("whatsapp_magic_tokens", "redirect_to", "VARCHAR(120)", wmt_cols)

    cp_cols = _existing("crew_profiles")
    _add("crew_profiles", "sex", "VARCHAR(20)", cp_cols)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key VARCHAR(160) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            total_jobs_scanned INTEGER NOT NULL DEFAULT 0,
            total_matched INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            completed_at DATETIME
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_sessions_user_key ON match_sessions (user_key)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_session_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            matched BOOLEAN NOT NULL DEFAULT 0,
            compatibility REAL NOT NULL DEFAULT 0.0,
            reason TEXT,
            strengths TEXT,
            gaps TEXT,
            factor_scores TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_session_results_session_id ON match_session_results (session_id)"
    )

    conn.commit()
