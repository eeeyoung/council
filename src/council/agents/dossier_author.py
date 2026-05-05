"""
council/agents/dossier_author.py

Dossier Author — compiles the final publication-ready research dossier from
the expert research, debate transcript, synthesis, and evidence scorecard.
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


def build_dossier_author(llm: object | None = None) -> Agent:
    """Build the Dossier Author agent."""
    if llm is None:
        llm = build_llm(temperature=0.6)

    cfg = _load_agents_config()["dossier_author"]

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
