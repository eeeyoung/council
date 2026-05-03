"""
tests/test_debate.py

Stage 3 tests for the Debate Phase and RecorderAgent logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.agents.recorder import parse_scorecard_output
from council.state import CouncilState, ExpertDefinition


def test_parse_scorecard_valid_json():
    raw_json = '''
    [
        {
            "claim": "Axions solve the strong CP problem.",
            "agent_name": "Dr. Kenji Tanaka",
            "source_url": "https://arxiv.org/abs/example"
        },
        {
            "claim": "WIMPs are ruled out by recent xenon experiments.",
            "agent_name": "Dr. Lena Hartmann",
            "source_url": "UNCITED"
        }
    ]
    '''
    entries = parse_scorecard_output(raw_json)
    assert len(entries) == 2
    assert entries[0].claim == "Axions solve the strong CP problem."
    assert entries[0].source_url == "https://arxiv.org/abs/example"
    assert entries[1].source_url == "UNCITED"


def test_parse_scorecard_with_markdown_fences():
    raw = '''Here is the evidence scorecard:
    ```json
    [
        {"claim": "A", "agent_name": "Agent A", "source_url": "URL"}
    ]
    ```
    '''
    entries = parse_scorecard_output(raw)
    assert len(entries) == 1
    assert entries[0].claim == "A"


def test_parse_scorecard_invalid_json():
    raw = "I could not find any evidence to support the claims."
    entries = parse_scorecard_output(raw)
    assert len(entries) == 0


def test_debate_crew_imports():
    from council.crews.debate_crew import _run_single_turn, run_debate
    assert callable(run_debate)
    assert callable(_run_single_turn)


@pytest.mark.skip(reason="Requires real API keys and network — run manually")
def test_full_debate_integration():
    """
    Integration test for Phase C.
    Requires Phase B to have run first to populate library.
    """
    from council.crews.debate_crew import run_debate

    state = CouncilState(query="Is dark matter a WIMP or an axion?")
    state.status = "debating"
    state.experts = [
        ExpertDefinition(
            name="Dr. Test",
            discipline="Physics",
            bias="None",
            persona_prompt="A generic physicist."
        )
    ]
    
    result = run_debate(state)
    assert result.status == "auditing"
    assert len(result.transcript) > 0
    assert len(result.evidence_scorecard) >= 0
