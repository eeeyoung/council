"""
council/agents/discussant.py

Discussant
Evaluates the Rapporteur's consensus document against the Evidence Scorecard.
Outputs structured JSON indicating approval or rejection, with a mandate for
the next round if rejected.
Has library read access to independently verify suspicious claims.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from crewai import Agent

import council.config  # noqa: F401
from council.config import build_llm
from council.tools.library_tool import LibraryReadTool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_agents_config() -> dict:
    with open(_CONFIG_DIR / "agents.yaml") as f:
        return yaml.safe_load(f)


def build_discussant(
    library_read: LibraryReadTool | None = None,
    llm: object | None = None,
) -> Agent:
    """Build the Discussant agent."""
    if llm is None:
        llm = build_llm(temperature=0.2)

    cfg = _load_agents_config()["discussant"]

    tools = [library_read] if library_read else []

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=tools,
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
