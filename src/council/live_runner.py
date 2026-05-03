"""
council/live_runner.py

Async generator that runs the full COUNCIL pipeline (Phases B-E) live and emits
SSE events at each milestone. Wraps synchronous crew functions in asyncio.to_thread().

Used by server.py's GET /api/sessions/{id}/live endpoint.

Event catalogue (same contract as simulator.py):
  session_start, phase_start, phase_complete, research_complete,
  round_start, debate_message, scorecard_ready, audit_result,
  dossier_chunk, dossier_complete, session_complete
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from council.db import save_state
from council.state import CouncilState

OUT_DIR = Path("outputs")


async def run_live_session(state: CouncilState) -> AsyncIterator[tuple[str, dict]]:
    """Run Phases B-E of the pipeline live, yielding SSE events."""

    session_id = state.session_id
    query = state.query

    yield "session_start", {"session_id": session_id, "query": query}

    # ── Phase B: Parallel Research ─────────────────────────────────────────
    yield "phase_start", {"phase": "B"}

    from council.crews.research_crew import run_research

    state = await asyncio.to_thread(run_research, state, None, False)
    save_state(state)

    # Emit research_complete for each expert
    for expert in state.experts:
        summary = state.research_summaries.get(expert.name, "")
        expert_id = _safe_id(expert.name)
        yield "research_complete", {
            "expert_id": expert_id,
            "expert_name": expert.name,
            "summary": summary,
        }
        await asyncio.sleep(0.1)

    # Write research output files
    for key, text in state.research_summaries.items():
        safe = key.replace(" ", "_").replace(".", "").replace("__", "_").lower()
        fname = f"{session_id}_research_{safe}.md"
        (OUT_DIR / fname).write_text(text, encoding="utf-8")

    _write_manifest(state, OUT_DIR)
    yield "phase_complete", {"phase": "B"}

    # ── Phase C + D: Debate / Audit Loop ───────────────────────────────────
    yield "phase_start", {"phase": "C"}

    from council.crews.debate_crew import run_debate
    from council.crews.audit_crew import run_audit_loop

    while state.status in ("debating", "auditing"):

        if state.status == "debating":
            round_num = state.audit_round + 1
            yield "round_start", {"round": round_num}

            # Track transcript length before debate so we only emit new entries
            prev_len = len(state.transcript)
            state = await asyncio.to_thread(run_debate, state, None, False)
            save_state(state)

            # Emit only the new debate messages from this round
            for entry in state.transcript[prev_len:]:
                if entry.phase == "debate":
                    yield "debate_message", {
                        "name": entry.agent_name,
                        "discipline": entry.discipline,
                        "round": round_num,
                        "content": entry.speech,
                        "turn": entry.turn,
                    }
                    await asyncio.sleep(0.05)

            # Write transcript and scorecard files for this round
            r = state.audit_round
            _write_file(f"{session_id}_transcript_r{r}.md",
                        f"# Phase C Debate Transcript (Round {round_num})\n\n"
                        f"Session: {session_id}\nQuery: {query}\n\n"
                        f"{state.transcript_text}")
            _write_file(f"{session_id}_scorecard_r{r}.md",
                        f"# Phase C Evidence Scorecard (Session {session_id} - Round {round_num})\n\n"
                        f"{state.evidence_scorecard_text}")

            yield "scorecard_ready", {"round": r}

        if state.status == "auditing":
            state = await asyncio.to_thread(run_audit_loop, state, None, False)
            save_state(state)

            if state.audit_history:
                latest = state.audit_history[-1]
                if state.synthesis:
                    _write_file(f"{session_id}_consensus_r{state.audit_round}.md",
                                state.synthesis)
                yield "audit_result", {
                    "round": latest.round,
                    "approved": latest.approved,
                    "verdict": latest.verdict,
                    "issues": latest.issues,
                    "mandate": latest.conflict_mandate or "",
                }

        _write_manifest(state, OUT_DIR)

    yield "phase_complete", {"phase": "C"}
    yield "phase_complete", {"phase": "D"}

    # ── Phase E: Final Dossier ─────────────────────────────────────────────
    yield "phase_start", {"phase": "E"}

    from council.crews.dossier_crew import run_dossier

    state = await asyncio.to_thread(run_dossier, state, None, False)
    save_state(state)

    # Stream dossier paragraphs
    dossier_text = state.dossier_path or ""
    for para in dossier_text.split("\n\n"):
        if para.strip():
            yield "dossier_chunk", {"chunk": para + "\n\n"}
            await asyncio.sleep(0.08)

    dossier_file = f"{session_id}_dossier.md"
    _write_file(dossier_file, dossier_text)
    yield "dossier_complete", {"file": dossier_file}

    _write_manifest(state, OUT_DIR)
    yield "phase_complete", {"phase": "E"}

    # ── Done ───────────────────────────────────────────────────────────────
    state.status = "done"
    save_state(state)
    _write_manifest(state, OUT_DIR)

    yield "session_complete", {"session_id": session_id}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_id(name: str) -> str:
    return name.replace(".", "").replace(" ", "_").lower()


def _write_file(filename: str, content: str) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / filename).write_text(content, encoding="utf-8")


def _write_manifest(state: CouncilState, out_dir: Path) -> None:
    """Write/update outputs/{session_id}_manifest.json for GUI consumption."""
    import json

    experts = []
    for i, e in enumerate(state.experts):
        expert_id = e.name.replace(".", "").replace(" ", "_").lower()
        experts.append({
            "id": expert_id,
            "name": e.name,
            "discipline": e.discipline,
            "bias": e.bias,
            "persona_prompt": e.persona_prompt,
            "color_index": i,
        })

    research_files: list[dict] = []
    for expert in experts:
        f = out_dir / f"{state.session_id}_research_{expert['id']}.md"
        if f.exists():
            research_files.append({
                "expert_id": expert["id"],
                "expert_name": expert["name"],
                "file": f.name,
            })
    agg = out_dir / f"{state.session_id}_research___aggregation__.md"
    if agg.exists():
        research_files.append({
            "expert_id": "__aggregation__",
            "expert_name": "Aggregator Summary",
            "file": agg.name,
        })

    rounds: list[dict] = []
    for r in range(state.max_audit_rounds + 2):
        t = out_dir / f"{state.session_id}_transcript_r{r}.md"
        s = out_dir / f"{state.session_id}_scorecard_r{r}.md"
        c = out_dir / f"{state.session_id}_consensus_r{r + 1}.md"
        if t.exists() or s.exists():
            rounds.append({
                "round": r,
                "transcript": t.name if t.exists() else None,
                "scorecard": s.name if s.exists() else None,
                "consensus": c.name if c.exists() else None,
            })

    panel = out_dir / f"{state.session_id}_panel.json"
    dossier = out_dir / f"{state.session_id}_dossier.md"

    phases_complete: list[str] = []
    if panel.exists():
        phases_complete.append("A")
    if research_files:
        phases_complete.append("B")
    if rounds:
        phases_complete.append("C")
    if any(r.get("consensus") for r in rounds):
        phases_complete.append("D")
    if dossier.exists():
        phases_complete.append("E")

    manifest = {
        "session_id": state.session_id,
        "query": state.query,
        "status": state.status,
        "created_at": state.created_at.isoformat(),
        "experts": experts,
        "audit_rounds": len(rounds),
        "files": {
            "panel": panel.name if panel.exists() else None,
            "research": research_files,
            "rounds": rounds,
            "dossier": dossier.name if dossier.exists() else None,
        },
        "phases_complete": phases_complete,
    }

    out_dir.mkdir(exist_ok=True)
    manifest_path = out_dir / f"{state.session_id}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
