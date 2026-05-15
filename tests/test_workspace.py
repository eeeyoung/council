"""
tests/test_workspace.py

Tests for the workspace data model and persistence (multi-panel refactor).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.workspace.state import (
    Session, Panel, Expert, KnowledgePool, PoolSource, Opinion, Message, Symposium,
)
from council.workspace.db import save, load, get_or_create_default


class TestPanel:
    def test_create_panel(self):
        p = Panel(name="Test", query="What is X?")
        assert p.id
        assert p.name == "Test"
        assert p.query == "What is X?"
        assert len(p.experts) == 0

    def test_panel_with_experts(self):
        p = Panel()
        p.experts.append(Expert(name="Dr. A", discipline="Physics"))
        p.experts.append(Expert(name="Dr. B", discipline="Chemistry"))
        assert len(p.experts) == 2
        assert p.experts[0].name == "Dr. A"


class TestSession:
    def test_create_empty_session(self):
        s = Session()
        assert s.id == "default"
        assert len(s.panels) == 0
        assert len(s.messages) == 0
        assert len(s.symposia) == 0

    def test_session_with_panel(self):
        s = Session()
        p = Panel(name="Climate Economics")
        p.experts.append(Expert(
            name="Socratyes",
            discipline="Climate Economics",
            bias="Prefers carbon taxation",
            persona_prompt="A pragmatic economist.",
        ))
        s.panels.append(p)
        assert len(s.panels) == 1
        assert len(s.panels[0].experts) == 1
        assert s.panels[0].experts[0].name == "Socratyes"

    def test_get_expert_cross_panel(self):
        s = Session()
        p1 = Panel(); p2 = Panel()
        e1 = Expert(name="A", discipline="Physics")
        e2 = Expert(name="B", discipline="Chemistry")
        p1.experts = [e1]; p2.experts = [e2]
        s.panels = [p1, p2]

        assert s.get_expert(e1.id).name == "A"
        assert s.get_expert(e2.id).name == "B"
        assert s.get_expert("nonexistent") is None

    def test_get_expert_with_panel(self):
        s = Session()
        p = Panel(name="Test Panel")
        e = Expert(name="Dr. X", discipline="Math")
        p.experts = [e]
        s.panels = [p]

        result = s.get_expert_with_panel(e.id)
        assert result is not None
        panel_id, expert = result
        assert panel_id == p.id
        assert expert.name == "Dr. X"
        assert s.get_expert_with_panel("nonexistent") is None

    def test_get_expert_by_name(self):
        s = Session()
        p = Panel()
        e = Expert(name="Socratyes", discipline="Philosophy")
        p.experts = [e]
        s.panels = [p]

        assert s.get_expert_by_name("Socratyes").id == e.id
        assert s.get_expert_by_name("Nobody") is None

    def test_get_experts_flat(self):
        s = Session()
        p1 = Panel(); p2 = Panel()
        e1 = Expert(name="A", discipline="Physics")
        e2 = Expert(name="B", discipline="Chemistry")
        p1.experts = [e1]; p2.experts = [e2]
        s.panels = [p1, p2]

        flat = s.get_experts_flat()
        assert len(flat) == 2
        assert flat[0]["panel_id"] == p1.id
        assert flat[1]["panel_id"] == p2.id

    def test_get_panel(self):
        s = Session()
        p = Panel(name="My Panel")
        s.panels = [p]
        assert s.get_panel(p.id).name == "My Panel"
        assert s.get_panel("nope") is None

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

    def test_migrate_from_v1(self):
        old_data = {
            "id": "abc12345",
            "name": "Old Session",
            "query": "What is old?",
            "function_type": "",
            "function_detail": "",
            "experts": [
                {"name": "Dr. Old", "discipline": "History", "bias": "",
                 "persona_prompt": "", "photo_url": "",
                 "knowledge_pool": {"sources": [], "opinions": []}}
            ],
            "messages": [],
            "symposia": [],
            "created_at": "2025-01-01T00:00:00Z",
        }
        s = Session.migrate_from_v1(old_data)
        assert s.id == "default"
        assert len(s.panels) == 1
        assert s.panels[0].name == "Old Session"
        assert s.panels[0].query == "What is old?"
        assert len(s.panels[0].experts) == 1
        assert s.panels[0].experts[0].name == "Dr. Old"


class TestDB:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s = Session()
        p = Panel(name="Test Panel", query="Test persistence")
        p.experts.append(Expert(name="Socratyes", discipline="Economics"))
        s.panels.append(p)
        s.add_message(role="user", content="Hello")
        save(s)
        loaded = load(s.id)
        assert loaded.id == s.id
        assert len(loaded.panels) == 1
        assert loaded.panels[0].query == "Test persistence"
        assert len(loaded.panels[0].experts) == 1
        assert loaded.panels[0].experts[0].name == "Socratyes"
        assert len(loaded.messages) == 1

    def test_save_updates_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s = Session(); save(s)
        p = Panel(name="Updated", query="New query")
        s.panels.append(p)
        save(s)
        loaded = load(s.id)
        assert len(loaded.panels) == 1
        assert loaded.panels[0].name == "Updated"

    def test_get_or_create_default_creates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s = get_or_create_default()
        assert s.id == "default"
        assert len(s.panels) == 0

    def test_get_or_create_default_loads_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        s1 = Session()
        p = Panel(name="Persistent")
        s1.panels.append(p)
        save(s1)
        s2 = get_or_create_default()
        assert len(s2.panels) == 1
        assert s2.panels[0].name == "Persistent"

    def test_load_nonexistent_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test.db")
        with pytest.raises(ValueError, match="No session found"):
            load("nonexistent")
