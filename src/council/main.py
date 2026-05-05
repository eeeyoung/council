"""
council/main.py

Entry point for Project COUNCIL.
Provides a CLI interface for running a symposium session.

Usage:
    uv run python -m council.main "Your research question here"
    uv run python -m council.main "Your question" --experts 5
    uv run python -m council.main "Your question" --no-confirm  (skip panel approval)
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# ── Force UTF-8 encoding on Windows ──────────────────────────────────────
# On Chinese/Japanese/Korean Windows, the default console encoding is often
# GBK/Shift-JIS/EUC-KR. LLM outputs contain Unicode characters (em dashes,
# smart quotes, academic symbols) that can't be encoded in those code pages,
# causing "'gbk' codec can't decode byte 0x94" errors.
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "buffer"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

# Ensure src/ is on the path when running as __main__
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Import config first — this triggers load_dotenv with an explicit path
import council.config  # noqa: F401

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table

from council.agents.moderator import run_curation
from council.state import CouncilState, ExpertDefinition

console = Console()

# ------------------------------------------------------------------ #
# Display helpers
# ------------------------------------------------------------------ #

COUNCIL_BANNER = """
[bold cyan]
   ██████╗ ██████╗ ██╗   ██╗███╗   ██╗ ██████╗██╗██╗
  ██╔════╝██╔═══██╗██║   ██║████╗  ██║██╔════╝██║██║
  ██║     ██║   ██║██║   ██║██╔██╗ ██║██║     ██║██║
  ██║     ██║   ██║██║   ██║██║╚██╗██║██║     ██║██║
  ╚██████╗╚██████╔╝╚██████╔╝██║ ╚████║╚██████╗██║███████╗
   ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚═╝╚══════╝
[/bold cyan]
[dim]Collaborative Open-source Universal Consortium for Industrial & Logical Research[/dim]
"""


def print_banner() -> None:
    console.print(COUNCIL_BANNER, justify="center")
    console.print(Rule(style="cyan dim"))
    console.print()


def print_expert_panel(experts: list[ExpertDefinition]) -> None:
    """Render the proposed expert panel as a rich table."""
    table = Table(
        title="[bold]Proposed Expert Panel[/bold]",
        show_header=True,
        header_style="bold magenta",
        border_style="cyan",
        expand=True,
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Name", style="bold white", min_width=20)
    table.add_column("Discipline", style="cyan", min_width=22)
    table.add_column("Intellectual Bias", style="yellow", min_width=28)
    table.add_column("Persona", style="dim white", min_width=35)

    for i, expert in enumerate(experts, 1):
        persona = expert.persona_prompt
        if len(persona) > 120:
            persona = persona[:120] + "…"
        table.add_row(str(i), expert.name, expert.discipline, expert.bias, persona)

    console.print(table)
    console.print()


def _run_expectation_curator(state: CouncilState) -> str:
    """Run the Expectation Curator to refine success criteria."""
    from council.agents.expectation_curator import build_expectation_curator
    from crewai import Crew, Process, Task
    from pathlib import Path
    import yaml

    _CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
    with open(_CONFIG_DIR / "tasks.yaml") as f:
        tasks_cfg = yaml.safe_load(f)

    agent = build_expectation_curator()
    cfg = tasks_cfg["expectation_curator_refine"]
    desc = cfg["description"].format(
        query=state.query,
        expectation_type=state.expectation_type.replace("_", " ").title(),
        expectation_detail=state.expectation_detail or "(none)",
    )

    task = Task(
        description=desc,
        expected_output=cfg["expected_output"],
        agent=agent,
    )

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    result = crew.kickoff()
    return result.raw if hasattr(result, "raw") else str(result)


def panel_approval_loop(
    state: CouncilState, skip_confirm: bool = False
) -> CouncilState:
    """
    Interactive panel approval loop.
    User can approve, request a regeneration, or edit the panel size.
    """
    # Cache the query so it survives across retry iterations
    query = state.query

    while True:
        from rich.panel import Panel

        console.print(
            Panel(
                f"[bold white]Research Question:[/bold white]\n[italic cyan]{query}[/italic cyan]",
                border_style="cyan",
                title="[bold]Phase A — Panel Curation[/bold]",
            )
        )
        console.print()
        console.print("[bold yellow]⟳  Consulting the Moderator…[/bold yellow]")
        console.print()

        try:
            experts = run_curation(state)
        except Exception as exc:
            console.print(f"\n[bold red]✗ Moderator failed:[/bold red] {exc}\n")
            if not Confirm.ask("Retry?", default=True):
                raise SystemExit(1)
            continue

        state.experts = experts
        print_expert_panel(experts)

        if skip_confirm:
            console.print("[dim]Panel auto-approved (--no-confirm)[/dim]")
            break

        console.print("[bold]Options:[/bold]")
        console.print("  [cyan]A[/cyan] — Approve this panel and proceed")
        console.print("  [cyan]R[/cyan] — Regenerate with different experts")
        console.print("  [cyan]E[/cyan] — Edit panel size then regenerate")
        console.print("  [cyan]Q[/cyan] — Quit")
        console.print()

        choice = Prompt.ask(
            "[bold white]Your choice[/bold white]",
            choices=["A", "a", "R", "r", "E", "e", "Q", "q"],
            default="A",
        ).upper()

        if choice == "A":
            console.print()
            from rich.panel import Panel as P
            console.print(
                P(
                    f"[bold green]✓ Panel approved![/bold green]  {len(experts)} experts ready.",
                    border_style="green",
                )
            )
            break
        elif choice == "R":
            console.print("\n[yellow]Regenerating panel…[/yellow]\n")
            continue
        elif choice == "E":
            new_size = IntPrompt.ask("How many experts?", default=state.max_experts)
            state.max_experts = max(2, min(8, new_size))
            continue
        elif choice == "Q":
            console.print("[dim]Session cancelled.[/dim]")
            raise SystemExit(0)

    # ── Run Expectation Curator ────────────────────────────────────────
    if state.expectation_type:
        console.print("\n[bold yellow]⟳  Expectation Curator is refining success criteria…[/bold yellow]\n")
        try:
            criteria = _run_expectation_curator(state)
            state.expectation_criteria = criteria
            console.print(
                Panel(
                    criteria,
                    border_style="magenta",
                    title="[bold]Success Criteria[/bold]",
                )
            )
        except Exception as exc:
            console.print(f"[yellow]⚠  Expectation Curator failed: {exc}[/yellow]")
            console.print("[dim]Continuing without refined criteria.[/dim]")

    state.status = "researching"
    return state


# ------------------------------------------------------------------ #
# CLI entry point
# ------------------------------------------------------------------ #


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="council",
        description="COUNCIL — Multi-Agent Scientific Brainstorming Framework",
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="The research question to investigate. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--experts",
        type=int,
        default=5,
        metavar="N",
        help="Maximum number of expert personas to generate (2–8, default: 5)",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip interactive panel approval (useful for testing)",
    )
    parser.add_argument(
        "--session-id",
        metavar="ID",
        help="(Stage 4) Resume an existing session by ID",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging to see the agents' live thought process and tool usage",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print_banner()

    # --- Get the query ---
    # --- Load or Initialize state ---
    from council.db import init_db, load_state, save_state
    init_db()

    if args.session_id:
        try:
            state = load_state(args.session_id)
            console.print(f"[bold green]✓ Resumed session:[/bold green] [cyan]{state.session_id}[/cyan] at status: [bold]{state.status}[/bold]")
        except Exception as e:
            console.print(f"[bold red]Failed to resume session {args.session_id}:[/bold red] {e}")
            raise SystemExit(1)
    else:
        if args.query:
            query = args.query.strip()
        else:
            query = Prompt.ask("[bold cyan]Enter your research question[/bold cyan]").strip()

        if not query:
            console.print("[bold red]No query provided. Exiting.[/bold red]")
            raise SystemExit(1)

        # ── Expectation gathering ──────────────────────────────────────────
    EXPECTATION_TYPES = {
        "1": ("definitive_answer", "Definitive Answer — reach a clear conclusion"),
        "2": ("feasible_plan", "Feasible Plan — detailed implementation roadmap"),
        "3": ("balanced_overview", "Balanced Overview — survey competing viewpoints"),
        "4": ("research_roadmap", "Research Roadmap — prioritize future directions"),
        "5": ("decision_analysis", "Decision Analysis — weigh alternatives, recommend one"),
        "6": ("hypothesis_evaluation", "Hypothesis Evaluation — test a specific hypothesis"),
        "7": ("custom", "Custom — describe your own desired outcome"),
    }

    console.print("\n[bold]What kind of outcome do you expect from this symposium?[/bold]\n")
    for key, (_, label) in EXPECTATION_TYPES.items():
        console.print(f"  [cyan]{key}[/cyan]. {label}")

    choice = Prompt.ask(
        "\n[bold cyan]Select outcome type[/bold cyan]",
        choices=list(EXPECTATION_TYPES.keys()),
        default="1",
    )
    exp_type, exp_label = EXPECTATION_TYPES[choice]

    exp_detail = ""
    if exp_type == "custom" or choice in ("1", "2", "3", "4", "5", "6"):
        detail = Prompt.ask(
            "[dim]Optional: add specific detail or context[/dim]",
            default="",
        )
        if detail.strip():
            exp_detail = detail.strip()

    state = CouncilState(
        query=query,
        max_experts=max(2, min(8, args.experts)),
        expectation_type=exp_type,
        expectation_detail=exp_detail,
    )

    console.print(
        f"\n[bold]Session ID:[/bold] [cyan]{state.session_id}[/cyan]  "
        f"[dim](save this to resume later: --session-id {state.session_id})[/dim]\n"
    )
    console.print(f"[dim]Expectation:[/dim] {exp_label}")
    save_state(state)

    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ #
    # Phase A: Panel Curation
    # ------------------------------------------------------------------ #
    if state.status == "curating":
        state = panel_approval_loop(state, skip_confirm=args.no_confirm)
        save_state(state)

        # Save expert panel as JSON for GUI Phase A editor
        import json
        panel_file = out_dir / f"{state.session_id}_panel.json"
        with open(panel_file, "w", encoding="utf-8") as f:
            json.dump([e.model_dump() for e in state.experts], f, indent=2)
        console.print(f"[bold green]✓ Expert panel saved to:[/bold green] [cyan]{panel_file}[/cyan]")
        _write_manifest(state, out_dir)

        console.print()
        console.print(Rule("[bold cyan]Phase A Complete[/bold cyan]", style="cyan"))
        console.print()


    # ------------------------------------------------------------------ #
    # Phase B: Parallel Research
    # ------------------------------------------------------------------ #
    try:
        from council.crews.research_crew import run_research
        _phase_b_available = True
    except ImportError:
        _phase_b_available = False

    if _phase_b_available and state.status == "researching":
        console.print("[bold yellow]⟳  Launching parallel research phase…[/bold yellow]")
        console.print(
            "[dim]Each expert will independently search the web and populate the shared library.[/dim]\n"
        )
        state = run_research(state, console=console, verbose=args.verbose)
        save_state(state)
        
        # Save the full research summaries to discrete files for the GUI
        for expert_name, text in state.research_summaries.items():
            safe_name = expert_name.replace(" ", "_").replace(".", "").lower()
            file_name = out_dir / f"{state.session_id}_research_{safe_name}.md"
            with open(file_name, "w", encoding="utf-8") as f:
                f.write(text)
        
        console.print(f"[bold green]✓ Research summaries saved to:[/bold green] [cyan]{out_dir}[/cyan]")
        _write_manifest(state, out_dir)
        console.print()
        console.print(Rule("[bold cyan]Phase B Complete[/bold cyan]", style="cyan"))
        console.print()
    elif state.status == "researching":
        console.print(
            "[dim]Phase B (research_crew) not yet available — run Stage 2 first.[/dim]\n"
        )
    # ------------------------------------------------------------------ #
    # Phase C & D: The Audit Loop (Sequential Debate -> Audit Review)
    # ------------------------------------------------------------------ #
    try:
        from council.crews.debate_crew import run_debate
        from council.crews.audit_crew import run_audit_loop
        _phases_cd_available = True
    except ImportError:
        _phases_cd_available = False

    if _phases_cd_available:
        while state.status in ("debating", "auditing"):
            
            # PHASE C: Debate
            if state.status == "debating":
                state = run_debate(state, console=console, verbose=args.verbose)
                save_state(state)
                
                # Save transcript and scorecard
                transcript_file = out_dir / f"{state.session_id}_transcript_r{state.audit_round}.md"
                with open(transcript_file, "w", encoding="utf-8") as f:
                    f.write(f"# Phase C Debate Transcript (Session {state.session_id} - Round {state.audit_round})\n\n")
                    f.write(state.transcript_text)
                    
                scorecard_file = out_dir / f"{state.session_id}_scorecard_r{state.audit_round}.md"
                with open(scorecard_file, "w", encoding="utf-8") as f:
                    f.write(f"# Phase C Evidence Scorecard (Session {state.session_id} - Round {state.audit_round})\n\n")
                    f.write(state.evidence_scorecard_text)

                console.print(f"[bold green]✓ Saved transcript:[/bold green] [cyan]{transcript_file}[/cyan]")
                console.print(f"[bold green]✓ Saved scorecard:[/bold green] [cyan]{scorecard_file}[/cyan]")
                _write_manifest(state, out_dir)
                console.print(Rule("[bold cyan]Phase C Complete[/bold cyan]", style="cyan"))
                console.print()

            # PHASE D: Audit
            if state.status == "auditing":
                state = run_audit_loop(state, console=console, verbose=args.verbose)
                save_state(state)
                
                if state.synthesis:
                    consensus_file = out_dir / f"{state.session_id}_consensus_r{state.audit_round}.md"
                    with open(consensus_file, "w", encoding="utf-8") as f:
                        f.write(f"# Phase D Consensus Draft (Session {state.session_id} - Round {state.audit_round})\n\n")
                        f.write(state.synthesis)
                    _write_manifest(state, out_dir)

                console.print(Rule("[bold magenta]Phase D Complete[/bold magenta]", style="magenta"))
                console.print()
    elif state.status in ("debating", "auditing"):
        console.print("[dim]Phase C/D not yet available — run Stage 3 & 4 first.[/dim]\n")

    # ------------------------------------------------------------------ #
    # Phase E: Final Dossier Compilation
    # ------------------------------------------------------------------ #
    try:
        from council.crews.dossier_crew import run_dossier
        _phase_e_available = True
    except ImportError:
        _phase_e_available = False

    if _phase_e_available and state.status == "dossier":
        state = run_dossier(state, console=console, verbose=args.verbose)
        save_state(state)

        dossier_file = out_dir / f"{state.session_id}_dossier.md"
        with open(dossier_file, "w", encoding="utf-8") as f:
            f.write(state.dossier_path or "")

        console.print(f"[bold green]✓ Final dossier saved to:[/bold green] [cyan]{dossier_file}[/cyan]")
        _write_manifest(state, out_dir)
        console.print(Rule("[bold blue]Phase E Complete[/bold blue]", style="blue"))
        console.print()
    elif state.status == "dossier":
        console.print("[dim]Phase E (dossier_crew) not yet available.[/dim]\n")

    # ------------------------------------------------------------------ #
    # Final Rich TUI Session Summary (Director's Console recap)
    # ------------------------------------------------------------------ #
    _print_session_summary(state, out_dir)


from council.manifest import write_manifest as _write_manifest


def _print_session_summary(state: "CouncilState", out_dir: Path) -> None:
    """Print a rich table summarising all completed phases."""
    from rich.panel import Panel

    STATUS_DONE = "[bold green]✓ Done[/bold green]"
    STATUS_SKIP = "[dim]— Skipped[/dim]"

    def _done(cond: bool) -> str:
        return STATUS_DONE if cond else STATUS_SKIP

    table = Table(
        title="[bold]COUNCIL — Director's Session Summary[/bold]",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan dim",
        expand=True,
        show_lines=True,
    )
    table.add_column("Phase", style="bold", width=8)
    table.add_column("Name", min_width=20)
    table.add_column("Status", min_width=14)
    table.add_column("Detail", style="dim")

    table.add_row(
        "A",
        "Panel Curation",
        _done(bool(state.experts)),
        f"{len(state.experts)} expert(s) approved" if state.experts else "—",
    )
    table.add_row(
        "B",
        "Parallel Research",
        _done(bool(state.research_summaries)),
        f"{len(state.research_summaries)} research summary/summaries" if state.research_summaries else "—",
    )

    transcript_turns = len(state.transcript) if hasattr(state, "transcript") and state.transcript else 0
    table.add_row(
        "C",
        "The Symposium",
        _done(transcript_turns > 0),
        f"{transcript_turns} turn(s) across {state.audit_round + 1} round(s)" if transcript_turns else "—",
    )
    table.add_row(
        "D",
        "Audit Loop",
        _done(state.status in ("dossier", "done")),
        f"APPROVED after round {state.audit_round}" if state.status in ("dossier", "done") else f"Round {state.audit_round}",
    )

    dossier_path = out_dir / f"{state.session_id}_dossier.md"
    table.add_row(
        "E",
        "Final Dossier",
        _done(state.status == "done" and dossier_path.exists()),
        str(dossier_path) if dossier_path.exists() else "—",
    )

    console.print()
    console.print(Rule("[bold cyan]Session Complete[/bold cyan]", style="cyan"))
    console.print()
    console.print(table)
    console.print()

    if dossier_path.exists():
        # Print first 20 lines of dossier as a preview
        preview_lines = dossier_path.read_text(encoding="utf-8").splitlines()[:20]
        preview = "\n".join(preview_lines)
        console.print(
            Panel(
                f"[dim]{preview}[/dim]",
                title="[bold]Dossier Preview[/bold]",
                border_style="blue",
                expand=True,
            )
        )
        console.print()


if __name__ == "__main__":
    main()
