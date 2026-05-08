"""
council/crews/audit_crew.py

Phase D: Synthesis and Expectation Evaluation.

The Rapporteur synthesises the debate transcript and evidence scorecard into
a structured consensus document. The Expectation Evaluator then checks whether
the synthesis meets the user's desired outcome criteria. If not met, the loop
falls back to a new debate round with an expectation mandate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from crewai import Crew, Process, Task
from rich.console import Console

import council.config  # noqa: F401
from council.agents.rapporteur import build_rapporteur
from council.config import build_llm
from council.state import CouncilState
from council.tools.library_tool import LibraryReadTool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_tasks_config() -> dict:
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        return yaml.safe_load(f)


def _extract_text(output: object) -> str:
    """Extract raw text from a crewAI task output."""
    return output.raw if hasattr(output, "raw") else str(output)


def _parse_expectation_output(raw_output: str) -> tuple[bool, str]:
    """Parse the Expectation Evaluator's JSON output to get (met, gaps_text)."""
    cleaned = re.sub(r"```(?:json)?", "", raw_output).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1:
        return False, "Expectation Evaluator produced malformed output."

    try:
        data = json.loads(cleaned[start : end + 1])
        met = data.get("expectation_met", False)
        gaps = data.get("gaps", [])
        mandate = "\n".join(f"- {g}" for g in gaps) if gaps else "Address the expectation criteria."
        return met, mandate
    except Exception:
        return False, "Failed to parse Expectation Evaluator output."


def _evaluate_expectation(state, tasks_cfg: dict, verbose: bool = False) -> tuple[bool, str]:
    """Run the Expectation Evaluator. Returns (expectation_met, mandate_text)."""
    from council.agents.expectation_evaluator import build_expectation_evaluator

    evaluator = build_expectation_evaluator()
    cfg = tasks_cfg["expectation_evaluator_review"]

    desc = cfg["description"].format(
        query=state.query,
        expectation_type=state.expectation_type.replace("_", " ").title(),
        expectation_criteria=state.expectation_criteria,
        synthesis=state.synthesis or "(No synthesis available)",
    )

    task = Task(
        description=desc,
        expected_output=cfg["expected_output"],
        agent=evaluator,
    )

    crew = Crew(
        agents=[evaluator],
        tasks=[task],
        process=Process.sequential,
        verbose=verbose,
    )

    result = crew.kickoff()
    raw = _extract_text(result)
    return _parse_expectation_output(raw)


def _fallback_for_expectation(state, console, mandate: str) -> None:
    """Handle expectation NOT_MET: fall back to a new debate round."""
    state.audit_round += 1
    if state.audit_round >= state.max_audit_rounds:
        console.print(
            f"[yellow]Maximum audit rounds ({state.max_audit_rounds}) reached.[/yellow] "
            f"[bold]Symposium halted.[/bold]"
        )
        state.status = "compiling"
        state.expectation_mandate = ""
        return

    console.print(f"[bold yellow]→  Expectation Evaluator: EXPECTATION NOT MET.[/bold yellow]")
    console.print(f"[yellow]Gaps to address:[/yellow]\n{mandate}\n")
    state.status = "debating"
    state.expectation_mandate = mandate


def run_audit_loop(
    state: CouncilState,
    console: Console | None = None,
    verbose: bool = False,
) -> CouncilState:
    """Run Phase D: Rapporteur synthesis → Expectation evaluation."""
    if console is None:
        console = Console()

    if state.status != "auditing":
        raise ValueError(f"Cannot run audit loop from state: {state.status}")

    console.print(f"\n[bold magenta]⟳  Phase D: Synthesis & Evaluation (Round {state.audit_round + 1})...[/bold magenta]\n")

    tasks_cfg = _load_tasks_config()
    library_read = LibraryReadTool(session_id=state.session_id)
    llm_rapporteur = build_llm(temperature=0.4)

    rapporteur = build_rapporteur(library_read=library_read, llm=llm_rapporteur)

    # ── Step 1: Rapporteur Synthesis ──────────────────────────────────────
    cfg_synth = tasks_cfg["rapporteur_synthesis"]
    desc_synth = cfg_synth["description"].format(
        query=state.query,
        transcript=state.transcript_text,
        evidence_scorecard=state.evidence_scorecard_text,
    )
    desc_synth += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for library searches."

    if state.expectation_criteria:
        desc_synth += (
            f"\n\n=== SYMPOSIUM EXPECTATION ===\n"
            f"The user expects this symposium to produce a {state.expectation_type.replace('_', ' ').title()}.\n"
            f"Success criteria:\n{state.expectation_criteria}\n"
            f"Your synthesis should aim to satisfy these criteria."
        )

    task_synth = Task(
        description=desc_synth,
        expected_output=cfg_synth["expected_output"],
        agent=rapporteur,
    )

    crew = Crew(
        agents=[rapporteur],
        tasks=[task_synth],
        process=Process.sequential,
        verbose=verbose,
    )

    console.print("[dim]  Rapporteur is drafting the synthesis...[/dim]\n")
    result = crew.kickoff()

    synthesis = _extract_text(result.tasks_output[0]) if getattr(result, "tasks_output", []) else _extract_text(result)
    state.synthesis = synthesis

    state.add_transcript_entry(
        agent_name="Rapporteur",
        discipline="Rapporteur",
        speech=synthesis,
        phase="audit",
    )

    # ── Step 2: Expectation Evaluation ────────────────────────────────────
    if state.expectation_criteria:
        exp_met, exp_mandate = _evaluate_expectation(state, tasks_cfg, verbose)
        state.expectation_met = exp_met
        if exp_met:
            console.print("[bold green]✓  Expectation Evaluator: EXPECTATION MET.[/bold green] The symposium is complete.")
            state.status = "compiling"
        else:
            state.expectation_mandate = exp_mandate
            _fallback_for_expectation(state, console, exp_mandate)
            return state
    else:
        console.print("[bold green]✓  Synthesis complete.[/bold green] The symposium is complete.")
        state.status = "compiling"

    return state
