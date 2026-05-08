"""
council/agents/fact_checker.py

Fact-Checker agent — traces every significant claim in the debate transcript
to a citation in the shared research library, verifies sources via web search,
and produces the Evidence Scorecard.
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
from council.tools.search_tool import WebSearchTool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_agents_config() -> dict:
    with open(_CONFIG_DIR / "agents.yaml") as f:
        return yaml.safe_load(f)


def build_fact_checker(
    library_read: LibraryReadTool,
    search_tool: WebSearchTool | None = None,
    llm: object | None = None,
) -> Agent:
    """Build the Fact-Checker agent."""
    if llm is None:
        llm = build_llm(temperature=0.2)

    cfg = _load_agents_config()["fact_checker"]

    tools = [library_read]
    if search_tool:
        tools.append(search_tool)

    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=tools,
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )


def parse_scorecard_output(raw_output: str) -> list[EvidenceEntry]:
    """Parse the JSON array of evidence entries from the Fact-Checker."""
    cleaned = re.sub(r"```(?:json)?", "", raw_output).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        return []

    json_str = cleaned[start : end + 1]
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
                    claim_type=item.get("claim_type", "empirical"),
                    source_url=item.get("source_url", ""),
                    verification_status=item.get("verification_status", ""),
                    source_quote=item.get("source_quote", ""),
                    relevance_note=item.get("relevance_note"),
                )
            )
        return entries
    except Exception:
        return []
