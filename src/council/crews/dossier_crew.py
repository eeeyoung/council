"""
council/crews/dossier_crew.py

Phase E: Final Dossier Compilation.

Runs after the audit loop approves (state.status == "dossier").
The RecorderAgent:
  1. Maps every claim in the transcript to a citation (scorecard task)
  2. Compiles the full publication-ready Markdown dossier
"""

from __future__ import annotations

from pathlib import Path

import yaml
from crewai import Crew, Process, Task
from rich.console import Console

import council.config  # noqa: F401
from council.agents.recorder import build_recorder_agent
from council.config import build_llm
from council.state import CouncilState
from council.tools.library_tool import LibraryReadTool

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
    llm = build_llm(temperature=0.3)

    # Build agent with library access
    library_read = LibraryReadTool(session_id=state.session_id)
    recorder = build_recorder_agent(library_read=library_read, llm=llm)

    # Task 1: Evidence Scorecard
    cfg_sc = tasks_cfg["recorder_scorecard"]
    desc_sc = cfg_sc["description"].format(
        query=state.query,
        transcript=state.transcript_text,
    )
    task_scorecard = Task(
        description=desc_sc,
        expected_output=cfg_sc["expected_output"],
        agent=recorder,
    )

    # Task 2: Final Dossier — depends on scorecard
    cfg_dos = tasks_cfg["recorder_dossier"]
    experts_list = "\n".join(
        f"- **{e.name}**: {e.discipline}" for e in state.experts
    )
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
        agent=recorder,
        context=[task_scorecard],
    )

    crew = Crew(
        agents=[recorder],
        tasks=[task_scorecard, task_dossier],
        process=Process.sequential,
        verbose=verbose,
    )

    console.print("[dim]  Recorder is mapping claims to citations…[/dim]")
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

    state.dossier_path = dossier_text  # store text temporarily
    state.status = "done"

    console.print("[bold green]✓  Dossier compiled successfully.[/bold green]")
    return state
