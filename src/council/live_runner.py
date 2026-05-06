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

    # Announce each expert before research begins
    for expert in state.experts:
        expert_id = _safe_id(expert.name)
        yield "research_start", {
            "expert_id": expert_id,
            "expert_name": expert.name,
            "discipline": expert.discipline,
        }
        await asyncio.sleep(0.15)

    from council.crews.research_crew import run_research

    state = await asyncio.to_thread(run_research, state, None, False)
    save_state(state)

    # Emit research_complete for each expert with full summary
    for expert in state.experts:
        summary = state.research_summaries.get(expert.name, "")
        expert_id = _safe_id(expert.name)
        # Truncate long summaries for the SSE event (full text saved to file anyway)
        preview = summary[:600] + "…" if len(summary) > 600 else summary
        yield "research_complete", {
            "expert_id": expert_id,
            "expert_name": expert.name,
            "summary": preview,
        }
        await asyncio.sleep(0.15)

    # Write research output files
    for key, text in state.research_summaries.items():
        safe = key.replace(" ", "_").replace(".", "").replace("__", "_").lower()
        fname = f"{session_id}_research_{safe}.md"
        (OUT_DIR / fname).write_text(text, encoding="utf-8")

    _write_manifest(state, OUT_DIR)
    yield "phase_complete", {"phase": "B"}

    # ── Phase C + D: Debate / Audit Loop ───────────────────────────────────
    yield "phase_start", {"phase": "C"}

    from council.crews.debate_crew import (
        run_debate, run_expert_turn, run_scorecard, _load_tasks_config,
    )
    from council.crews.audit_crew import run_audit_loop
    from council.tools.search_tool import create_search_tool
    from council.tools.library_tool import create_library_tools
    from council.tools.pdf_tool import create_pdf_tool
    from council.config import build_llm

    while state.status in ("debating", "auditing"):

        if state.status == "debating":
            round_num = state.audit_round + 1
            yield "round_start", {"round": round_num}

            # Build shared tools once for all experts this round
            search_tool = create_search_tool()
            library_write, library_read = create_library_tools()
            pdf_tool = create_pdf_tool()
            llm = build_llm(temperature=0.8)
            tasks_cfg = _load_tasks_config()

            # Run each expert one at a time — emit their speech immediately
            for expert_def in state.experts:
                # Typing indicator
                yield "debate_typing", {
                    "name": expert_def.name,
                    "discipline": expert_def.discipline,
                    "round": round_num,
                }
                await asyncio.sleep(1.0)

                # Run the expert's turn (blocking — LLM must finish)
                speech = await asyncio.to_thread(
                    run_expert_turn,
                    state=state,
                    expert_def=expert_def,
                    search_tool=search_tool,
                    library_write=library_write,
                    library_read=library_read,
                    pdf_tool=pdf_tool,
                    llm=llm,
                    tasks_cfg=tasks_cfg,
                )
                save_state(state)

                # Emit the expert's message immediately — real-time!
                yield "debate_message", {
                    "name": expert_def.name,
                    "discipline": expert_def.discipline,
                    "round": round_num,
                    "content": speech.strip(),
                    "turn": state.transcript[-1].turn if state.transcript else 1,
                }
                await asyncio.sleep(0.5)

            # Scorecard
            state = await asyncio.to_thread(run_scorecard, state, False)
            save_state(state)

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
            # Signal the GUI that the audit loop is working (it's a blocking call)
            yield "debate_typing", {
                "name": "Rapporteur",
                "discipline": "Audit Loop",
                "round": state.audit_round + 1,
            }
            await asyncio.sleep(0.3)

            prev_len = len(state.transcript)
            state = await asyncio.to_thread(run_audit_loop, state, None, False)
            save_state(state)

            # Emit audit-phase messages (Rapporteur, Discussant) in real-time
            for entry in state.transcript[prev_len:]:
                if entry.phase == "audit":
                    yield "debate_typing", {
                        "name": entry.agent_name,
                        "discipline": entry.discipline,
                        "round": state.audit_round + 1,
                    }
                    await asyncio.sleep(1.0)
                    yield "debate_message", {
                        "name": entry.agent_name,
                        "discipline": entry.discipline,
                        "round": state.audit_round + 1,
                        "content": entry.speech,
                        "turn": entry.turn,
                    }
                    await asyncio.sleep(0.5)

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

                # Emit expectation evaluation if available
                if state.expectation_met is not None:
                    yield "expectation_result", {
                        "met": state.expectation_met,
                        "mandate": state.expectation_mandate or "",
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


from council.manifest import write_manifest as _write_manifest
