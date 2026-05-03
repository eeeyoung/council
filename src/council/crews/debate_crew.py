"""
council/crews/debate_crew.py

Phase C: The Sequential Symposium.

In this phase, experts speak one by one. To support dynamic transcript injection
and allow for future user interruptions (the Director's Console), we run each
speaker's turn as a single-agent Crew execution in a loop.

At the end of the loop, the RecorderAgent reviews the full transcript and generates
the Evidence Scorecard.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from crewai import Crew, Process, Task
from rich.console import Console

import council.config  # noqa: F401
from council.agents.expert import build_expert_agent
from council.agents.recorder import build_recorder_agent, parse_scorecard_output
from council.config import build_llm
from council.state import CouncilState
from council.tools.library_tool import create_library_tools
from council.tools.pdf_tool import create_pdf_tool
from council.tools.search_tool import create_search_tool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_tasks_config() -> dict:
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        return yaml.safe_load(f)


def _run_single_turn(
    expert_def,
    state: CouncilState,
    search_tool,
    library_write,
    library_read,
    pdf_tool,
    llm,
    tasks_cfg: dict,
    verbose: bool = False,
) -> str:
    """Execute a single speaking turn for one expert."""
    agent = build_expert_agent(
        expert=expert_def,
        search_tool=search_tool,
        library_write=library_write,
        library_read=library_read,
        pdf_tool=pdf_tool,
        llm=llm,
        verbose=verbose,
    )

    cfg = tasks_cfg["expert_debate"]
    
    # Inject the live transcript and any active conflict mandate
    description = cfg["description"].format(
        name=expert_def.name,
        discipline=expert_def.discipline,
        query=state.query,
        transcript=state.transcript_text,
    )

    if state.conflict_mandate:
        description += (
            f"\n\n=== HOST B MANDATE ===\n"
            f"The previous round was rejected by the Auditor with this instruction:\n"
            f"{state.conflict_mandate}\n"
            f"You MUST address this in your response."
        )

    description += (
        f"\n\nIMPORTANT: When calling library_write or library_read tools, "
        f"always use session_id='{state.session_id}'."
    )

    task = Task(
        description=description,
        expected_output=cfg["expected_output"],
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=verbose,
    )

    result = crew.kickoff()
    return result.raw if hasattr(result, "raw") else str(result)


def run_debate(
    state: CouncilState,
    console: Console | None = None,
    verbose: bool = False,
) -> CouncilState:
    """
    Run Phase C: The Sequential Debate + Evidence Scorecard.
    """
    if console is None:
        console = Console()

    if state.status != "debating":
        raise ValueError(f"Cannot start debate from state: {state.status}")

    # Build shared tools
    search_tool = create_search_tool()
    library_write, library_read = create_library_tools()
    pdf_tool = create_pdf_tool()
    llm = build_llm(temperature=0.8)
    tasks_cfg = _load_tasks_config()

    console.print(f"\n[bold cyan]⟳  The Symposium Begins (Round {state.audit_round + 1})[/bold cyan]\n")

    # 1. The Debate Loop
    for expert_def in state.experts:
        console.print(f"[bold yellow]→ {expert_def.name} is preparing their statement...[/bold yellow]")
        
        speech = _run_single_turn(
            expert_def=expert_def,
            state=state,
            search_tool=search_tool,
            library_write=library_write,
            library_read=library_read,
            pdf_tool=pdf_tool,
            llm=llm,
            tasks_cfg=tasks_cfg,
            verbose=verbose,
        )

        state.add_transcript_entry(
            agent_name=expert_def.name,
            discipline=expert_def.discipline,
            speech=speech.strip(),
            phase="debate",
        )
        
        # Display preview
        preview = speech[:150].replace("\n", " ") + "…"
        console.print(f"  [cyan]\"{preview}\"[/cyan]\n")

    # 2. The Evidence Scorecard
    console.print("[bold yellow]⟳  RecorderAgent is compiling the Evidence Scorecard...[/bold yellow]")
    
    recorder_agent = build_recorder_agent(library_read=library_read)
    rec_cfg = tasks_cfg["recorder_scorecard"]
    
    rec_desc = rec_cfg["description"].format(
        query=state.query,
        transcript=state.transcript_text,
    )
    rec_desc += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for library searches."

    rec_task = Task(
        description=rec_desc,
        expected_output=rec_cfg["expected_output"],
        agent=recorder_agent,
    )

    rec_crew = Crew(
        agents=[recorder_agent],
        tasks=[rec_task],
        verbose=verbose,
    )

    rec_result = rec_crew.kickoff()
    raw_scorecard = rec_result.raw if hasattr(rec_result, "raw") else str(rec_result)
    
    state.evidence_scorecard = parse_scorecard_output(raw_scorecard)
    state.status = "auditing"

    console.print(
        f"[bold green]✓ Debate round complete.[/bold green] "
        f"Scorecard contains {len(state.evidence_scorecard)} evidence mappings.\n"
    )

    return state
