"""
council/agents/host_b.py

Host B (Hostile Peer Reviewer)
Evaluates Host A's consensus document against the Evidence Scorecard.
Outputs structured JSON indicating approval or rejection, with a mandate for
the next round if rejected.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from crewai import Agent

import council.config  # noqa: F401
from council.config import build_llm

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_agents_config() -> dict:
    with open(_CONFIG_DIR / "agents.yaml") as f:
        return yaml.safe_load(f)


def build_host_b(llm: object | None = None) -> Agent:
    """Build Host B (Hostile Peer Reviewer)."""
    if llm is None:
        llm = build_llm(temperature=0.2)  # Low temp for strict logic

    cfg = _load_agents_config()["host_b"]

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
