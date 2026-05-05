"""
tests/test_expectation.py

Tests for the symposium expectation framework:
state fields, Expectation Evaluator output parsing, and criteria injection.
"""

from __future__ import annotations

import json

from council.crews.audit_crew import _parse_expectation_output
from council.state import CouncilState


# ── CouncilState expectation fields ───────────────────────────────────────

def test_state_expectation_defaults():
    state = CouncilState(query="Test")
    assert state.expectation_type == ""
    assert state.expectation_detail == ""
    assert state.expectation_criteria == ""
    assert state.expectation_met is None
    assert state.expectation_mandate is None


def test_state_expectation_set():
    state = CouncilState(
        query="Test",
        expectation_type="definitive_answer",
        expectation_detail="I need a clear conclusion.",
        expectation_criteria="1. Must pick a winner\n2. Must cite evidence",
    )
    assert state.expectation_type == "definitive_answer"
    assert state.expectation_detail == "I need a clear conclusion."
    assert "Must pick a winner" in state.expectation_criteria


# ── _parse_expectation_output ─────────────────────────────────────────────

def test_parse_expectation_met():
    raw = json.dumps({
        "expectation_met": True,
        "verdict": "EXPECTATION_MET",
        "criteria_results": [
            {"criterion": "Must pick a winner", "satisfied": True, "note": "Clearly chose WIMPs."}
        ],
        "gaps": [],
    })
    met, mandate = _parse_expectation_output(raw)
    assert met is True
    # When met, mandate can be empty or the default (which won't be used since we proceeded to dossier)


def test_parse_expectation_not_met():
    raw = json.dumps({
        "expectation_met": False,
        "verdict": "EXPECTATION_NOT_MET",
        "criteria_results": [
            {"criterion": "Must include timeline", "satisfied": False, "note": "No timeline provided."}
        ],
        "gaps": ["No implementation timeline", "Missing resource estimates"],
    })
    met, mandate = _parse_expectation_output(raw)
    assert met is False
    assert "implementation timeline" in mandate
    assert "resource estimates" in mandate


def test_parse_expectation_malformed():
    met, mandate = _parse_expectation_output("Not a JSON response.")
    assert met is False
    assert "malformed" in mandate.lower()


def test_parse_expectation_empty_json():
    met, mandate = _parse_expectation_output("{}")
    assert met is False
