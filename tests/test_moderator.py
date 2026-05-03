"""
tests/test_moderator.py

Stage 1 smoke tests for the ModeratorAgent.

These tests are intentionally lightweight — they test the parsing logic
without making real LLM calls, plus one integration test (skipped by default).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.agents.moderator import _parse_expert_definitions
from council.state import CouncilState, ExpertDefinition


# ------------------------------------------------------------------ #
# Unit tests for JSON parsing (no LLM calls)
# ------------------------------------------------------------------ #


VALID_JSON = json.dumps(
    [
        {
            "name": "Dr. Lena Hartmann",
            "discipline": "Theoretical Astrophysics",
            "bias": "Prefers WIMP-based dark matter models",
            "persona_prompt": "A meticulous theorist who insists on mathematical elegance.",
        },
        {
            "name": "Prof. James Okoro",
            "discipline": "Experimental Particle Physics",
            "bias": "Skeptical of unfalsifiable theories",
            "persona_prompt": "Demands reproducible experimental evidence above all.",
        },
    ]
)


def test_parse_valid_json():
    experts = _parse_expert_definitions(VALID_JSON)
    assert len(experts) == 2
    assert experts[0].name == "Dr. Lena Hartmann"
    assert experts[1].discipline == "Experimental Particle Physics"


def test_parse_json_with_markdown_fences():
    fenced = f"```json\n{VALID_JSON}\n```"
    experts = _parse_expert_definitions(fenced)
    assert len(experts) == 2


def test_parse_json_with_preamble():
    raw = f"Here is the expert panel:\n\n{VALID_JSON}\n\nI hope this helps!"
    experts = _parse_expert_definitions(raw)
    assert len(experts) == 2


def test_parse_json_with_trailing_comma():
    bad_json = '[{"name":"Dr. X","discipline":"Physics","bias":"WIMP","persona_prompt":"A physicist.",},]'
    experts = _parse_expert_definitions(bad_json)
    assert len(experts) == 1
    assert experts[0].name == "Dr. X"


def test_parse_empty_array_raises():
    with pytest.raises(ValueError, match="empty"):
        _parse_expert_definitions("[]")


def test_parse_missing_field_raises():
    bad = '[{"name": "Dr. X", "discipline": "Physics"}]'  # missing bias and persona_prompt
    with pytest.raises(ValueError):
        _parse_expert_definitions(bad)


def test_parse_no_json_raises():
    with pytest.raises(ValueError, match="valid JSON array"):
        _parse_expert_definitions("I cannot produce a JSON array.")


# ------------------------------------------------------------------ #
# CouncilState tests
# ------------------------------------------------------------------ #


def test_council_state_defaults():
    state = CouncilState(query="Is dark matter a WIMP or an axion?")
    assert state.status == "curating"
    assert state.experts == []
    assert state.audit_round == 0
    assert state.session_id  # auto-generated


def test_transcript_text_empty():
    state = CouncilState(query="test")
    assert "first speaker" in state.transcript_text


def test_add_transcript_entry():
    state = CouncilState(query="test")
    state.add_transcript_entry("Dr. X", "Physics", "Dark matter is a WIMP.")
    assert len(state.transcript) == 1
    assert state.transcript[0].turn == 1
    assert state.next_turn_number == 2


def test_transcript_text_renders():
    state = CouncilState(query="test")
    state.add_transcript_entry("Dr. X", "Physics", "My argument here.")
    text = state.transcript_text
    assert "Dr. X" in text
    assert "My argument here." in text


# ------------------------------------------------------------------ #
# Integration test (skipped unless --run-integration flag is set)
# ------------------------------------------------------------------ #


@pytest.mark.skip(reason="Requires real LLM API keys — run manually")
def test_full_curation_integration():
    """
    Full integration test: actually calls the LLM and verifies the output.
    Run manually: uv run pytest tests/test_moderator.py -k integration -s
    """
    from council.agents.moderator import run_curation

    state = CouncilState(
        query="Is dark matter a WIMP or an axion?",
        max_experts=3,
    )
    experts = run_curation(state)

    assert len(experts) >= 2
    for expert in experts:
        assert expert.name
        assert expert.discipline
        assert expert.bias
        assert expert.persona_prompt
        print(f"  • {expert.name} — {expert.discipline}")
