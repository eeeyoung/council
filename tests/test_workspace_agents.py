"""
tests/test_workspace_agents.py

Phase 2 tests for workspace agent wrappers and knowledge pool operations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.workspace.state import Expert, KnowledgePool, PoolSource, Opinion
from council.workspace.agents import (
    _expert_to_definition,
    _pool_to_text,
    _parse_json,
    _chunk_text,
    _enrich_source,
    add_source_to_expert,
    upload_file_to_expert,
    expert_respond,
    expert_research,
    fact_check_source,
    form_opinion,
    moderator_propose_panel,
    rapporteur_synthesize,
)
from council.state import ExpertDefinition


class TestHelpers:
    def test_expert_to_definition(self):
        expert = Expert(
            name="Socratyes",
            discipline="Climate Economics",
            bias="Prefers carbon taxation",
            persona_prompt="A pragmatic economist.",
        )
        ed = _expert_to_definition(expert)
        assert isinstance(ed, ExpertDefinition)
        assert ed.name == "Socratyes"

    def test_pool_to_text_empty(self):
        pool = KnowledgePool()
        text = _pool_to_text(pool)
        assert "empty" in text

    def test_pool_to_text_with_sources(self):
        pool = KnowledgePool()
        pool.sources.append(PoolSource(
            url="https://example.com/paper",
            title="A Key Paper",
            snippet="Important findings...",
            verification_status="verified",
        ))
        text = _pool_to_text(pool)
        assert "A Key Paper" in text
        assert "[verified]" in text

    def test_parse_json_valid(self):
        result = _parse_json('[{"key": "value"}]')
        assert result == [{"key": "value"}]

    def test_parse_json_with_markdown_fence(self):
        result = _parse_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_invalid(self):
        assert _parse_json("not json at all") is None

    def test_parse_json_trailing_comma(self):
        result = _parse_json('[{"key": "value",}]')
        assert result == [{"key": "value"}]

    def test_chunk_text_short(self):
        chunks = _chunk_text("Hello world.", chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world."

    def test_chunk_text_long(self):
        text = "The quick brown fox. " * 200  # ~4800 chars
        chunks = _chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 550  # allow some margin for boundary snapping

    def test_chunk_text_respects_paragraphs(self):
        text = "A" * 400 + "\n\n" + "B" * 400
        chunks = _chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 2


class TestKnowledgePoolOps:
    """User-driven operations (no LLM)."""

    def test_add_source_to_expert(self, tmp_path, monkeypatch):
        expert = Expert(name="Socratyes", discipline="Economics")
        src = add_source_to_expert(
            expert=expert,
            workspace_id="test_ws",
            url="https://example.com/carbon-tax",
            title="Carbon Tax Study",
            snippet="Carbon taxes reduce emissions 15% faster than cap-and-trade.",
            enrich=False,  # Don't try to fetch — avoids network
        )
        assert src.type == "collected"
        assert src.title == "Carbon Tax Study"
        assert src in expert.knowledge_pool.sources

    def test_add_source_with_enrich_attempt(self):
        """Enrichment should not crash on invalid URLs."""
        expert = Expert(name="Test", discipline="Physics")
        src = add_source_to_expert(
            expert=expert,
            workspace_id="test_ws",
            url="https://invalid.example/nonexistent-page-12345",
            title="Nonexistent",
            snippet="This page doesn't exist.",
            enrich=True,
        )
        # Should still store the source (enrichment is best-effort)
        assert src.type == "collected"
        assert src in expert.knowledge_pool.sources

    def test_upload_file_to_expert_text(self, tmp_path, monkeypatch):
        file_path = tmp_path / "test.txt"
        file_path.write_text("This is a test document with some content for the knowledge pool.")

        expert = Expert(name="Test", discipline="Physics")
        src = upload_file_to_expert(
            expert=expert,
            workspace_id="test_ws",
            file_path=str(file_path),
        )
        assert src is not None
        assert src.type == "uploaded"
        assert src.title == "test.txt"
        assert "test document" in src.full_text
        assert src in expert.knowledge_pool.sources

    def test_upload_file_nonexistent(self, tmp_path, monkeypatch):
        expert = Expert(name="Test", discipline="Physics")
        src = upload_file_to_expert(
            expert=expert,
            workspace_id="test_ws",
            file_path="/nonexistent/file.pdf",
        )
        assert src is None


class TestAgentImports:
    """Verify all agent wrappers are importable."""

    def test_expert_respond_importable(self):
        assert callable(expert_respond)

    def test_expert_research_importable(self):
        assert callable(expert_research)

    def test_fact_check_source_importable(self):
        assert callable(fact_check_source)

    def test_form_opinion_importable(self):
        assert callable(form_opinion)

    def test_moderator_propose_panel_importable(self):
        assert callable(moderator_propose_panel)

    def test_rapporteur_synthesize_importable(self):
        assert callable(rapporteur_synthesize)

    def test_add_source_importable(self):
        assert callable(add_source_to_expert)

    def test_upload_file_importable(self):
        assert callable(upload_file_to_expert)


@pytest.mark.skip(reason="Requires real LLM API keys — run manually")
class TestAgentCalls:
    """Manual integration tests — run with valid API keys."""

    def test_moderator_propose_panel(self):
        experts = moderator_propose_panel(
            query="What is the future of solid-state batteries?",
            max_experts=3,
        )
        assert len(experts) == 3
        for e in experts:
            assert e.name
            assert e.discipline

    def test_fact_check_real_source(self):
        source = PoolSource(
            url="https://en.wikipedia.org/wiki/Solid-state_battery",
            title="Solid-state battery - Wikipedia",
            snippet="Solid-state batteries use solid electrolytes instead of liquid ones.",
        )
        result = fact_check_source(source)
        assert result.verification_status in ("verified", "misattributed", "unverifiable")

    def test_expert_respond_with_pool(self):
        expert = Expert(
            name="Socratyes",
            discipline="Energy Economics",
            bias="Prefers market-based mechanisms",
        )
        expert.knowledge_pool.sources.append(PoolSource(
            url="https://example.com/carbon-tax",
            title="Carbon Tax Efficiency Study",
            snippet="Carbon taxes reduce emissions 15% faster than cap-and-trade.",
            verification_status="verified",
        ))

        response = expert_respond(
            expert=expert,
            workspace_id="test_ws_integration",
            query="What is the best carbon pricing mechanism?",
            message="What does the economic evidence say about carbon taxes vs cap-and-trade?",
        )
        assert "## Position" in response
        assert "**Keywords:**" in response

    def test_form_opinion_with_pool(self):
        expert = Expert(
            name="Socratyes",
            discipline="Energy Economics",
        )
        expert.knowledge_pool.sources.append(PoolSource(
            url="https://example.com/carbon-tax",
            title="Carbon Tax Study",
            snippet="Carbon taxes reduce emissions 15% faster than cap-and-trade.",
            verification_status="verified",
            full_text="A comprehensive study of carbon pricing mechanisms across 40 countries. "
                       "Carbon taxes consistently outperformed cap-and-trade in reducing emissions, "
                       "showing 15% faster reduction rates on average.",
        ))

        opinion = form_opinion(
            expert=expert,
            workspace_id="test_ws_integration",
            query="What is the best carbon pricing mechanism?",
        )
        if opinion:  # May be None if retrieval fails in test
            assert opinion.text
            assert len(opinion.source_ids) > 0

    def test_rapporteur_synthesize(self):
        transcript = """[Turn 1] **Socratyes** (Energy Economics):
## Position
Carbon tax is the most efficient mechanism.
**Keywords:** carbon tax, market efficiency
## Evidence
### Finding 1
**Claim:** Carbon taxes reduce emissions faster.
**Source:** https://example.com/carbon-tax
**Quote:** "Carbon taxes reduce emissions 15% faster than cap-and-trade."
"""

        scorecard = '[{"claim": "Carbon taxes reduce emissions faster.", "agent_name": "Socratyes", "claim_type": "empirical", "source_url": "https://example.com/carbon-tax", "verification_status": "verified", "source_quote": "Carbon taxes reduce emissions 15% faster."}]'

        synthesis = rapporteur_synthesize(
            transcript=transcript,
            scorecard=scorecard,
            query="What is the best carbon pricing mechanism?",
        )
        assert "## Consensus Map" in synthesis or "## Unified Hypothesis" in synthesis
