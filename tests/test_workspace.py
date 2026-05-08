"""
tests/test_workspace.py

Phase 1 tests for the workspace data model and persistence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.workspace.state import (
    WorkspaceState, Panel, Expert, KnowledgePool, PoolSource, Opinion,
    Message, Symposium,
)
from council.workspace.db import save, load, list_all, delete


# ── State model tests ──────────────────────────────────────────────────────

class TestWorkspaceState:
    def test_create_empty_workspace(self):
        ws = WorkspaceState(query="Test climate economics")
        assert ws.id
        assert len(ws.panels) == 0
        assert len(ws.messages) == 0
        assert len(ws.symposia) == 0

    def test_create_panel_with_experts(self):
        ws = WorkspaceState()
        expert = Expert(
            name="Socratyes",
            discipline="Climate Economics",
            bias="Prefers carbon taxation",
            persona_prompt="A pragmatic economist who trusts market mechanisms.",
        )
        panel = Panel(
            name="Climate Policy",
            query="What is the most effective carbon pricing mechanism?",
            experts=[expert],
        )
        ws.panels.append(panel)

        assert len(ws.panels) == 1
        assert ws.panels[0].experts[0].name == "Socratyes"

    def test_get_expert(self):
        ws = WorkspaceState()
        e1 = Expert(name="A", discipline="Physics")
        e2 = Expert(name="B", discipline="Chemistry")
        ws.panels.append(Panel(experts=[e1]))
        ws.panels.append(Panel(experts=[e2]))

        assert ws.get_expert(e1.id).name == "A"
        assert ws.get_expert(e2.id).name == "B"
        assert ws.get_expert("nonexistent") is None

    def test_get_panel(self):
        ws = WorkspaceState()
        p = Panel(name="Test Panel")
        ws.panels.append(p)

        assert ws.get_panel(p.id).name == "Test Panel"
        assert ws.get_panel("nonexistent") is None

    def test_knowledge_pool_sources_and_opinions(self):
        expert = Expert(name="Test", discipline="Physics")
        src = PoolSource(
            url="https://example.com/paper",
            title="A Key Paper",
            snippet="Important findings...",
            verification_status="verified",
        )
        expert.knowledge_pool.sources.append(src)
        opinion = Opinion(
            text="The evidence supports carbon taxation.",
            source_ids=[src.id],
        )
        expert.knowledge_pool.opinions.append(opinion)

        assert len(expert.knowledge_pool.sources) == 1
        assert expert.knowledge_pool.sources[0].verification_status == "verified"
        assert len(expert.knowledge_pool.opinions) == 1
        assert expert.knowledge_pool.opinions[0].source_ids == [src.id]

    def test_add_message(self):
        ws = WorkspaceState()
        ws.add_message(
            role="user",
            content="What does the panel think about carbon pricing?",
        )
        ws.add_message(
            role="agent",
            agent_id="ex_123",
            agent_name="Socratyes",
            content="## Position\nCarbon tax is the most efficient mechanism.",
            symposium_id="sym_1",
            turn=1,
        )

        assert len(ws.messages) == 2
        assert ws.messages[0].role == "user"
        assert ws.messages[1].turn == 1

    def test_symposium_messages(self):
        ws = WorkspaceState()
        ws.add_message(role="system", content="Symposium started.", symposium_id="sym_1")
        ws.add_message(role="agent", agent_name="A", content="Position.", symposium_id="sym_1")
        ws.add_message(role="user", content="Hello", symposium_id="")

        sym_msgs = ws.get_messages_for_symposium("sym_1")
        assert len(sym_msgs) == 2
        assert len(ws.get_messages_for_symposium("nonexistent")) == 0

    def test_symposium_with_participants(self):
        e1 = Expert(name="A", discipline="Physics")
        e2 = Expert(name="B", discipline="Chemistry")
        sym = Symposium(
            title="Cross-discipline debate",
            format="structured",
            participant_ids=[e1.id, e2.id],
        )
        assert len(sym.participant_ids) == 2
        assert sym.format == "structured"
        assert sym.synthesis == ""


# ── Persistence tests ───────────────────────────────────────────────────────

class TestWorkspaceDB:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test_workspace.db")

        ws = WorkspaceState(query="Test persistence")
        e = Expert(name="Socratyes", discipline="Economics")
        ws.panels.append(Panel(name="Test", experts=[e]))
        ws.add_message(role="user", content="Hello")

        save(ws)
        loaded = load(ws.id)

        assert loaded.id == ws.id
        assert loaded.query == "Test persistence"
        assert len(loaded.panels) == 1
        assert loaded.panels[0].experts[0].name == "Socratyes"
        assert len(loaded.messages) == 1

    def test_save_updates_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test_workspace.db")

        ws = WorkspaceState()
        save(ws)
        ws.query = "Updated query"
        save(ws)
        loaded = load(ws.id)

        assert loaded.query == "Updated query"

    def test_list_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test_workspace.db")

        ws1 = WorkspaceState()
        ws2 = WorkspaceState()
        save(ws1)
        save(ws2)

        all_ws = list_all()
        ids = {w["id"] for w in all_ws}
        assert ws1.id in ids
        assert ws2.id in ids

    def test_load_nonexistent_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test_workspace.db")

        with pytest.raises(ValueError, match="No workspace found"):
            load("nonexistent")

    def test_delete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("council.workspace.db.DB_PATH", tmp_path / "test_workspace.db")

        ws = WorkspaceState()
        save(ws)
        delete(ws.id)

        with pytest.raises(ValueError):
            load(ws.id)
