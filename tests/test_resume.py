"""
tests/test_resume.py

Tests for resume.py — reconstructing CouncilState from output files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from council.resume import load_session_from_outputs, resume_and_save
from council.state import CouncilState


@pytest.fixture
def mock_outputs_dir(tmp_path: Path) -> Path:
    session_id = "abc12345"
    out = tmp_path / "outputs"
    out.mkdir()

    panel = [
        {
            "name": "Dr. Alice Chen",
            "discipline": "Quantum Physics",
            "bias": "Theoretical purist",
            "persona_prompt": "Dr. Chen is a quantum physicist.",
        },
        {
            "name": "Dr. Bob Smith",
            "discipline": "Experimental Physics",
            "bias": "Empiricist",
            "persona_prompt": "Dr. Smith trusts only data.",
        },
    ]
    (out / f"{session_id}_panel.json").write_text(json.dumps(panel), encoding="utf-8")

    research = """# Structured Research Summary: Topic
## Dr. Alice Chen, Quantum Physics
### Finding 1: Title
**Key Finding:** Some finding text.
"""
    (out / f"{session_id}_research_dr_alice_chen.md").write_text(research, encoding="utf-8")

    research2 = """# Structured Research Summary: Topic
## Dr. Bob Smith, Experimental Physics
### Finding 1: Title
**Key Finding:** Another finding.
"""
    (out / f"{session_id}_research_dr_bob_smith.md").write_text(research2, encoding="utf-8")

    transcript = """# Phase C Debate Transcript (Session abc12345 - Round 0)

[Turn 1] **Dr. Alice Chen** (Quantum Physics):
Alice's argument goes here with multiple lines.
More content.

[Turn 2] **Dr. Bob Smith** (Experimental Physics):
Bob's rebuttal goes here.

[RAPPORTEUR] **Rapporteur** (Round 1):
Some synthesis text.
"""
    (out / f"{session_id}_transcript_r0.md").write_text(transcript, encoding="utf-8")

    scorecard = json.dumps([
        {
            "claim": "Quantum mechanics governs this",
            "agent_name": "Dr. Alice Chen",
            "claim_type": "empirical",
            "source_url": "https://example.com/quantum",
            "verification_status": "verified",
            "source_quote": "Quantum mechanics governs this behavior.",
            "relevance_note": None,
        },
        {
            "claim": "Data shows otherwise",
            "agent_name": "Dr. Bob Smith",
            "claim_type": "empirical",
            "source_url": "",
            "verification_status": "",
            "source_quote": "",
            "relevance_note": None,
        },
        {
            "claim": "Second claim by Alice",
            "agent_name": "Dr. Alice Chen",
            "claim_type": "inference",
            "source_url": "",
            "verification_status": "",
            "source_quote": "",
            "relevance_note": "Expert synthesis",
        },
    ])
    (out / f"{session_id}_scorecard_r0.json").write_text(scorecard, encoding="utf-8")

    return out


def test_load_session_from_outputs(mock_outputs_dir: Path):
    state = load_session_from_outputs("abc12345", str(mock_outputs_dir))

    assert state.session_id == "abc12345"
    assert state.status == "auditing"
    assert state.audit_round == 0
    assert len(state.experts) == 2
    assert state.experts[0].name == "Dr. Alice Chen"
    assert state.experts[1].discipline == "Experimental Physics"

    assert len(state.research_summaries) == 2
    assert "Dr. Alice Chen" in state.research_summaries

    assert len(state.transcript) == 2
    assert state.transcript[0].agent_name == "Dr. Alice Chen"
    assert state.transcript[0].turn == 1
    assert "Alice's argument" in state.transcript[0].speech
    assert state.transcript[1].agent_name == "Dr. Bob Smith"

    assert len(state.evidence_scorecard) == 3
    assert state.evidence_scorecard[0].claim == "Quantum mechanics governs this"
    assert state.evidence_scorecard[0].source_url == "https://example.com/quantum"
    assert state.evidence_scorecard[0].verification_status == "verified"
    assert state.evidence_scorecard[0].source_quote == "Quantum mechanics governs this behavior."
    assert state.evidence_scorecard[1].source_url == ""
    assert state.evidence_scorecard[1].verification_status == ""
    assert state.evidence_scorecard[2].claim_type == "inference"


def test_resume_and_save(mock_outputs_dir: Path, monkeypatch, tmp_path):
    temp_db = tmp_path / "council_test.db"
    monkeypatch.setattr("council.db.DB_PATH", temp_db)

    state = resume_and_save("abc12345", str(mock_outputs_dir))

    from council.db import load_state
    loaded = load_state("abc12345")
    assert loaded.status == "auditing"
    assert len(loaded.experts) == 2
    assert len(loaded.transcript) == 2
    assert len(loaded.evidence_scorecard) == 3


def test_missing_panel_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Panel file not found"):
        load_session_from_outputs("nonexistent", str(tmp_path))


def test_empty_scorecard_and_transcript_handled(mock_outputs_dir: Path):
    (mock_outputs_dir / "abc12345_transcript_r0.md").unlink()
    (mock_outputs_dir / "abc12345_scorecard_r0.json").unlink()

    state = load_session_from_outputs("abc12345", str(mock_outputs_dir))
    assert state.status == "auditing"
    assert state.transcript == []
    assert state.evidence_scorecard == []


def test_aggregation_file_skipped(mock_outputs_dir: Path):
    agg = "# Aggregated"
    (mock_outputs_dir / "abc12345_research___aggregation__.md").write_text(agg, encoding="utf-8")

    state = load_session_from_outputs("abc12345", str(mock_outputs_dir))
    assert len(state.research_summaries) == 2
    for k in state.research_summaries:
        assert "__aggregation__" not in k
