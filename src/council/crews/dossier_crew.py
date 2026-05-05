"""
council/crews/dossier_crew.py

Phase E: Final Dossier Compilation.

Runs after the audit loop approves (state.status == "dossier").
The Fact-Checker maps claims to citations, then the Dossier Author compiles
the full publication-ready Markdown dossier.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from crewai import Crew, Process, Task
from rich.console import Console

import council.config  # noqa: F401
from council.agents.fact_checker import build_fact_checker
from council.agents.dossier_author import build_dossier_author
from council.config import build_llm
from council.state import CouncilState
from council.tools.library_tool import LibraryReadTool
from council.tools.search_tool import create_search_tool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_tasks_config() -> dict:
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        return yaml.safe_load(f)


def run_dossier(
    state: CouncilState,
    console: Console | None = None,
    verbose: bool = False,
) -> CouncilState:
    """Phase E: Compile the final research dossier."""
    if console is None:
        console = Console()

    if state.status != "dossier":
        raise ValueError(f"Cannot run dossier compilation from state: {state.status}")

    console.print("\n[bold blue]⟳  Phase E: Compiling Final Dossier…[/bold blue]\n")

    tasks_cfg = _load_tasks_config()

    # Build agents — Fact-Checker (precision) and Dossier Author (narrative)
    library_read = LibraryReadTool(session_id=state.session_id)
    search_tool = create_search_tool()
    fact_checker = build_fact_checker(
        library_read=library_read,
        search_tool=search_tool,
        llm=build_llm(temperature=0.2),
    )
    author = build_dossier_author(llm=build_llm(temperature=0.6))

    # Task 1: Evidence Scorecard
    cfg_sc = tasks_cfg["fact_checker_scorecard"]
    desc_sc = cfg_sc["description"].format(
        query=state.query,
        transcript=state.transcript_text,
    )
    task_scorecard = Task(
        description=desc_sc,
        expected_output=cfg_sc["expected_output"],
        agent=fact_checker,
    )

    # Task 2: Final Dossier — depends on scorecard
    cfg_dos = tasks_cfg["dossier_author_compile"]
    desc_dos = cfg_dos["description"].format(
        query=state.query,
        synthesis=state.synthesis or "(No synthesis available)",
        evidence_scorecard=state.evidence_scorecard_text,
        transcript=state.transcript_text,
        audit_round=state.audit_round,
    )
    task_dossier = Task(
        description=desc_dos,
        expected_output=cfg_dos["expected_output"],
        agent=author,
        context=[task_scorecard],
    )

    crew = Crew(
        agents=[fact_checker, author],
        tasks=[task_scorecard, task_dossier],
        process=Process.sequential,
        verbose=verbose,
    )

    console.print("[dim]  Fact-Checker is mapping claims to citations…[/dim]")
    result = crew.kickoff()

    # Extract dossier text from final task output
    tasks_output = getattr(result, "tasks_output", [])
    if len(tasks_output) >= 2:
        dossier_text = (
            tasks_output[1].raw
            if hasattr(tasks_output[1], "raw")
            else str(tasks_output[1])
        )
    else:
        dossier_text = result.raw if hasattr(result, "raw") else str(result)

    state.dossier_path = dossier_text
    state.status = "done"

    console.print("[bold green]✓  Dossier compiled successfully.[/bold green]")
    return state
