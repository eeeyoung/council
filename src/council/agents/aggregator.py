"""
council/agents/aggregator.py

Research Aggregator — compiles all parallel research findings from the expert
panel into a structured summary before Phase C begins.
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


def build_aggregator(llm: object | None = None) -> Agent:
    """Build the Research Aggregator agent."""
    if llm is None:
        llm = build_llm(temperature=0.4)

    cfg = _load_agents_config()["aggregator"]

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
