"""
tests/test_audit_loop.py

Stage 4 tests for the Audit Phase logic and Discussant parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.crews.audit_crew import _parse_discussant_output


def test_parse_discussant_approved():
    raw = '''
    ```json
    {
        "approved": true,
        "conflict_mandate": ""
    }
    ```
    '''
    approved, mandate = _parse_discussant_output(raw)
    assert approved is True


def test_parse_discussant_rejected():
    raw = '''
    {
        "approved": false,
        "conflict_mandate": "The evidence does not support the conclusion on X."
    }
    '''
    approved, mandate = _parse_discussant_output(raw)
    assert approved is False
    assert "The evidence does not support" in mandate


def test_parse_discussant_malformed():
    raw = "I think the debate is bad, so I reject it."
    approved, mandate = _parse_discussant_output(raw)
    assert approved is False
    assert "malformed output" in mandate
