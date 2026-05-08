"""
council/workspace/db.py

SQLite persistence for Session. Same pattern as council.db:
a single JSON blob per session, stored as a row.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from council.workspace.state import Session

DB_PATH = Path("workspace.db")


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


def save(session: Session) -> None:
    """Persist a session. Upserts by id."""
    init_db()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (id, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session.id, session.model_dump_json()),
            )


def load(session_id: str) -> Session:
    """Load a session by id."""
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "SELECT state_json FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"No session found with id: {session_id}")
        return Session.model_validate_json(row[0])


def list_all() -> list[dict]:
    """Return all session ids with metadata (no state blob)."""
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "SELECT id, updated_at FROM sessions ORDER BY updated_at DESC"
        )
        return [
            {"id": row[0], "updated_at": row[1]}
            for row in cursor.fetchall()
        ]


def delete(session_id: str) -> None:
    """Delete a session. Raises ValueError if not found."""
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        if not cursor.fetchone():
            raise ValueError(f"No session found with id: {session_id}")
        with conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
