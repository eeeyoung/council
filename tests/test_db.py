"""
tests/test_db.py

Tests for SQLite persistence of CouncilState.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from council.db import DB_PATH, init_db, load_state, save_state
from council.state import CouncilState, ExpertDefinition


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    """Use a unique temporary database file for each test to avoid Windows file locks."""
    temp_file = tmp_path / "council_test.db"
    monkeypatch.setattr("council.db.DB_PATH", temp_file)
    yield


def test_init_db():
    init_db()
    from council.db import DB_PATH
    assert DB_PATH.exists()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        assert cursor.fetchone() is not None


def test_save_and_load_state():
    state = CouncilState(query="Test query", status="researching")
    state.session_id = "test_123"
    state.experts = [
        ExpertDefinition(
            name="Alice",
            discipline="Physics",
            bias="None",
            persona_prompt="Prompt"
        )
    ]
    
    # Save
    save_state(state)
    
    # Load into a new object
    loaded = load_state("test_123")
    
    assert loaded.session_id == "test_123"
    assert loaded.query == "Test query"
    assert loaded.status == "researching"
    assert len(loaded.experts) == 1
    assert loaded.experts[0].name == "Alice"


def test_load_nonexistent_state():
    with pytest.raises(ValueError, match="No session found"):
        load_state("does_not_exist")


def test_save_updates_existing():
    state = CouncilState(query="Q1")
    state.session_id = "update_test"
    
    save_state(state)
    
    # Change state and save again
    state.status = "debating"
    state.query = "Q2"
    save_state(state)
    
    loaded = load_state("update_test")
    assert loaded.status == "debating"
    assert loaded.query == "Q2"
