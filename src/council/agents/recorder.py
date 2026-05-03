"""
council/agents/recorder.py

RecorderAgent — Facts-checks the debate and compiles the dossier.

In Stage 3, this agent runs at the end of the debate. It takes the full transcript,
queries the shared library for evidence, and produces a structured Evidence Scorecard
mapping claims to citations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from crewai import Agent

import council.config  # noqa: F401
from council.config import build_llm
from council.state import EvidenceEntry
from council.tools.library_tool import LibraryReadTool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_agents_config() -> dict:
    with open(_CONFIG_DIR / "agents.yaml") as f:
        return yaml.safe_load(f)


def build_recorder_agent(
    library_read: LibraryReadTool,
    llm: object | None = None,
) -> Agent:
    """Build the RecorderAgent."""
    if llm is None:
        llm = build_llm(temperature=0.2)  # Low temp for factual mapping

    cfg = _load_agents_config()["recorder"]

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=[library_read],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )


def parse_scorecard_output(raw_output: str) -> list[EvidenceEntry]:
    """Parse the JSON array of evidence entries from the Recorder."""
    cleaned = re.sub(r"```(?:json)?", "", raw_output).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        return []

    json_str = cleaned[start : end + 1]
    # Fix trailing commas
    json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

    try:
        data = json.loads(json_str)
        if not isinstance(data, list):
            return []
        
        entries = []
        for item in data:
            entries.append(
                EvidenceEntry(
                    claim=item.get("claim", ""),
                    agent_name=item.get("agent_name", ""),
                    source_url=item.get("source_url", "UNCITED"),
                )
            )
        return entries
    except Exception:
        return []
