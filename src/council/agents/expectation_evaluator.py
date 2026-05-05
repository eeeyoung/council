"""
council/agents/expectation_evaluator.py

Expectation Evaluator — runs after the Discussant approves scientific rigor.
Checks whether the synthesis satisfies the user's success criteria.
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


def build_expectation_evaluator(llm: object | None = None) -> Agent:
    """Build the Expectation Evaluator agent."""
    if llm is None:
        llm = build_llm(temperature=0.2)

    cfg = _load_agents_config()["expectation_evaluator"]

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
