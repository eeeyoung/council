"""
council/crews/audit_crew.py

Phase D: The Audit Loop.

The Rapporteur drafts a Consensus Document. The Discussant evaluates it.
If rejected, the Rapporteur gets one chance to rebut — directly addressing the
Discussant's critique and revising the synthesis. Only if the rebuttal is also
rejected does the loop fall back to a new debate round with a conflict mandate.
Both agents have library read access to independently verify claims.
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
from council.agents.discussant import build_discussant
from council.config import build_llm
from council.state import CouncilState
from council.tools.library_tool import LibraryReadTool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_tasks_config() -> dict:
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        return yaml.safe_load(f)


def _parse_discussant_output(raw_output: str) -> tuple[bool, str]:
    """Parse the Discussant's JSON output to get (approved, conflict_mandate)."""
    cleaned = re.sub(r"```(?:json)?", "", raw_output).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1:
        return False, "Discussant produced malformed output. The panel must be more rigorous."

    try:
        data = json.loads(cleaned[start : end + 1])
        approved = data.get("approved", False)
        mandate = data.get("conflict_mandate", "Please refine the arguments.")
        return approved, mandate
    except Exception:
        return False, "Failed to parse Discussant critique. Try again with more rigor."


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
    raw = result.raw if hasattr(result, "raw") else str(result)
    return _parse_expectation_output(raw)


def _fallback_for_expectation(state, console, mandate: str) -> None:
    """Handle expectation NOT_MET: fall back to a new debate round."""
    state.audit_round += 1
    if state.audit_round >= state.max_audit_rounds:
        console.print(
            f"[yellow]Maximum audit rounds ({state.max_audit_rounds}) reached.[/yellow] "
            f"[bold]Symposium halted.[/bold]"
        )
        state.status = "dossier"
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
    """Run Phase D: Audit Loop with rebuttal step."""
    if console is None:
        console = Console()

    if state.status != "auditing":
        raise ValueError(f"Cannot run audit loop from state: {state.status}")

    console.print(f"\n[bold magenta]⟳  Phase D: The Audit Loop (Round {state.audit_round + 1}) begins...[/bold magenta]\n")

    tasks_cfg = _load_tasks_config()

    # Build shared library tool — both agents can independently verify claims
    library_read = LibraryReadTool(session_id=state.session_id)
    llm_rapporteur = build_llm(temperature=0.4)
    llm_discussant = build_llm(temperature=0.2)

    rapporteur = build_rapporteur(library_read=library_read, llm=llm_rapporteur)
    discussant = build_discussant(library_read=library_read, llm=llm_discussant)

    # ── Step 1: Rapporteur Synthesis ──────────────────────────────────────
    cfg_synth = tasks_cfg["rapporteur_synthesis"]
    desc_synth = cfg_synth["description"].format(
        query=state.query,
        transcript=state.transcript_text,
        evidence_scorecard=state.evidence_scorecard_text,
    )
    desc_synth += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for library searches."

    task_synth = Task(
        description=desc_synth,
        expected_output=cfg_synth["expected_output"],
        agent=rapporteur,
    )

    # ── Step 2: Discussant Review ─────────────────────────────────────────
    cfg_review = tasks_cfg["discussant_review"]
    desc_review = cfg_review["description"].format(
        query=state.query,
        synthesis="",
        evidence_scorecard=state.evidence_scorecard_text,
    )
    desc_review += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for library searches."

    task_review = Task(
        description=desc_review,
        expected_output=cfg_review["expected_output"],
        agent=discussant,
        context=[task_synth],
    )

    crew_1 = Crew(
        agents=[rapporteur, discussant],
        tasks=[task_synth, task_review],
        process=Process.sequential,
        verbose=verbose,
    )

    console.print("[dim]  Rapporteur is drafting the consensus...[/dim]")
    console.print("[dim]  Discussant is reviewing the claims...[/dim]\n")

    result_1 = crew_1.kickoff()
    tasks_out_1 = getattr(result_1, "tasks_output", [])

    synthesis = _extract_text(tasks_out_1[0]) if len(tasks_out_1) > 0 else ""
    critique = _extract_text(tasks_out_1[1]) if len(tasks_out_1) > 1 else _extract_text(result_1)

    state.synthesis = synthesis

    state.add_transcript_entry(
        agent_name="Rapporteur",
        discipline="Rapporteur",
        speech=synthesis,
        phase="audit",
    )
    state.add_transcript_entry(
        agent_name="Discussant",
        discipline="Discussant",
        speech=critique,
        phase="audit",
    )

    approved, mandate = _parse_discussant_output(critique)

    if approved:
        console.print("[bold green]✓  Discussant APPROVED the consensus.[/bold green]")
        state.conflict_mandate = ""
        # Run Expectation Evaluator
        if state.expectation_criteria:
            exp_met, exp_mandate = _evaluate_expectation(state, tasks_cfg, verbose)
            state.expectation_met = exp_met
            if exp_met:
                console.print("[bold green]✓  Expectation Evaluator: EXPECTATION MET.[/bold green] The symposium is complete.")
                state.status = "dossier"
            else:
                state.expectation_mandate = exp_mandate
                _fallback_for_expectation(state, console, exp_mandate)
                return state
        else:
            state.status = "dossier"
        return state

    # ── Step 3: Rapporteur Rebuttal ───────────────────────────────────────
    console.print("[bold yellow]→  Discussant REJECTED. Rapporteur is preparing a rebuttal...[/bold yellow]\n")

    cfg_rebuttal = tasks_cfg["rapporteur_rebuttal"]
    desc_rebuttal = cfg_rebuttal["description"].format(
        query=state.query,
        synthesis=synthesis,
        discussant_critique=critique,
        evidence_scorecard=state.evidence_scorecard_text,
    )
    desc_rebuttal += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for library searches."

    task_rebuttal = Task(
        description=desc_rebuttal,
        expected_output=cfg_rebuttal["expected_output"],
        agent=rapporteur,
    )

    # ── Step 4: Discussant Final Review ────────────────────────────────────
    desc_review2 = cfg_review["description"].format(
        query=state.query,
        synthesis="",
        evidence_scorecard=state.evidence_scorecard_text,
    )
    desc_review2 += (
        f"\n\nThis is a REVISED synthesis — the Rapporteur has already addressed your "
        f"initial critique. Evaluate the revision on its own merits."
        f"\n\nIMPORTANT: Use session_id='{state.session_id}' for library searches."
    )

    task_review2 = Task(
        description=desc_review2,
        expected_output=cfg_review["expected_output"],
        agent=discussant,
        context=[task_rebuttal],
    )

    crew_2 = Crew(
        agents=[rapporteur, discussant],
        tasks=[task_rebuttal, task_review2],
        process=Process.sequential,
        verbose=verbose,
    )

    console.print("[dim]  Rapporteur is revising the synthesis in response to critique...[/dim]")
    console.print("[dim]  Discussant is re-evaluating the revised synthesis...[/dim]\n")

    result_2 = crew_2.kickoff()
    tasks_out_2 = getattr(result_2, "tasks_output", [])

    revised_synthesis = _extract_text(tasks_out_2[0]) if len(tasks_out_2) > 0 else ""
    final_critique = _extract_text(tasks_out_2[1]) if len(tasks_out_2) > 1 else _extract_text(result_2)

    state.synthesis = revised_synthesis or synthesis

    state.add_transcript_entry(
        agent_name="Rapporteur",
        discipline="Rapporteur (rebuttal)",
        speech=revised_synthesis,
        phase="audit",
    )
    state.add_transcript_entry(
        agent_name="Discussant",
        discipline="Discussant (final)",
        speech=final_critique,
        phase="audit",
    )

    approved, mandate = _parse_discussant_output(final_critique)

    if approved:
        console.print("[bold green]✓  Discussant APPROVED the revised consensus.[/bold green]")
        state.conflict_mandate = ""
        if state.expectation_criteria:
            exp_met, exp_mandate = _evaluate_expectation(state, tasks_cfg, verbose)
            state.expectation_met = exp_met
            if exp_met:
                console.print("[bold green]✓  Expectation Evaluator: EXPECTATION MET.[/bold green] The symposium is complete.")
                state.status = "dossier"
            else:
                state.expectation_mandate = exp_mandate
                _fallback_for_expectation(state, console, exp_mandate)
                return state
        else:
            state.status = "dossier"
        return state

    # ── Rebuttal rejected — fall back to debate ───────────────────────────
    state.audit_round += 1
    if state.audit_round >= state.max_audit_rounds:
        console.print(
            f"[yellow]Maximum audit rounds ({state.max_audit_rounds}) reached.[/yellow] "
            f"[bold]Symposium halted.[/bold]"
        )
        state.status = "dossier"
        state.conflict_mandate = ""
        state.expectation_mandate = None
        return state

    console.print(f"[bold red]✗  Discussant REJECTED the rebuttal (Round {state.audit_round}).[/bold red]")
    console.print(f"[yellow]Mandate for next debate round:[/yellow] {mandate}\n")
    state.status = "debating"
    state.conflict_mandate = mandate
    state.expectation_mandate = None

    return state
