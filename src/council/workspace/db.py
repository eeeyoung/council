"""
council/workspace/db.py

SQLite persistence for Session. Same pattern as council.db:
a single JSON blob per session, stored as a row.

After the multi-panel refactor there is only one session (id="default").
Legacy sessions with different ids are migrated on first load.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from council.workspace.state import Session

DB_PATH = Path("workspace.db")

log = logging.getLogger("council")


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
    """Persist the session. Upserts by id."""
    init_db()
    json_size = len(session.model_dump_json())
    expert_count = sum(len(p.experts) for p in session.panels)
    log.info(
        "[db] save() → %d panels, %d experts, %d messages, %d symposia (%dKB)",
        len(session.panels), expert_count,
        len(session.messages), len(session.symposia),
        json_size // 1024,
    )
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


def load(session_id: str = "default") -> Session:
    """Load a session by id (defaults to singleton)."""
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "SELECT state_json FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"No session found with id: {session_id}")
        return _deserialize(row[0])


def _deserialize(raw: str) -> Session:
    """Deserialize a session, attempting v1 migration if the new format fails."""
    try:
        return Session.model_validate_json(raw)
    except ValidationError:
        data = json.loads(raw)
        log.info("[db] detected v1 session format — migrating to multi-panel")
        return Session.migrate_from_v1(data)


def get_or_create_default() -> Session:
    """Return the singleton session, creating it if it doesn't exist.
    Also migrates any old-format sessions found in the database."""
    init_db()
    with closing(_connect()) as conn:
        # Check for the default session
        cursor = conn.execute(
            "SELECT state_json FROM sessions WHERE id = ?", ("default",)
        )
        row = cursor.fetchone()
        if row:
            return _deserialize(row[0])

        # No default session — check for legacy sessions to migrate
        cursor = conn.execute(
            "SELECT id, state_json FROM sessions ORDER BY updated_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            old_id, old_json = row
            log.info("[db] migrating legacy session %s → default", old_id)
            session = _deserialize(old_json)
            session.id = "default"
            save(session)
            # Delete old row
            with conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (old_id,))
            return session

        # Create a fresh default session
        log.info("[db] get_or_create_default() → created new default session")
        session = Session()
        save(session)
        return session
