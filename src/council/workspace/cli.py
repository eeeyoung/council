#!/usr/bin/env python3
"""
council/workspace/cli.py

Module-based CLI for the workspace system. Each subcommand is independently
invocable — no pipeline, no vertical dependencies.

Single implicit session (id="default"). No ws_id parameter needed.

Usage:
  uv run python -m council.workspace.cli list
  uv run python -m council.workspace.cli panel-add <query> [-n N]
  uv run python -m council.workspace.cli panel-rm <panel_id>
  uv run python -m council.workspace.cli panel-regenerate <panel_id>
  uv run python -m council.workspace.cli add-url <panel_id> <expert_id> <url>
  uv run python -m council.workspace.cli upload <panel_id> <expert_id> <file>
  uv run python -m council.workspace.cli verify <panel_id> <expert_id>
  uv run python -m council.workspace.cli ask <panel_id> <expert_id> "<msg>"
  uv run python -m council.workspace.cli debate --panel <panel_id>
  uv run python -m council.workspace.cli debate --expert-ids a,b,c --query "Q"
  uv run python -m council.workspace.cli synthesize <symposium_id>
  uv run python -m council.workspace.cli export
  uv run python -m council.workspace.cli run <query>   # demo pipeline
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
from council.workspace.db import get_or_create_default, save
from council.workspace.state import Panel, Symposium, Session

console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _die(msg: str) -> None:
    console.print(f"[red]Error:[/red] {msg}")
    sys.exit(1)


def _load() -> Session:
    return get_or_create_default()


def _find_expert(ws: Session, expert_id: str):
    expert = ws.get_expert(expert_id)
    if not expert:
        _die(f"Expert not found: {expert_id}")
    return expert


def _get_query(ws: Session, panel_id: str | None = None) -> str:
    """Get a reasonable query string from a panel or fallback."""
    if panel_id:
        panel = ws.get_panel(panel_id)
        if panel and panel.query:
            return panel.query
    if ws.panels and ws.panels[0].query:
        return ws.panels[0].query
    return "the research context"


# ── Subcommands ──────────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> None:
    ws = _load()

    console.print(Rule("COUNCIL Session"))
    for pi, panel in enumerate(ws.panels):
        console.print(f"\n[bold]Panel {pi+1}:[/bold] {panel.name or panel.id}")
        console.print(f"  Query: [italic]{panel.query or '(none)'}[/italic]")
        console.print(f"  Function: {panel.function_type or '(none)'}")
        for e in panel.experts:
            n_sources = len(e.knowledge_pool.sources)
            n_opinions = len(e.knowledge_pool.opinions)
            console.print(f"    [{e.id}] [bold]{e.name}[/bold] — {e.discipline}")
            console.print(f"         {n_sources} sources, {n_opinions} opinions")

    for sym in ws.symposia:
        console.print(f"\n[bold]Symposium:[/bold] {sym.title or sym.id} ({sym.format})")
        console.print(f"  Participants: {len(sym.participant_ids)}, Messages: {len(sym.message_ids)}")
        if sym.synthesis:
            console.print(f"  Synthesis: {len(sym.synthesis)} chars")


def cmd_panel_add(args: argparse.Namespace) -> None:
    ws = _load()
    console.print(f"[yellow]Moderator proposing panel for:[/yellow] {args.query}")
    experts = moderator_propose_panel(query=args.query, max_experts=args.num)
    if not experts:
        _die("Moderator failed to propose experts.")

    panel = Panel(
        name=args.query[:60],
        query=args.query,
        experts=experts,
    )
    ws.panels.append(panel)
    save(ws)

    console.print(f"\n[green]Panel added:[/green] [bold]{panel.id}[/bold]")
    for e in experts:
        console.print(f"  [{e.id}] [bold]{e.name}[/bold] — {e.discipline} ({e.bias})")


def cmd_panel_rm(args: argparse.Namespace) -> None:
    ws = _load()
    panel = ws.get_panel(args.panel_id)
    if not panel:
        _die(f"Panel not found: {args.panel_id}")
    ws.panels = [p for p in ws.panels if p.id != args.panel_id]
    save(ws)
    console.print(f"[green]Panel removed:[/green] {args.panel_id}")


def cmd_panel_regenerate(args: argparse.Namespace) -> None:
    ws = _load()
    panel = ws.get_panel(args.panel_id)
    if not panel:
        _die(f"Panel not found: {args.panel_id}")

    console.print(f"[yellow]Regenerating experts for:[/yellow] {panel.name or panel.id}")
    experts = moderator_propose_panel(
        query=panel.query,
        max_experts=args.num or 5,
    )
    if not experts:
        _die("Moderator failed to propose experts.")

    panel.experts = experts
    save(ws)

    console.print(f"\n[green]Panel regenerated:[/green]")
    for e in experts:
        console.print(f"  [{e.id}] [bold]{e.name}[/bold] — {e.discipline} ({e.bias})")


def cmd_add_url(args: argparse.Namespace) -> None:
    ws = _load()
    expert = _find_expert(ws, args.expert_id)

    src = add_source_to_expert(
        expert=expert,
        session_id=ws.id,
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
    ws = _load()
    expert = _find_expert(ws, args.expert_id)

    file_path = Path(args.file_path)
    if not file_path.exists():
        _die(f"File not found: {args.file_path}")

    src = upload_file_to_expert(expert=expert, session_id=ws.id, file_path=args.file_path)
    if not src:
        _die(f"Could not parse file: {args.file_path}")

    save(ws)
    console.print(f"[green]File uploaded to {expert.name}:[/green] [{src.id}] {file_path.name}")
    console.print(f"  Full text: {len(src.full_text)} chars")


def cmd_verify(args: argparse.Namespace) -> None:
    ws = _load()
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
    ws = _load()
    expert = _find_expert(ws, args.expert_id)
    query = _get_query(ws, getattr(args, 'panel_id', None))

    response = expert_respond(
        expert=expert,
        session_id=ws.id,
        query=query,
        message=args.message,
    )
    ws.add_message(role="agent", agent_id=expert.id, agent_name=expert.name, content=response)
    save(ws)

    console.print(RichPanel(response[:1200], title=f"{expert.name}'s response"))


def cmd_expert(args: argparse.Namespace) -> None:
    """Show expert profile, knowledge pool summary, and ChromaDB info."""
    ws = _load()
    expert = _find_expert(ws, args.expert_id)

    # Find which panel this expert belongs to
    panel_name = "?"
    for p in ws.panels:
        if any(e.id == expert.id for e in p.experts):
            panel_name = p.name or p.id
            break

    # Profile card
    table = Table(title=f"Expert: {expert.name}")
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("UUID", expert.id)
    table.add_row("Panel", panel_name)
    table.add_row("Discipline", expert.discipline)
    table.add_row("Bias", expert.bias or "(none)")
    table.add_row("Persona", expert.persona_prompt or "(none)")
    table.add_row("Photo URL", expert.photo_url or "(none)")
    console.print(table)

    # Knowledge pool summary
    pool = expert.knowledge_pool
    console.print(f"\n[bold]Knowledge Pool[/bold] — {len(pool.sources)} sources, {len(pool.opinions)} opinions")

    if pool.sources:
        src_table = Table(title="Sources")
        src_table.add_column("ID", style="dim")
        src_table.add_column("Status")
        src_table.add_column("Title / URL")
        for s in pool.sources:
            icon = {"verified": "[green]✓[/green]", "misattributed": "[red]✗[/red]",
                    "unverifiable": "[yellow]?[/yellow]"}.get(s.verification_status, "[dim]○[/dim]")
            src_table.add_row(s.id, icon, (s.title or s.url)[:80])
        console.print(src_table)

    if pool.opinions:
        console.print(f"\n[bold]Opinions:[/bold]")
        for o in pool.opinions:
            console.print(f"  • {o.text[:120]}… (cites {len(o.source_ids)} sources)")

    # ChromaDB info
    console.print(f"\n[bold]ChromaDB[/bold] — collection: [cyan]expert_{expert.id}[/cyan]")
    try:
        import os
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=os.path.join(os.getcwd(), "chroma_db", "ws_default"),
            settings=Settings(anonymized_telemetry=False),
        )
        col = client.get_collection(f"expert_{expert.id}")
        count = col.count()
        console.print(f"  Chunks indexed: {count}")
        if count > 0:
            data = col.get(limit=1, include=["metadatas"])
            if data["metadatas"]:
                m = data["metadatas"][0]
                console.print(f"  Sample metadata: source_id={m.get('source_id','?')} "
                              f"title={str(m.get('title','?'))[:60]} "
                              f"status={m.get('verification_status','?')}")
    except Exception as e:
        console.print(f"  [dim]Could not open collection: {e}[/dim]")


def cmd_expert_sources(args: argparse.Namespace) -> None:
    """List all sources in an expert's knowledge pool with optional status filter."""
    ws = _load()
    expert = _find_expert(ws, args.expert_id)

    sources = expert.knowledge_pool.sources
    if args.status:
        if args.status == "pending":
            sources = [s for s in sources if not s.verification_status]
        else:
            sources = [s for s in sources if s.verification_status == args.status]

    if not sources:
        console.print(f"[dim]No sources found{'' if not args.status else ' with status=' + args.status}[/dim]")
        return

    console.print(f"[bold]{expert.name}[/bold] — {len(sources)} source(s)")
    for s in sources:
        status = s.verification_status or "pending"
        icon = {"verified": "✓", "misattributed": "✗", "unverifiable": "?"}.get(status, "○")
        console.print(f"\n  [{icon} [bold]{status}[/bold]] [{s.id}] {s.title or 'Untitled'}")
        if s.url:
            console.print(f"    URL: [cyan]{s.url}[/cyan]")
        if s.snippet:
            console.print(f"    Snippet: {s.snippet[:200]}")
        if s.verification_note:
            console.print(f"    Note: [dim]{s.verification_note}[/dim]")
        if s.full_text:
            console.print(f"    Full text: {len(s.full_text)} chars (type={s.type}, added_by={s.added_by})")


def cmd_expert_chunks(args: argparse.Namespace) -> None:
    """Show ChromaDB vector chunks for an expert."""
    ws = _load()
    expert = _find_expert(ws, args.expert_id)

    try:
        import os
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=os.path.join(os.getcwd(), "chroma_db", "ws_default"),
            settings=Settings(anonymized_telemetry=False),
        )
        col = client.get_collection(f"expert_{expert.id}")
        count = col.count()
        limit = min(args.limit, count)
        if count == 0:
            console.print("[dim]No chunks indexed for this expert.[/dim]")
            return

        data = col.get(limit=limit, include=["documents", "metadatas"])
        console.print(f"[bold]{expert.name}[/bold] — {count} total chunks (showing {limit})")

        for i in range(limit):
            doc = data["documents"][i]
            meta = data["metadatas"][i] if data["metadatas"] else {}
            console.print(f"\n[bold]Chunk {i+1}[/bold]")
            console.print(f"  Source: {meta.get('title', '?')}")
            console.print(f"  URL: [cyan]{meta.get('url', '?')}[/cyan]")
            console.print(f"  Status: {meta.get('verification_status', '?')}")
            console.print(f"  Text: [dim]{doc[:300]}...[/dim]")

    except Exception as e:
        _die(f"Could not open ChromaDB collection: {e}")


def cmd_debate(args: argparse.Namespace) -> None:
    ws = _load()
    participants = []
    query = ""

    # Determine participants and query based on mode
    if args.expert_ids:
        # Mode B: custom expert IDs
        for eid in args.expert_ids.split(","):
            eid = eid.strip()
            expert = ws.get_expert(eid)
            if expert:
                participants.append(expert)
        query = args.query or "Custom Symposium"
    elif args.panel:
        # Mode A: use a panel's experts + query
        panel = ws.get_panel(args.panel)
        if not panel:
            _die(f"Panel not found: {args.panel}")
        participants = list(panel.experts)
        query = panel.query or args.query or "Debate"
    else:
        # Fallback: all experts across all panels
        for panel in ws.panels:
            participants.extend(panel.experts)
        query = args.query or "Cross-panel Debate"

    if not participants:
        _die("No participants found.")

    sym = Symposium(
        title=f"Debate: {query[:50]}",
        format="structured",
        participant_ids=[e.id for e in participants],
    )
    ws.symposia.append(sym)

    transcript_lines: list[str] = []

    for i, expert in enumerate(participants):
        turn = i + 1
        console.print(f"\n[yellow]Turn {turn}: {expert.name}[/yellow]")

        context = "\n".join(transcript_lines) if transcript_lines else "(You are the first speaker.)"
        prompt = (
            f"=== DEBATE TRANSCRIPT SO FAR ===\n{context}\n=== END TRANSCRIPT ===\n\n"
            f"Present your evidence-based position on: {query}\n\n"
            f"As turn {turn}, respond to previous speakers and present your unique "
            f"disciplinary perspective grounded in your knowledge pool."
        )

        speech = expert_respond(
            expert=expert,
            session_id=ws.id,
            query=query,
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
    ws = _load()
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
    query = _get_query(ws)

    console.print("[yellow]Rapporteur is synthesizing...[/yellow]")
    synthesis = rapporteur_synthesize(
        transcript=transcript,
        scorecard=scorecard,
        query=query,
    )
    sym.synthesis = synthesis
    save(ws)

    console.print(RichPanel(synthesis[:1200], title="Synthesis"))


def cmd_export(args: argparse.Namespace) -> None:
    from council.workspace.export import export_all
    ws = _load()
    formats = None if args.format == "all" else [args.format]
    result = export_all(ws, formats)
    console.print(f"[green]Exported:[/green]")
    for fmt, filename in result.items():
        console.print(f"  {fmt}: [bold]{filename}[/bold]")


def cmd_run(args: argparse.Namespace) -> None:
    """Demo mode: full pipeline from query to synthesis."""
    console.print(f"\n[bold]COUNCIL Session — Demo Run[/bold]\n")
    query = args.query
    ws = _load()

    # Panel
    console.print(Rule("Panel"))
    experts = moderator_propose_panel(query=query, max_experts=args.num)
    if not experts:
        _die("Moderator failed.")
    panel = Panel(name=query[:60], query=query, experts=experts)
    ws.panels.append(panel)
    save(ws)
    console.print(f"Panel: [bold]{panel.id}[/bold]")

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

    save(ws)

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
        speech = expert_respond(expert=expert, session_id=ws.id, query=query, message=prompt)
        transcript_lines.append(f"[Turn {turn}] **{expert.name}** ({expert.discipline}):\n{speech}")
        ws.add_message(role="agent", agent_id=expert.id, agent_name=expert.name,
                       symposium_id=sym.id, content=speech, turn=turn)
        console.print(f"  [dim]{speech[:200]}...[/dim]")

    # Synthesize
    console.print(Rule("Synthesis"))
    transcript = "\n\n".join(transcript_lines)
    all_experts = [e for p in ws.panels for e in p.experts]
    scorecard = str([
        {"claim": s.snippet[:100], "agent_name": s.added_by, "source_url": s.url,
         "verification_status": s.verification_status}
        for e in all_experts for s in e.knowledge_pool.sources if s.verification_status == "verified"
    ])
    synthesis = rapporteur_synthesize(transcript=transcript, scorecard=scorecard, query=query)
    sym.synthesis = synthesis
    save(ws)

    console.print(RichPanel(synthesis[:1200], title="Synthesis"))
    console.print(f"\n[green]Done. Session: [bold]{ws.id}[/bold][/green]")


# ── Arg parser ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="council-workspace",
        description="COUNCIL Workspace CLI — single-session, multi-panel",
    )
    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser("list", help="List all panels, experts, and symposia")

    # panel-add
    p = sub.add_parser("panel-add", help="Add a new expert panel")
    p.add_argument("query")
    p.add_argument("-n", "--num", type=int, default=5, help="Number of experts")

    # panel-rm
    p = sub.add_parser("panel-rm", help="Remove a panel")
    p.add_argument("panel_id")

    # panel-regenerate
    p = sub.add_parser("panel-regenerate", help="Regenerate experts for a panel")
    p.add_argument("panel_id")
    p.add_argument("-n", "--num", type=int, default=5, help="Number of experts")

    # add-url
    p = sub.add_parser("add-url", help="Add a URL source to an expert")
    p.add_argument("panel_id")
    p.add_argument("expert_id")
    p.add_argument("url")
    p.add_argument("--title", "-t", default="")
    p.add_argument("--snippet", "-s", default="")

    # upload
    p = sub.add_parser("upload", help="Upload a file to an expert")
    p.add_argument("panel_id")
    p.add_argument("expert_id")
    p.add_argument("file_path")

    # expert — inspect expert profile and storage
    p = sub.add_parser("expert", help="Show expert profile, pool summary, and ChromaDB info")
    p.add_argument("expert_id", help="Expert UUID (e.g. 954f0356)")

    # expert-sources — list all sources for an expert
    p = sub.add_parser("expert-sources", help="List all sources in an expert's knowledge pool")
    p.add_argument("expert_id", help="Expert UUID")
    p.add_argument("--status", "-s", default="", choices=["verified","misattributed","unverifiable","pending",""],
                   help="Filter by verification status (default: all)")

    # expert-chunks — show ChromaDB chunks for an expert
    p = sub.add_parser("expert-chunks", help="Show ChromaDB vector chunks for an expert")
    p.add_argument("expert_id", help="Expert UUID")
    p.add_argument("--limit", "-n", type=int, default=10, help="Max chunks to show (default: 10)")

    # verify
    p = sub.add_parser("verify", help="Fact-check unverified sources for an expert")
    p.add_argument("panel_id")
    p.add_argument("expert_id")

    # ask
    p = sub.add_parser("ask", help="Ask an expert a question")
    p.add_argument("panel_id")
    p.add_argument("expert_id")
    p.add_argument("message")

    # debate
    p = sub.add_parser("debate", help="Run a structured debate")
    p.add_argument("--panel", "-p", default="", help="Use this panel's experts + query")
    p.add_argument("--expert-ids", default="", help="Comma-separated expert IDs (custom mode)")
    p.add_argument("--query", "-q", default="", help="Custom debate question")

    # synthesize
    p = sub.add_parser("synthesize", help="Rapporteur synthesizes a symposium")
    p.add_argument("symposium_id")

    # export
    p = sub.add_parser("export", help="Export dossier, memo, scorecard, or transcript")
    p.add_argument("--format", "-f", default="all", choices=["all","dossier","memo","scorecard","transcript"])

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
        "list": cmd_list,
        "panel-add": cmd_panel_add,
        "panel-rm": cmd_panel_rm,
        "panel-regenerate": cmd_panel_regenerate,
        "add-url": cmd_add_url,
        "upload": cmd_upload,
        "verify": cmd_verify,
        "ask": cmd_ask,
        "expert": cmd_expert,
        "expert-sources": cmd_expert_sources,
        "expert-chunks": cmd_expert_chunks,
        "debate": cmd_debate,
        "synthesize": cmd_synthesize,
        "export": cmd_export,
        "run": cmd_run,
    }

    try:
        cmds[args.command](args)
    except Exception as exc:
        _die(str(exc))


if __name__ == "__main__":
    main()
