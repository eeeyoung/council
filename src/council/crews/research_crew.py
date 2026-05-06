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
from council.agents.expert import build_expert_agent, build_expert_agents
from council.config import build_llm
from council.state import CouncilState, SourcePoolEntry
from council.tools.library_tool import (
    create_library_tools, create_source_pool_tools,
    get_source_pool, clear_source_pool,
)
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


# ------------------------------------------------------------------ #
# Shared setup for research sub-phases
# ------------------------------------------------------------------ #

def _setup_research(state: CouncilState, verbose: bool = False):
    """Create shared tools and config for research sub-phases."""
    tools = {
        "search": create_search_tool(),
        "library_write": create_library_tools()[0],
        "library_read": create_library_tools()[1],
        "pdf": create_pdf_tool(),
        "pool_write": create_source_pool_tools()[0],
        "pool_read": create_source_pool_tools()[1],
    }
    return tools, build_llm(temperature=0.8), _load_tasks_config()


def run_collection(state: CouncilState, console: Console | None = None,
                   verbose: bool = False) -> CouncilState:
    """B1: Experts search and deposit candidate sources into the Source Pool."""
    if console is None:
        console = Console()
    tools, llm, tasks_cfg = _setup_research(state, verbose)

    collect_agents, collect_tasks = [], []
    for expert_def in state.experts:
        agent = build_expert_agent(
            expert=expert_def, search_tool=tools["search"],
            library_write=tools["library_write"], library_read=tools["library_read"],
            pdf_tool=tools["pdf"], llm=llm, verbose=verbose,
        )
        agent.tools.append(tools["pool_write"])
        collect_agents.append(agent)
        cfg = tasks_cfg["expert_collect"]
        desc = cfg["description"].format(
            name=expert_def.name, discipline=expert_def.discipline, query=state.query,
        )
        desc += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for all tool calls."
        collect_tasks.append(Task(description=desc, expected_output=cfg["expected_output"],
                                  agent=agent, async_execution=True))

    # CrewAI requires at most one async task, and it must be the last one.
    # We add a dummy sync task so the multiple async collection tasks are accepted.
    dummy_agent = Agent(role="Collector", goal="Wait for collection.",
                        backstory="You wait for sources to be collected.", llm=llm,
                        verbose=False, allow_delegation=False)
    dummy_task = Task(description="Return 'done'. Do nothing else.",
                      expected_output="done", agent=dummy_agent, async_execution=False)
    Crew(agents=collect_agents + [dummy_agent], tasks=collect_tasks + [dummy_task],
         process=Process.sequential, verbose=verbose).kickoff()
    state.source_pool = get_source_pool(state.session_id)
    console.print(f"[dim]  Source pool: {len(state.source_pool)} entries collected[/dim]\n")
    return state


def run_gate_check(state: CouncilState, console: Console | None = None,
                   verbose: bool = False) -> CouncilState:
    """B2: Fact-Checker verifies each source, moves verified ones to the library."""
    if console is None:
        console = Console()
    tools, llm, tasks_cfg = _setup_research(state, verbose)
    from council.agents.fact_checker import build_fact_checker

    pool_text = _render_source_pool(state.source_pool)
    fc_agent = build_fact_checker(library_read=tools["library_read"], search_tool=tools["search"])
    cfg = tasks_cfg["gate_check"]
    desc = cfg["description"].format(query=state.query, source_pool_text=pool_text)
    desc += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for library writes."

    gate_task = Task(description=desc, expected_output=cfg["expected_output"], agent=fc_agent)
    gate_result = Crew(agents=[fc_agent], tasks=[gate_task], process=Process.sequential,
                       verbose=verbose).kickoff()
    _apply_gate_results(state, gate_result)
    verified = sum(1 for e in state.source_pool if e.status == "verified")
    rejected = sum(1 for e in state.source_pool if e.status == "rejected")
    console.print(f"[bold green]✓ Gate check complete.[/bold green] {verified} verified, {rejected} rejected.\n")
    return state


def run_analysis(state: CouncilState, console: Console | None = None,
                 verbose: bool = False) -> CouncilState:
    """B3: Experts analyze verified sources, form opinions, write summaries."""
    if console is None:
        console = Console()
    tools, llm, tasks_cfg = _setup_research(state, verbose)

    analyze_agents, analyze_tasks = [], []
    for expert_def in state.experts:
        agent = build_expert_agent(
            expert=expert_def, search_tool=tools["search"],
            library_write=tools["library_write"], library_read=tools["library_read"],
            pdf_tool=tools["pdf"], llm=llm, verbose=verbose,
        )
        analyze_agents.append(agent)
        cfg = tasks_cfg["expert_analyze"]
        desc = cfg["description"].format(
            name=expert_def.name, discipline=expert_def.discipline, query=state.query,
        )
        if state.expectation_criteria:
            desc += f"\n\n=== SYMPOSIUM EXPECTATION ===\n{state.expectation_criteria}"
        desc += f"\n\nIMPORTANT: Use session_id='{state.session_id}' for all tool calls."
        analyze_tasks.append(Task(description=desc, expected_output=cfg["expected_output"],
                                  agent=agent, async_execution=True))

    aggregator_agent, agg_task = _build_aggregation_task(
        agents=analyze_agents, research_tasks=analyze_tasks, state=state,
        tasks_cfg=tasks_cfg, llm=llm,
    )
    all_agents = analyze_agents + [aggregator_agent]
    all_tasks = analyze_tasks + [agg_task]
    result = Crew(agents=all_agents, tasks=all_tasks, process=Process.sequential,
                  verbose=verbose).kickoff()

    tasks_output = getattr(result, "tasks_output", [])
    for i, (expert_def, _task) in enumerate(zip(state.experts, analyze_tasks)):
        if i < len(tasks_output):
            out = tasks_output[i]
            text = getattr(out, "exported_output", None) or getattr(out, "raw", None) or str(out)
            if text and not text.strip().startswith("#"):
                str_out = str(out)
                if str_out.strip().startswith("#"):
                    text = str_out
            state.research_summaries[expert_def.name] = text or "(No output captured)"
        else:
            state.research_summaries[expert_def.name] = "(No output captured)"

    if tasks_output:
        agg_out = tasks_output[-1]
        agg_text = agg_out.raw if hasattr(agg_out, "raw") else str(agg_out)
        state.research_summaries["__aggregation__"] = agg_text

    state.status = "debating"
    clear_source_pool(state.session_id)
    console.print(f"\n[bold green]✓  Research complete.[/bold green] {len(state.experts)} experts completed.\n")
    for expert in state.experts:
        summary = state.research_summaries.get(expert.name, "")
        preview = summary[:100].replace("\n", " ") + "…" if summary else "(no output)"
        console.print(f"  [cyan]•[/cyan] [bold]{expert.name}[/bold]: {preview}")
    return state


def run_research(
    state: CouncilState,
    console: Console | None = None,
    verbose: bool = False,
) -> CouncilState:
    """Run the full Phase B pipeline: Collect → Verify → Analyze."""
    if console is None:
        console = Console()
    if not state.experts:
        raise ValueError("No experts defined. Run Phase A (panel curation) first.")
    console.print(f"[dim]  Experts: {len(state.experts)}[/dim]\n")

    console.print("[bold cyan]⟳  Phase B1 — Experts are collecting sources…[/bold cyan]\n")
    state = run_collection(state, console, verbose)
    console.print("[bold yellow]⟳  Phase B2 — Fact-Checker is verifying sources…[/bold yellow]\n")
    state = run_gate_check(state, console, verbose)
    console.print("[bold cyan]⟳  Phase B3 — Experts are analyzing verified sources…[/bold cyan]\n")
    state = run_analysis(state, console, verbose)
    return state


def _render_source_pool(pool: list) -> str:
    """Render source pool entries for the gate check prompt."""
    if not pool:
        return "(empty)"
    lines = []
    for i, e in enumerate(pool, 1):
        lines.append(f"[{i}] From: {e.agent_name}")
        lines.append(f"    URL: {e.url}")
        lines.append(f"    Title: {e.title}")
        lines.append(f"    Snippet: {e.snippet[:200]}")
        lines.append("")
    return "\n".join(lines)


def _apply_gate_results(state, gate_result) -> None:
    """Parse gate check output and update source pool entry statuses."""
    import json, re
    raw = gate_result.raw if hasattr(gate_result, "raw") else str(gate_result)
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        return
    try:
        results = json.loads(cleaned[start:end + 1])
    except Exception:
        return
    for r in results:
        url = r.get("url", "")
        status = r.get("status", "")
        for entry in state.source_pool:
            if entry.url == url:
                entry.status = status
                entry.rejection_reason = r.get("reason", "")
