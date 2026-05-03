"""
council/db.py

SQLite persistence layer for CouncilState.
Allows pausing and resuming sessions.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from council.state import CouncilState

DB_PATH = Path("council.db")


from contextlib import closing

def init_db() -> None:
    """Initialize the SQLite database schema."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


def save_state(state: CouncilState) -> None:
    """Serialize and save the current state to the database."""
    init_db()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (state.session_id, state.model_dump_json()),
            )


def load_state(session_id: str) -> CouncilState:
    """Load a state from the database by session_id."""
    init_db()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.execute(
            "SELECT state_json FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()

        if not row:
            raise ValueError(f"No session found with ID: {session_id}")

        return CouncilState.model_validate_json(row[0])
