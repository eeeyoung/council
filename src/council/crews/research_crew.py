"""
council/crews/research_crew.py

Phase B: The Parallel Research Lab.

Each expert agent runs an independent research task with async_execution=True,
meaning all experts search the web simultaneously. Their findings are written
to the shared ChromaDB library as they go.

A final aggregation task (synchronous) waits for all research tasks to complete
and compiles a structured summary of what was found.

Architecture:
    [Expert A Task (async)] ─┐
    [Expert B Task (async)] ─┤─→ [Aggregation Task (sync)] → state
    [Expert C Task (async)] ─┘
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from crewai import Crew, Process, Task
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

import council.config  # noqa: F401
from council.agents.expert import build_expert_agents
from council.config import build_llm
from council.state import CouncilState
from council.tools.library_tool import create_library_tools
from council.tools.pdf_tool import create_pdf_tool
from council.tools.search_tool import create_search_tool

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_tasks_config() -> dict:
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------ #
# Research task builder
# ------------------------------------------------------------------ #


def _build_research_task(
    expert_definition,
    agent,
    state: CouncilState,
    tasks_cfg: dict,
) -> Task:
    """Build one async research task for a single expert."""
    cfg = tasks_cfg["expert_research"]
    description = cfg["description"].format(
        name=expert_definition.name,
        discipline=expert_definition.discipline,
        query=state.query,
    )

    # Inject expectation criteria to guide research toward the desired outcome
    if state.expectation_criteria:
        description += (
            f"\n\n=== SYMPOSIUM EXPECTATION ===\n"
            f"The user expects this symposium to produce a specific type of outcome. "
            f"Your research should gather evidence that supports this goal:\n"
            f"{state.expectation_criteria}"
        )

    # Inject the session_id so the agent knows which library collection to write to.
    description += (
        f"\n\nIMPORTANT: When calling library_write or library_read tools, "
        f"always use session_id='{state.session_id}'."
    )

    return Task(
        description=description,
        expected_output=cfg["expected_output"],
        agent=agent,
        async_execution=True,  # Run in parallel with other expert research tasks
    )


# ------------------------------------------------------------------ #
# Aggregation task
# ------------------------------------------------------------------ #


def _build_aggregation_task(
    agents: list,
    research_tasks: list[Task],
    state: CouncilState,
    tasks_cfg: dict,
    llm: object,
) -> tuple[object, Task]:
    """
    Build the Research Aggregator agent + task that waits for all async tasks.
    This is the synchronisation point that ensures all research is complete
    before Phase C begins.
    """
    from council.agents.aggregator import build_aggregator

    aggregator = build_aggregator(llm=llm)

    expert_names = ", ".join(e.name for e in state.experts)

    cfg = tasks_cfg["aggregator_compile"]
    description = cfg["description"].format(
        query=state.query,
        expert_names=expert_names,
    )

    task = Task(
        description=description,
        expected_output=cfg["expected_output"],
        agent=aggregator,
        context=research_tasks,  # This task waits for ALL async tasks to complete
        async_execution=False,
    )

    return aggregator, task


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #


def run_research(
    state: CouncilState,
    console: Console | None = None,
    verbose: bool = False,
) -> CouncilState:
    """
    Run Phase B: parallel research for all experts in state.experts.

    Updates state.research_summaries with each expert's findings,
    populates the shared ChromaDB library, and sets state.status = 'debating'.

    Returns the updated CouncilState.
    """
    if console is None:
        console = Console()

    if not state.experts:
        raise ValueError("No experts defined. Run Phase A (panel curation) first.")

    # Build shared tools — same instances passed to ALL expert agents
    search_tool = create_search_tool()
    library_write, library_read = create_library_tools()
    pdf_tool = create_pdf_tool()

    tavily_key = council.config.get_tavily_key()
    search_backend = "Tavily" if tavily_key else "DuckDuckGo (no Tavily key set)"
    console.print(f"[dim]  Search backend: {search_backend}[/dim]")
    console.print(f"[dim]  Library session: {state.session_id}[/dim]")
    console.print(f"[dim]  Experts: {len(state.experts)}[/dim]\n")

    llm = build_llm(temperature=0.8)

    # Build expert agents
    expert_agents = build_expert_agents(
        experts=state.experts,
        search_tool=search_tool,
        library_write=library_write,
        library_read=library_read,
        pdf_tool=pdf_tool,
        llm=llm,
        verbose=verbose,
    )

    # Build async research tasks (one per expert)
    tasks_cfg = _load_tasks_config()
    research_tasks: list[Task] = []
    for expert_def, agent in zip(state.experts, expert_agents):
        task = _build_research_task(expert_def, agent, state, tasks_cfg)
        research_tasks.append(task)

    # Build synchronous aggregation task (waits for all async tasks)
    aggregator_agent, agg_task = _build_aggregation_task(
        agents=expert_agents,
        research_tasks=research_tasks,
        state=state,
        tasks_cfg=tasks_cfg,
        llm=llm,
    )

    # Assemble crew
    all_agents = expert_agents + [aggregator_agent]
    all_tasks = research_tasks + [agg_task]

    crew = Crew(
        agents=all_agents,
        tasks=all_tasks,
        process=Process.sequential,
        verbose=verbose,
    )

    # Run with a spinner
    console.print("[bold cyan]⟳  Research phase running — experts searching in parallel…[/bold cyan]")
    console.print("[dim]  (This may take 1-3 minutes depending on the LLM and search results)[/dim]\n")

    result = crew.kickoff()

    # Extract individual task outputs and map to expert names
    # crewAI stores task outputs in result.tasks_output
    tasks_output = getattr(result, "tasks_output", [])

    for i, (expert_def, task) in enumerate(zip(state.experts, research_tasks)):
        if i < len(tasks_output):
            out = tasks_output[i]
            # Prefer exported_output (final answer) over raw (may contain tool call traces)
            text = getattr(out, "exported_output", None) or getattr(out, "raw", None) or str(out)
            # If the output looks like raw tool calls rather than a report, try harder
            if text and not text.strip().startswith("#"):
                # Fall back to str() which sometimes has cleaner output
                str_out = str(out)
                if str_out.strip().startswith("#"):
                    text = str_out
            state.research_summaries[expert_def.name] = text or "(No output captured)"
        else:
            state.research_summaries[expert_def.name] = "(No output captured)"

    # The aggregation task output is the last one
    if tasks_output:
        agg_output = tasks_output[-1]
        agg_text = agg_output.raw if hasattr(agg_output, "raw") else str(agg_output)
        state.research_summaries["__aggregation__"] = agg_text

    state.status = "debating"

    # Display summary
    console.print(
        f"\n[bold green]✓  Research complete.[/bold green] "
        f"{len(state.experts)} experts completed. "
        f"Library populated for session [cyan]{state.session_id}[/cyan].\n"
    )

    for expert in state.experts:
        summary = state.research_summaries.get(expert.name, "")
        preview = summary[:100].replace("\n", " ") + "…" if summary else "(no output)"
        console.print(f"  [cyan]•[/cyan] [bold]{expert.name}[/bold]: {preview}")

    return state
