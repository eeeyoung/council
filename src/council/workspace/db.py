"""
council/workspace/db.py

SQLite persistence for WorkspaceState. Same pattern as council.db:
a single JSON blob per workspace, stored as a row.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from council.workspace.state import WorkspaceState

DB_PATH = Path("workspace.db")


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


def save(state: WorkspaceState) -> None:
    """Persist a workspace. Upserts by id."""
    init_db()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO workspaces (id, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (state.id, state.model_dump_json()),
            )


def load(workspace_id: str) -> WorkspaceState:
    """Load a workspace by id."""
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "SELECT state_json FROM workspaces WHERE id = ?",
            (workspace_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"No workspace found with id: {workspace_id}")
        return WorkspaceState.model_validate_json(row[0])


def list_all() -> list[dict]:
    """Return all workspace ids with metadata (no state blob)."""
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "SELECT id, updated_at FROM workspaces ORDER BY updated_at DESC"
        )
        return [
            {"id": row[0], "updated_at": row[1]}
            for row in cursor.fetchall()
        ]


def delete(workspace_id: str) -> None:
    """Delete a workspace."""
    init_db()
    with closing(_connect()) as conn:
        with conn:
            conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
