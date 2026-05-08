#!/usr/bin/env python3
"""
council/workspace/cli.py

Module-based CLI for the workspace system. Each subcommand is independently
invoable — no pipeline, no vertical dependencies.

Usage:
  uv run python -m council.workspace.cli new <query>
  uv run python -m council.workspace.cli load <id>
  uv run python -m council.workspace.cli panel <ws_id> <query>
  uv run python -m council.workspace.cli list <ws_id>
  uv run python -m council.workspace.cli add-url <ws_id> <expert_id> <url> [title] [snippet]
  uv run python -m council.workspace.cli upload <ws_id> <expert_id> <file_path>
  uv run python -m council.workspace.cli verify <ws_id> <expert_id>
  uv run python -m council.workspace.cli ask <ws_id> <expert_id> "<message>"
  uv run python -m council.workspace.cli debate <ws_id> <panel_id>
  uv run python -m council.workspace.cli synthesize <ws_id> <symposium_id>
  uv run python -m council.workspace.cli run <query>   # demo: full pipeline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel as RichPanel
from rich.rule import Rule
from rich.table import Table

from council.workspace.agents import (
    add_source_to_expert,
    expert_respond,
    expert_research,
    fact_check_source,
    form_opinion,
    moderator_propose_panel,
    rapporteur_synthesize,
    upload_file_to_expert,
)
from council.workspace.db import delete, list_all, load, save
from council.workspace.state import Panel, Symposium, WorkspaceState

console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _die(msg: str) -> None:
    console.print(f"[red]Error:[/red] {msg}")
    sys.exit(1)


def _load(ws_id: str) -> WorkspaceState:
    try:
        return load(ws_id)
    except ValueError:
        _die(f"Workspace not found: {ws_id}")


def _find_expert(ws: WorkspaceState, expert_id: str):
    expert = ws.get_expert(expert_id)
    if not expert:
        _die(f"Expert not found: {expert_id}")
    return expert


# ── Subcommands ──────────────────────────────────────────────────────────────

def cmd_new(args: argparse.Namespace) -> None:
    ws = WorkspaceState(query=args.query)
    save(ws)
    console.print(f"[green]Workspace created:[/green] [bold]{ws.id}[/bold]")
    console.print(f"  Query: [italic]{args.query}[/italic]")


def cmd_load(args: argparse.Namespace) -> None:
    ws = _load(args.id)
    console.print(f"[bold]Workspace:[/bold] {ws.id}")
    console.print(f"  Query: [italic]{ws.query or '(none)'}[/italic]")
    console.print(f"  Panels: {len(ws.panels)}")
    console.print(f"  Messages: {len(ws.messages)}")
    console.print(f"  Symposia: {len(ws.symposia)}")


def cmd_list(args: argparse.Namespace) -> None:
    if args.all:
        workspaces = list_all()
        if not workspaces:
            console.print("[dim]No workspaces found.[/dim]")
            return
        table = Table(title="Workspaces")
        table.add_column("ID", style="cyan")
        table.add_column("Updated", style="dim")
        for w in workspaces:
            table.add_row(w["id"], w["updated_at"])
        console.print(table)
        return

    ws = _load(args.ws_id)
    console.print(Rule(f"Workspace: {ws.id}"))
    for panel in ws.panels:
        console.print(f"\n[bold]Panel:[/bold] {panel.name or panel.id} (query: {panel.query or '(none)'})")
        for e in panel.experts:
            n_sources = len(e.knowledge_pool.sources)
            n_opinions = len(e.knowledge_pool.opinions)
            console.print(f"  [{e.id}] [bold]{e.name}[/bold] — {e.discipline}")
            console.print(f"       {n_sources} sources, {n_opinions} opinions")
    for sym in ws.symposia:
        console.print(f"\n[bold]Symposium:[/bold] {sym.title or sym.id} ({sym.format})")
        console.print(f"  Participants: {len(sym.participant_ids)}, Messages: {len(sym.message_ids)}")
        if sym.synthesis:
            console.print(f"  Synthesis: {len(sym.synthesis)} chars")


def cmd_panel(args: argparse.Namespace) -> None:
    ws = _load(args.ws_id)
    console.print(f"[yellow]Moderator proposing panel for:[/yellow] {args.query}")
    experts = moderator_propose_panel(query=args.query, max_experts=args.num)
    if not experts:
        _die("Moderator failed to propose experts.")

    panel = Panel(name=args.query[:60], query=args.query, experts=experts)
    ws.panels.append(panel)
    save(ws)

    console.print(f"\n[green]Panel created:[/green] [bold]{panel.id}[/bold]")
    for e in experts:
        console.print(f"  [{e.id}] [bold]{e.name}[/bold] — {e.discipline} ({e.bias})")


def cmd_add_url(args: argparse.Namespace) -> None:
    ws = _load(args.ws_id)
    expert = _find_expert(ws, args.expert_id)

    src = add_source_to_expert(
        expert=expert,
        workspace_id=ws.id,
        url=args.url,
        title=args.title or "",
        snippet=args.snippet or "",
    )
    save(ws)

    console.print(f"[green]Source added to {expert.name}:[/green] [{src.id}] {src.title or args.url}")
    if src.full_text and len(src.full_text) > len(args.snippet or ""):
        console.print(f"  Full text fetched: {len(src.full_text)} chars")
    else:
        console.print(f"  [dim]Snippet only ({len(src.snippet)} chars)[/dim]")


def cmd_upload(args: argparse.Namespace) -> None:
    ws = _load(args.ws_id)
    expert = _find_expert(ws, args.expert_id)

    file_path = Path(args.file_path)
    if not file_path.exists():
        _die(f"File not found: {args.file_path}")

    src = upload_file_to_expert(expert=expert, workspace_id=ws.id, file_path=args.file_path)
    if not src:
        _die(f"Could not parse file: {args.file_path}")

    save(ws)
    console.print(f"[green]File uploaded to {expert.name}:[/green] [{src.id}] {file_path.name}")
    console.print(f"  Full text: {len(src.full_text)} chars")


def cmd_verify(args: argparse.Namespace) -> None:
    ws = _load(args.ws_id)
    expert = _find_expert(ws, args.expert_id)

    unverified = [s for s in expert.knowledge_pool.sources if s.verification_status != "verified"]
    if not unverified:
        console.print("[green]All sources already verified.[/green]")
        return

    console.print(f"Verifying {len(unverified)} sources for [bold]{expert.name}[/bold]...\n")
    for src in unverified:
        verified = fact_check_source(src)
        status = verified.verification_status or "pending"
        icon = {"verified": "✓", "misattributed": "⚠", "unverifiable": "?"}.get(status, "?")
        console.print(f"  [{icon} {status}] {src.title[:60]}")
    save(ws)


def cmd_ask(args: argparse.Namespace) -> None:
    ws = _load(args.ws_id)
    expert = _find_expert(ws, args.expert_id)

    response = expert_respond(
        expert=expert,
        workspace_id=ws.id,
        query=ws.query or "the research context",
        message=args.message,
    )
    ws.add_message(role="agent", agent_id=expert.id, agent_name=expert.name, content=response)
    save(ws)

    console.print(RichPanel(response[:1200], title=f"{expert.name}'s response"))


def cmd_debate(args: argparse.Namespace) -> None:
    ws = _load(args.ws_id)
    panel = ws.get_panel(args.panel_id)
    if not panel:
        _die(f"Panel not found: {args.panel_id}")

    sym = Symposium(
        title=f"Debate: {panel.query[:50]}",
        format="structured",
        participant_ids=[e.id for e in panel.experts],
    )
    ws.symposia.append(sym)

    transcript_lines: list[str] = []

    for i, expert in enumerate(panel.experts):
        turn = i + 1
        console.print(f"\n[yellow]Turn {turn}: {expert.name}[/yellow]")

        context = "\n".join(transcript_lines) if transcript_lines else "(You are the first speaker.)"
        prompt = (
            f"=== DEBATE TRANSCRIPT SO FAR ===\n{context}\n=== END TRANSCRIPT ===\n\n"
            f"Present your evidence-based position on: {panel.query}\n\n"
            f"As turn {turn}, respond to previous speakers and present your unique "
            f"disciplinary perspective grounded in your knowledge pool."
        )

        speech = expert_respond(
            expert=expert,
            workspace_id=ws.id,
            query=panel.query,
            message=prompt,
        )
        transcript_lines.append(f"[Turn {turn}] **{expert.name}** ({expert.discipline}):\n{speech}")
        ws.add_message(
            role="agent",
            agent_id=expert.id,
            agent_name=expert.name,
            symposium_id=sym.id,
            content=speech,
            turn=turn,
        )

        console.print(f"  [dim]{speech[:200]}...[/dim]")

    save(ws)
    console.print(f"\n[green]Debate complete.[/green] Symposium: [bold]{sym.id}[/bold]")


def cmd_synthesize(args: argparse.Namespace) -> None:
    ws = _load(args.ws_id)
    sym = ws.get_symposium(args.symposium_id)
    if not sym:
        _die(f"Symposium not found: {args.symposium_id}")

    msgs = ws.get_messages_for_symposium(sym.id)
    if not msgs:
        _die("Symposium has no messages.")

    transcript = "\n\n".join(
        f"[Turn {m.turn}] **{m.agent_name}**:\n{m.content}" if m.turn
        else f"**{m.agent_name}**:\n{m.content}"
        for m in msgs
        if m.role == "agent"
    )
    scorecard = str(sym.scorecard) if sym.scorecard else "[]"

    console.print("[yellow]Rapporteur is synthesizing...[/yellow]")
    synthesis = rapporteur_synthesize(
        transcript=transcript,
        scorecard=scorecard,
        query=ws.query,
    )
    sym.synthesis = synthesis
    save(ws)

    console.print(RichPanel(synthesis[:1200], title="Synthesis"))


def cmd_run(args: argparse.Namespace) -> None:
    """Demo mode: full pipeline from query to synthesis. Convenience, not the primary interface."""
    console.print(f"\n[bold]COUNCIL Workspace — Demo Run[/bold]\n")
    query = args.query

    # Create workspace
    ws = WorkspaceState(query=query)
    console.print(f"Workspace [bold]{ws.id}[/bold]")

    # Panel
    console.print(Rule("Panel"))
    experts = moderator_propose_panel(query=query, max_experts=args.num)
    if not experts:
        _die("Moderator failed.")
    panel = Panel(name=query[:60], query=query, experts=experts)
    ws.panels.append(panel)
    for e in experts:
        console.print(f"  [bold]{e.name}[/bold] — {e.discipline}")

    # Research
    console.print(Rule("Research"))
    for expert in panel.experts:
        console.print(f"[yellow]{expert.name}[/yellow] researching...")
        sources = expert_research(expert=expert, query=query)
        for src in sources:
            verified = fact_check_source(src)
            expert.knowledge_pool.sources.append(verified)
            console.print(f"  [{verified.verification_status or 'pending'}] {src.title[:60]}")

    # Debate
    console.print(Rule("Debate"))
    sym = Symposium(
        title=f"Debate: {query[:50]}",
        format="structured",
        participant_ids=[e.id for e in panel.experts],
    )
    ws.symposia.append(sym)
    transcript_lines: list[str] = []
    for i, expert in enumerate(panel.experts):
        turn = i + 1
        console.print(f"[yellow]Turn {turn}: {expert.name}[/yellow]")
        context = "\n".join(transcript_lines) if transcript_lines else "(You are the first speaker.)"
        prompt = (
            f"=== DEBATE TRANSCRIPT SO FAR ===\n{context}\n=== END TRANSCRIPT ===\n\n"
            f"Present your evidence-based position on: {query}"
        )
        speech = expert_respond(expert=expert, workspace_id=ws.id, query=query, message=prompt)
        transcript_lines.append(f"[Turn {turn}] **{expert.name}** ({expert.discipline}):\n{speech}")
        ws.add_message(role="agent", agent_id=expert.id, agent_name=expert.name,
                       symposium_id=sym.id, content=speech, turn=turn)
        console.print(f"  [dim]{speech[:200]}...[/dim]")

    # Synthesize
    console.print(Rule("Synthesis"))
    transcript = "\n\n".join(transcript_lines)
    scorecard = str([
        {"claim": s.snippet[:100], "agent_name": s.added_by, "source_url": s.url,
         "verification_status": s.verification_status}
        for e in panel.experts for s in e.knowledge_pool.sources if s.verification_status == "verified"
    ])
    synthesis = rapporteur_synthesize(transcript=transcript, scorecard=scorecard, query=query)
    sym.synthesis = synthesis
    save(ws)

    console.print(RichPanel(synthesis[:1200], title="Synthesis"))
    console.print(f"\n[green]Done. Workspace: [bold]{ws.id}[/bold][/green]")


# ── Arg parser ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="council-workspace",
        description="COUNCIL Workspace CLI — module-based, no pipeline",
    )
    sub = parser.add_subparsers(dest="command")

    # new
    p = sub.add_parser("new", help="Create a new workspace")
    p.add_argument("query", nargs="?", default="")

    # load
    p = sub.add_parser("load", help="Show workspace summary")
    p.add_argument("id")

    # list
    p = sub.add_parser("list", help="List workspaces or experts")
    p.add_argument("ws_id", nargs="?")
    p.add_argument("--all", "-a", action="store_true", help="List all workspaces")

    # panel
    p = sub.add_parser("panel", help="Propose an expert panel")
    p.add_argument("ws_id")
    p.add_argument("query")
    p.add_argument("-n", "--num", type=int, default=5, help="Number of experts")

    # add-url
    p = sub.add_parser("add-url", help="Add a URL source to an expert")
    p.add_argument("ws_id")
    p.add_argument("expert_id")
    p.add_argument("url")
    p.add_argument("--title", "-t", default="")
    p.add_argument("--snippet", "-s", default="")

    # upload
    p = sub.add_parser("upload", help="Upload a file to an expert")
    p.add_argument("ws_id")
    p.add_argument("expert_id")
    p.add_argument("file_path")

    # verify
    p = sub.add_parser("verify", help="Fact-check unverified sources for an expert")
    p.add_argument("ws_id")
    p.add_argument("expert_id")

    # ask
    p = sub.add_parser("ask", help="Ask an expert a question")
    p.add_argument("ws_id")
    p.add_argument("expert_id")
    p.add_argument("message")

    # debate
    p = sub.add_parser("debate", help="Run a structured debate with a panel")
    p.add_argument("ws_id")
    p.add_argument("panel_id")

    # synthesize
    p = sub.add_parser("synthesize", help="Rapporteur synthesizes a symposium")
    p.add_argument("ws_id")
    p.add_argument("symposium_id")

    # run (demo)
    p = sub.add_parser("run", help="Demo: full pipeline from query to synthesis")
    p.add_argument("query", nargs="?", default="What is the best carbon pricing mechanism?")
    p.add_argument("-n", "--num", type=int, default=3, help="Number of experts")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    cmds = {
        "new": cmd_new,
        "load": cmd_load,
        "list": cmd_list,
        "panel": cmd_panel,
        "add-url": cmd_add_url,
        "upload": cmd_upload,
        "verify": cmd_verify,
        "ask": cmd_ask,
        "debate": cmd_debate,
        "synthesize": cmd_synthesize,
        "run": cmd_run,
    }

    try:
        cmds[args.command](args)
    except Exception as exc:
        _die(str(exc))


if __name__ == "__main__":
    main()
