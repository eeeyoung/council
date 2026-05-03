"""
council/crews/audit_crew.py

Phase D: The Audit Loop.

Host A (Synthesis) attempts to write a Consensus Document.
Host B (Hostile Reviewer) evaluates it. If rejected, the state returns to "debating"
and a conflict_mandate is generated for the next round.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from crewai import Crew, Process, Task
from rich.console import Console

import council.config  # noqa: F401
from council.agents.host_a import build_host_a
from council.agents.host_b import build_host_b
from council.config import build_llm
from council.state import CouncilState

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_tasks_config() -> dict:
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        return yaml.safe_load(f)


def _parse_host_b_output(raw_output: str) -> tuple[bool, str]:
    """Parse Host B's JSON output to get (approved, conflict_mandate)."""
    cleaned = re.sub(r"```(?:json)?", "", raw_output).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    
    if start == -1 or end == -1:
        # Failsafe: if output is malformed, reject by default
        return False, "Host B produced malformed output. The panel must be more rigorous."

    try:
        data = json.loads(cleaned[start : end + 1])
        approved = data.get("approved", False)
        mandate = data.get("conflict_mandate", "Please refine the arguments.")
        return approved, mandate
    except Exception:
        return False, "Failed to parse Host B critique. Try again with more rigor."


def run_audit_loop(
    state: CouncilState,
    console: Console | None = None,
    verbose: bool = False,
) -> CouncilState:
    """Run Phase D: Audit Loop."""
    if console is None:
        console = Console()

    if state.status != "auditing":
        raise ValueError(f"Cannot run audit loop from state: {state.status}")

    console.print(f"\n[bold magenta]⟳  Phase D: The Audit Loop (Round {state.audit_round + 1}) begins...[/bold magenta]\n")
    
    tasks_cfg = _load_tasks_config()
    llm = build_llm()

    # Build Agents
    host_a = build_host_a(llm=llm)
    host_b = build_host_b(llm=llm)

    # Task 1: Host A Synthesis
    cfg_a = tasks_cfg["host_a_synthesis"]
    desc_a = cfg_a["description"].format(
        query=state.query,
        transcript=state.transcript_text,
        evidence_scorecard=state.evidence_scorecard_text,
    )
    task_a = Task(
        description=desc_a,
        expected_output=cfg_a["expected_output"],
        agent=host_a,
    )

    # Task 2: Host B Review
    cfg_b = tasks_cfg["host_b_review"]
    desc_b = cfg_b["description"].format(
        query=state.query,
        synthesis="",
        evidence_scorecard=state.evidence_scorecard_text,
    )
    task_b = Task(
        description=desc_b,
        expected_output=cfg_b["expected_output"],
        agent=host_b,
        context=[task_a],  # Evaluates Host A's output
    )

    crew = Crew(
        agents=[host_a, host_b],
        tasks=[task_a, task_b],
        process=Process.sequential,
        verbose=verbose,
    )

    console.print("[dim]  Host A is drafting the consensus...[/dim]")
    console.print("[dim]  Host B is reviewing the claims...[/dim]\n")

    result = crew.kickoff()
    
    # Extract outputs
    # Host A's output is in task_a.output
    # Host B's output is the final crew result
    
    tasks_output = getattr(result, "tasks_output", [])
    if len(tasks_output) > 0:
        a_out = tasks_output[0].raw if hasattr(tasks_output[0], "raw") else str(tasks_output[0])
        state.synthesis = a_out

    b_out = result.raw if hasattr(result, "raw") else str(result)

    # Append host outputs to the transcript so the GUI can render them
    state.add_transcript_entry(
        agent_name="Host A",
        discipline="Synthesis Host",
        speech=a_out,
        phase="audit",
    )
    state.add_transcript_entry(
        agent_name="Host B",
        discipline="Hostile Peer Reviewer",
        speech=b_out,
        phase="audit",
    )

    approved, mandate = _parse_host_b_output(b_out)

    if approved:
        console.print("[bold green]✓  Host B APPROVED the consensus.[/bold green] The symposium is complete.")
        state.status = "dossier"
        state.conflict_mandate = ""
    else:
        state.audit_round += 1
        if state.audit_round >= state.max_audit_rounds:
            console.print(
                f"[yellow]Maximum audit rounds ({state.max_audit_rounds}) reached.[/yellow] "
                f"[bold]Symposium halted.[/bold]"
            )
            state.status = "dossier"
            state.conflict_mandate = ""
            return state

        console.print(f"[bold red]✗  Host B REJECTED the consensus (Round {state.audit_round}).[/bold red]")
        console.print(f"[yellow]Mandate for next round:[/yellow] {mandate}\n")
        state.status = "debating"
        state.conflict_mandate = mandate

    return state
