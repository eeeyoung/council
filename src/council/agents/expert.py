"""
council/agents/expert.py

Expert agent factory for COUNCIL.

Creates crewAI Agent objects from ExpertDefinition objects stored in CouncilState.
Each expert is fully autonomous — they search the web, store findings in the
shared library, and contribute to the debate with their distinct persona.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from crewai import Agent

import council.config  # noqa: F401
from council.config import build_llm
from council.state import ExpertDefinition
from council.tools.library_tool import LibraryReadTool, LibraryWriteTool
from council.tools.pdf_tool import PDFParserTool
from council.tools.search_tool import WebSearchTool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_agents_config() -> dict:
    with open(_CONFIG_DIR / "agents.yaml") as f:
        return yaml.safe_load(f)


def build_expert_agent(
    expert: ExpertDefinition,
    search_tool: WebSearchTool,
    library_write: LibraryWriteTool,
    library_read: LibraryReadTool,
    pdf_tool: PDFParserTool,
    llm: object | None = None,
    verbose: bool = False,
) -> Agent:
    """
    Build a crewAI Agent from an ExpertDefinition.

    The agent receives:
    - A persona-rich backstory combining the expert definition + base template
    - Web search, library read/write, and PDF tools
    - The same LLM as the moderator (configurable)
    """
    if llm is None:
        llm = build_llm(temperature=0.8)  # Slightly higher temp for diverse debate contributions

    cfg = _load_agents_config()
    backstory_template = cfg["expert_base"]["backstory_template"]

    backstory = backstory_template.format(
        persona_prompt=expert.persona_prompt,
        discipline=expert.discipline,
        bias=expert.bias,
    )

    return Agent(
        role=f"{expert.discipline} Expert",
        goal=(
            f"As {expert.name}, investigate the research question from the perspective "
            f"of {expert.discipline}. Find compelling, evidence-backed insights that your "
            f"disciplinary training uniquely reveals. Challenge lazy assumptions and "
            f"push the debate toward rigorous scientific truth."
        ),
        backstory=backstory,
        tools=[search_tool, library_write, library_read, pdf_tool],
        llm=llm,
        verbose=verbose,
        allow_delegation=False,
        max_iter=8,  # Allow room for search + 3-5 writes + final report
    )


def build_expert_agents(
    experts: list[ExpertDefinition],
    search_tool: WebSearchTool,
    library_write: LibraryWriteTool,
    library_read: LibraryReadTool,
    pdf_tool: PDFParserTool,
    llm: object | None = None,
    verbose: bool = False,
) -> list[Agent]:
    """Build all expert agents for the given panel."""
    if llm is None:
        llm = build_llm(temperature=0.8)

    return [
        build_expert_agent(
            expert=expert,
            search_tool=search_tool,
            library_write=library_write,
            library_read=library_read,
            pdf_tool=pdf_tool,
            llm=llm,
            verbose=verbose,
        )
        for expert in experts
    ]
