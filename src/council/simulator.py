"""
council/simulator.py

Reads completed session output files and replays them as SSE events with
realistic timing delays — no LLM tokens consumed.

Consumed by server.py's GET /api/sessions/{id}/events endpoint.
Each yielded tuple is (event_type: str, data: dict).

Event catalogue:
  session_start       — initial manifest broadcast
  phase_start         — {"phase": "A"}
  phase_complete      — {"phase": "A"}
  research_start      — {"expert_id": ..., "expert_name": ...}
  research_chunk      — {"expert_id": ..., "chunk": <paragraph text>}
  research_complete   — {"expert_id": ..., "expert_name": ..., "file": ...}
  round_start         — {"round": <int>}
  debate_typing       — typing indicator before a message arrives
  debate_message      — full message: {name, marker, meta, round, content}
  scorecard_ready     — {"round": ..., "file": ...}
  audit_result        — {"round": ..., "file": ...}
  dossier_chunk       — {"chunk": <paragraph text>}
  dossier_complete    — {"file": ...}
  session_complete    — {"session_id": ...}
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import AsyncIterator

ROOT        = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = ROOT / "outputs"

# Timing constants (seconds)
_WORD_DELAY      = 0.018   # between words in typewriter stream
_MSG_PAUSE       = 0.9     # pause after a message finishes
_INDICATOR_PAUSE = 1.2     # how long the "typing…" indicator shows
_PARA_PAUSE      = 0.12    # between research paragraphs
_DOSSIER_PAUSE   = 0.08    # between dossier paragraphs


async def simulate_session(
    session_id: str, manifest: dict
) -> AsyncIterator[tuple[str, dict]]:
    """Async generator — yields (event_type, data) for every event in the replay."""

    yield "session_start", {
        "session_id": session_id,
        "query":      manifest.get("query", ""),
        "manifest":   manifest,
    }

    phases   = manifest.get("phases_complete", [])
    files    = manifest.get("files", {})

    # ── Phase A ───────────────────────────────────────────────────────────────
    if "A" in phases:
        yield "phase_start",    {"phase": "A"}
        await asyncio.sleep(0.4)
        yield "phase_complete", {"phase": "A"}

    # ── Phase B: stream each research file paragraph by paragraph ─────────────
    if "B" in phases:
        yield "phase_start", {"phase": "B"}
        for rf in files.get("research", []):
            path = OUTPUTS_DIR / rf["file"]
            if not path.exists():
                continue

            yield "research_start", {"expert_id": rf["expert_id"], "expert_name": rf["expert_name"]}

            text = path.read_text(encoding="utf-8")
            for para in text.split("\n\n"):
                if para.strip():
                    yield "research_chunk", {"expert_id": rf["expert_id"], "chunk": para + "\n\n"}
                    await asyncio.sleep(_PARA_PAUSE)

            preview = text[:600] + "…" if len(text) > 600 else text
            yield "research_complete", {
                "expert_id":   rf["expert_id"],
                "expert_name": rf["expert_name"],
                "file":        rf["file"],
                "summary":     preview,
            }
            await asyncio.sleep(0.25)

        yield "phase_complete", {"phase": "B"}

    # ── Phase C: replay debate transcript message by message ──────────────────
    if "C" in phases:
        yield "phase_start", {"phase": "C"}

        msg_regex = re.compile(
            r"(\[Turn \d+\]|\[RAPPORTEUR\]|\[DISCUSSANT\]) \*\*(.*?)\*\* \((.*?)\):\n"
            r"([\s\S]*?)(?=\n(?:\[Turn \d+\]|\[RAPPORTEUR\]|\[DISCUSSANT\])|$)"
        )

        for round_info in files.get("rounds", []):
            transcript_file = round_info.get("transcript")
            if not transcript_file:
                continue

            path = OUTPUTS_DIR / transcript_file
            if not path.exists():
                continue

            round_num = round_info["round"]
            yield "round_start", {"round": round_num}

            text         = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            current_round = round_num + 1

            for match in msg_regex.finditer(text):
                marker  = match.group(1)
                name    = match.group(2)
                meta    = match.group(3)
                content = match.group(4).strip()

                r_match = re.search(r"Round (\d+)", meta)
                if r_match:
                    current_round = int(r_match.group(1))

                # Typing indicator
                yield "debate_typing", {
                    "name":   name,
                    "marker": marker,
                    "meta":   meta,
                    "round":  current_round,
                }
                await asyncio.sleep(_INDICATOR_PAUSE)

                # Stream content word by word
                words    = re.split(r"(\s+)", content)
                streamed = ""
                for word in words:
                    streamed += word
                    if word.strip():
                        yield "debate_word", {
                            "name":    name,
                            "marker":  marker,
                            "meta":    meta,
                            "round":   current_round,
                            "content": streamed,
                        }
                        await asyncio.sleep(_WORD_DELAY)

                # Full message
                yield "debate_message", {
                    "name":       name,
                    "marker":     marker,
                    "meta":       meta,
                    "discipline": meta,  # meta IS the discipline
                    "round":      current_round,
                    "content":    content,
                }
                await asyncio.sleep(_MSG_PAUSE)

            # Scorecard and consensus for this round
            if round_info.get("scorecard"):
                yield "scorecard_ready", {"round": round_num, "file": round_info["scorecard"]}

            if round_info.get("consensus"):
                # Infer approved: if this is the last round with a consensus, it was approved
                all_rounds = files.get("rounds", [])
                has_next_round = any(
                    r["round"] == round_num + 1 for r in all_rounds
                )
                approved = not has_next_round
                yield "audit_result", {
                    "round":    round_num,
                    "approved": approved,
                    "verdict":  "APPROVED" if approved else "REJECTED",
                    "issues":   [],
                    "mandate":  "",
                    "file":     round_info["consensus"],
                }

        yield "phase_complete", {"phase": "C"}

    # ── Phase D ───────────────────────────────────────────────────────────────
    if "D" in phases:
        yield "phase_complete", {"phase": "D"}

    # ── Phase E: stream dossier paragraph by paragraph ────────────────────────
    if "E" in phases:
        yield "phase_start", {"phase": "E"}
        dossier_file = files.get("dossier")
        if dossier_file:
            path = OUTPUTS_DIR / dossier_file
            if path.exists():
                text = path.read_text(encoding="utf-8")
                for para in text.split("\n\n"):
                    if para.strip():
                        yield "dossier_chunk", {"chunk": para + "\n\n"}
                        await asyncio.sleep(_DOSSIER_PAUSE)
                yield "dossier_complete", {"file": dossier_file}
        yield "phase_complete", {"phase": "E"}

    yield "session_complete", {"session_id": session_id}
