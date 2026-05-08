"""
tests/test_audit_loop.py

Stage 4 tests for the Audit Phase logic and Expectation Evaluator parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.crews.audit_crew import _parse_expectation_output


def test_parse_expectation_met():
    raw = '''
    ```json
    {
        "expectation_met": true,
        "gaps": []
    }
    ```
    '''
    met, mandate = _parse_expectation_output(raw)
    assert met is True


def test_parse_expectation_not_met():
    raw = '''
    {
        "expectation_met": false,
        "gaps": [
            "The synthesis does not address resource constraints.",
            "Missing timeline for the proposed plan."
        ]
    }
    '''
    met, mandate = _parse_expectation_output(raw)
    assert met is False
    assert "resource constraints" in mandate
    assert "Missing timeline" in mandate


def test_parse_expectation_malformed():
    raw = "I think the output doesn't meet expectations."
    met, mandate = _parse_expectation_output(raw)
    assert met is False
    assert "malformed output" in mandate
