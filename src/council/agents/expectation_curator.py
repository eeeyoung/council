"""
council/agents/expectation_curator.py

Expectation Curator — takes the user's research question and desired outcome
type, and produces structured success criteria that guide the entire symposium.
Runs in Phase A after panel generation.
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


def build_expectation_curator(llm: object | None = None) -> Agent:
    """Build the Expectation Curator agent."""
    if llm is None:
        llm = build_llm(temperature=0.4)

    cfg = _load_agents_config()["expectation_curator"]

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
