#!/usr/bin/env python3
"""
council/workspace/smoke_test.py

End-to-end smoke test for the workspace system without GUI or server.
Exercises the full flow: create → panel → research → verify → respond → synthesize.

Requires valid LLM API keys (AI_PROVIDER env var).
Usage: uv run python -m council.workspace.smoke_test
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel as RichPanel
from rich.rule import Rule

from council.workspace.agents import (
    expert_respond,
    expert_research,
    fact_check_source,
    moderator_propose_panel,
    rapporteur_synthesize,
)
from council.workspace.db import save
from council.workspace.state import Message, Panel, Symposium, WorkspaceState

console = Console()


def step(label: str) -> None:
    console.print(Rule(f"[bold cyan]{label}[/bold cyan]"))


def show(msg: str) -> None:
    console.print(msg)


def run(query: str, max_experts: int = 3) -> WorkspaceState:
    """Run a full workspace session from query to synthesis."""

    # ── Create workspace ──────────────────────────────────────────────────
    step("Creating workspace")
    ws = WorkspaceState(query=query)
    show(f"Workspace [bold]{ws.id}[/bold] created with query: [italic]'{query}'[/italic]")

    # ── Propose panel ─────────────────────────────────────────────────────
    step("Moderator proposes expert panel")
    experts = moderator_propose_panel(query=query, max_experts=max_experts)

    if not experts:
        show("[red]Moderator failed to propose experts.[/red]")
        return ws

    panel = Panel(name=query[:60], query=query, experts=experts)
    ws.panels.append(panel)

    for e in experts:
        show(f"  • [bold]{e.name}[/bold] — {e.discipline} ({e.bias})")

    # ── Research: each expert collects sources ────────────────────────────
    step("Experts collect sources")
    for expert in panel.experts:
        show(f"\n[yellow]{expert.name}[/yellow] is researching...")
        sources = expert_research(
            expert=expert,
            query=query,
            research_goal=f"Find sources on {query} from a {expert.discipline} perspective.",
        )
        expert.knowledge_pool.sources.extend(sources)
        show(f"  Collected {len(sources)} sources")

        # ── Fact-check each source ────────────────────────────────────────
        for src in sources:
            verified = fact_check_source(src)
            show(f"    [{verified.verification_status or 'pending'}] {src.title[:60]}")

    # ── Expert responds to a prompt ───────────────────────────────────────
    step("Expert responds (single agent)")
    first_expert = panel.experts[0]
    show(f"[yellow]Asking {first_expert.name}...[/yellow]")

    response = expert_respond(
        expert=first_expert,
        query=query,
        message=f"Based on your research, what is your position on: {query}",
    )
    show(RichPanel(response[:800], title=f"{first_expert.name}'s response"))

    # ── Simulate a mini-symposium with all experts ────────────────────────
    step("Mini-symposium (each expert responds in turn)")
    symposium = Symposium(
        title=f"Symposium: {query[:50]}",
        format="structured",
        participant_ids=[e.id for e in panel.experts],
    )
    ws.symposia.append(symposium)

    transcript_lines: list[str] = []
    scorecard_entries: list[dict] = []

    for i, expert in enumerate(panel.experts):
        turn = i + 1
        show(f"\n[yellow]Turn {turn}: {expert.name}[/yellow]")

        # Build context from previous turns
        context = "\n".join(transcript_lines) if transcript_lines else "(You are the first speaker.)"
        prompt = f"""
=== DEBATE TRANSCRIPT SO FAR ===
{context}
=== END TRANSCRIPT ===

Present your evidence-based position on: {query}

As turn {turn}, you must respond to previous speakers if any, and present your
unique disciplinary perspective grounded in your knowledge pool sources.
"""

        speech = expert_respond(expert=expert, query=query, message=prompt)
        transcript_lines.append(f"[Turn {turn}] **{expert.name}** ({expert.discipline}):\n{speech}")

        ws.add_message(
            role="agent",
            agent_id=expert.id,
            agent_name=expert.name,
            symposium_id=symposium.id,
            content=speech,
            turn=turn,
        )

        show(f"  [dim]{speech[:200]}...[/dim]")

    # ── Rapporteur synthesizes ────────────────────────────────────────────
    step("Rapporteur synthesizes the symposium")
    transcript = "\n\n".join(transcript_lines)

    scorecard = str([
        {
            "claim": f"Looking at: {s.title}",
            "agent_name": s.added_by,
            "claim_type": "empirical",
            "source_url": s.url,
            "verification_status": s.verification_status,
            "source_quote": s.snippet[:100],
        }
        for expert in panel.experts
        for s in expert.knowledge_pool.sources
        if s.verification_status == "verified"
    ])

    synthesis = rapporteur_synthesize(
        transcript=transcript,
        scorecard=scorecard,
        query=query,
    )
    symposium.synthesis = synthesis
    show(RichPanel(synthesis[:1000], title="Synthesis"))

    # ── Persist ───────────────────────────────────────────────────────────
    step("Save workspace")
    save(ws)
    show(f"Workspace [bold]{ws.id}[/bold] saved to workspace.db")

    return ws


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is the most effective approach to carbon pricing?"
    console.print(f"\n[bold]COUNCIL Workspace — Smoke Test[/bold]\n")
    run(query)
    console.print(f"\n[bold green]Done.[/bold green]\n")
