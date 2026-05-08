"""
tests/test_workspace_agents.py

Phase 2 tests for workspace agent wrappers.
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
    expert_respond,
    expert_research,
    fact_check_source,
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
        assert ed.discipline == "Climate Economics"
        assert ed.bias == "Prefers carbon taxation"
        assert ed.persona_prompt == "A pragmatic economist."

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
        pool.sources.append(PoolSource(
            url="https://example.com/unverified",
            title="Unverified Source",
            snippet="Suspicious claim...",
            verification_status="",
        ))

        text = _pool_to_text(pool)
        assert "A Key Paper" in text
        assert "[verified]" in text
        assert "[pending]" in text
        assert "https://example.com/paper" in text

    def test_pool_to_text_with_opinions(self):
        pool = KnowledgePool()
        pool.opinions.append(Opinion(text="Carbon tax is more efficient than cap-and-trade."))

        text = _pool_to_text(pool)
        assert "Carbon tax is more efficient" in text
        assert "EXISTING OPINIONS" in text

    def test_parse_json_valid(self):
        result = _parse_json('[{"key": "value"}]')
        assert result == [{"key": "value"}]

    def test_parse_json_with_markdown_fence(self):
        result = _parse_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_invalid(self):
        result = _parse_json("not json at all")
        assert result is None

    def test_parse_json_trailing_comma(self):
        result = _parse_json('[{"key": "value",}]')
        assert result == [{"key": "value"}]


class TestAgentImports:
    """Verify all agent wrappers are importable with correct signatures."""

    def test_expert_respond_importable(self):
        assert callable(expert_respond)

    def test_expert_research_importable(self):
        assert callable(expert_research)

    def test_fact_check_source_importable(self):
        assert callable(fact_check_source)

    def test_moderator_propose_panel_importable(self):
        assert callable(moderator_propose_panel)

    def test_rapporteur_synthesize_importable(self):
        assert callable(rapporteur_synthesize)


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
            query="What is the best carbon pricing mechanism?",
            message="What does the economic evidence say about carbon taxes vs cap-and-trade?",
        )
        assert "## Position" in response
        assert "**Keywords:**" in response

    def test_rapporteur_synthesize_with_transcript(self):
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
