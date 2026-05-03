"""
council/agents/host_a.py

Host A (Synthesis Host)
Attempts to forge a consensus document from the debate transcript and scorecard.
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


def build_host_a(llm: object | None = None) -> Agent:
    """Build Host A (Synthesis Host)."""
    if llm is None:
        llm = build_llm(temperature=0.4)

    cfg = _load_agents_config()["host_a"]

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
