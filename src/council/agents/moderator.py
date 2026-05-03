"""
council/agents/moderator.py

ModeratorAgent — analyzes the user query and generates the expert panel.

The Moderator is the first agent to run. It receives the raw research question
and outputs a structured JSON list of ExpertDefinition objects. The user then
reviews and approves (or edits) the panel before Phase B begins.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

import council.config  # noqa: F401 — triggers load_dotenv at import time
from council.config import build_llm
from council.state import CouncilState, ExpertDefinition

# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_config() -> tuple[dict, dict]:
    """Load agents.yaml and tasks.yaml."""
    with open(_CONFIG_DIR / "agents.yaml") as f:
        agents_cfg = yaml.safe_load(f)
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        tasks_cfg = yaml.safe_load(f)
    return agents_cfg, tasks_cfg


# ------------------------------------------------------------------ #
# ModeratorAgent
# ------------------------------------------------------------------ #


def build_moderator_agent(llm: object | None = None) -> Agent:
    """Construct the crewAI Moderator agent from config."""
    if llm is None:
        llm = build_llm()
    agents_cfg, _ = _load_config()
    cfg = agents_cfg["moderator"]
    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"] + "\n\n" + cfg["output_instructions"],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def build_curation_task(agent: Agent, state: CouncilState) -> Task:
    """Build the panel curation task for the given state."""
    _, tasks_cfg = _load_config()
    cfg = tasks_cfg["moderator_curation"]
    description = cfg["description"].format(
        query=state.query,
        max_experts=state.max_experts,
    )
    return Task(
        description=description,
        expected_output=cfg["expected_output"],
        agent=agent,
    )


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #


def run_curation(state: CouncilState) -> list[ExpertDefinition]:
    """
    Run the ModeratorAgent to generate an expert panel for the given query.

    Returns a list of ExpertDefinition objects.
    Raises ValueError if the LLM output cannot be parsed.
    """
    agent = build_moderator_agent()
    task = build_curation_task(agent, state)

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    result = crew.kickoff()
    raw_output: str = result.raw if hasattr(result, "raw") else str(result)

    return _parse_expert_definitions(raw_output)


def _parse_expert_definitions(raw: str) -> list[ExpertDefinition]:
    """
    Extract and parse the JSON array from the LLM output.
    Handles common LLM formatting issues (markdown fences, trailing commas).
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()

    # Find the first '[' and last ']' to extract the array
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(
            f"ModeratorAgent did not return a valid JSON array.\nRaw output:\n{raw}"
        )

    json_str = cleaned[start : end + 1]

    # Fix trailing commas (common LLM mistake)
    json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse expert panel JSON: {exc}\nExtracted JSON:\n{json_str}"
        ) from exc

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got: {type(data)}")

    experts: list[ExpertDefinition] = []
    for i, item in enumerate(data):
        try:
            experts.append(ExpertDefinition(**item))
        except Exception as exc:
            raise ValueError(
                f"Expert definition #{i} is malformed: {exc}\nItem: {item}"
            ) from exc

    if not experts:
        raise ValueError("ModeratorAgent returned an empty expert panel.")

    return experts
