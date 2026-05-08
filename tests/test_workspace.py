"""
tests/test_workspace.py

Phase 1 tests for the session data model and persistence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.workspace.state import (
    Session, Expert, KnowledgePool, PoolSource, Opinion, Message, Symposium,
)
from council.workspace.db import save, load, list_all, delete


class TestSession:
    def test_create_empty_session(self):
        s = Session(query="Test climate economics")
        assert s.id
        assert len(s.experts) == 0
        assert len(s.messages) == 0
        assert len(s.symposia) == 0

    def test_create_session_with_experts(self):
        s = Session()
        s.experts.append(Expert(
            name="Socratyes",
            discipline="Climate Economics",
            bias="Prefers carbon taxation",
            persona_prompt="A pragmatic economist.",
        ))
        assert len(s.experts) == 1
        assert s.experts[0].name == "Socratyes"

    def test_get_expert(self):
        s = Session()
        e1 = Expert(name="A", discipline="Physics")
        e2 = Expert(name="B", discipline="Chemistry")
        s.experts = [e1, e2]

        assert s.get_expert(e1.id).name == "A"
        assert s.get_expert(e2.id).name == "B"
        assert s.get_expert("nonexistent") is None

    def test_knowledge_pool_sources_and_opinions(self):
        expert = Expert(name="Test", discipline="Physics")
        src = PoolSource(url="https://example.com/paper", title="A Key Paper",
                         snippet="Important findings...", verification_status="verified")
        expert.knowledge_pool.sources.append(src)
        opinion = Opinion(text="The evidence supports carbon taxation.", source_ids=[src.id])
        expert.knowledge_pool.opinions.append(opinion)

        assert len(expert.knowledge_pool.sources) == 1
        assert expert.knowledge_pool.sources[0].verification_status == "verified"
        assert len(expert.knowledge_pool.opinions) == 1
        assert expert.knowledge_pool.opinions[0].source_ids == [src.id]

    def test_add_message(self):
        s = Session()
        s.add_message(role="user", content="What does the panel think?")
        s.add_message(role="agent", agent_id="ex_123", agent_name="Socratyes",
                      content="## Position\nCarbon tax is efficient.", symposium_id="sym_1", turn=1)
        assert len(s.messages) == 2
        assert s.messages[1].turn == 1

    def test_symposium_messages(self):
        s = Session()
        s.add_message(role="system", content="Started.", symposium_id="sym_1")
        s.add_message(role="agent", agent_name="A", content="Pos.", symposium_id="sym_1")
        s.add_message(role="user", content="Hello", symposium_id="")
        assert len(s.get_messages_for_symposium("sym_1")) == 2
        assert len(s.get_messages_for_symposium("nonexistent")) == 0

    def test_symposium_with_participants(self):
        e1 = Expert(name="A", discipline="Physics")
        e2 = Expert(name="B", discipline="Chemistry")
        sym = Symposium(title="Cross-discipline debate", format="structured",
                        participant_ids=[e1.id, e2.id])
        assert len(sym.participant_ids) == 2
        assert sym.format == "structured"


class TestDB:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s = Session(query="Test persistence")
        s.experts.append(Expert(name="Socratyes", discipline="Economics"))
        s.add_message(role="user", content="Hello")
        save(s)
        loaded = load(s.id)
        assert loaded.id == s.id
        assert loaded.query == "Test persistence"
        assert len(loaded.experts) == 1
        assert loaded.experts[0].name == "Socratyes"
        assert len(loaded.messages) == 1

    def test_save_updates_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s = Session(); save(s)
        s.query = "Updated"; save(s)
        assert load(s.id).query == "Updated"

    def test_list_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s1, s2 = Session(), Session()
        save(s1); save(s2)
        ids = {w["id"] for w in list_all()}
        assert s1.id in ids and s2.id in ids

    def test_load_nonexistent_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        with pytest.raises(ValueError, match="No session found"):
            load("nonexistent")

    def test_delete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s = Session(); save(s); delete(s.id)
        with pytest.raises(ValueError): load(s.id)
