"""
council/resume.py

Utility to reconstruct a CouncilState from saved output files.

Use when:
- The SQLite DB is missing or corrupted
- You want to skip Phases A/B/C and jump straight to Phase D
- You need programmatic batch processing of previous sessions

Usage:
    from council.resume import load_session_from_outputs
    state = load_session_from_outputs("57011c05", "outputs")
    # state.status == "auditing" — ready for Phase D
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from council.state import (
    CouncilState,
    EvidenceEntry,
    ExpertDefinition,
    TranscriptEntry,
)


def _parse_experts_from_panel(panel_path: Path) -> list[ExpertDefinition]:
    with open(panel_path, encoding="utf-8") as f:
        data = json.load(f)
    return [ExpertDefinition(**item) for item in data]


def _parse_research_summaries(outputs_dir: Path, session_id: str) -> dict[str, str]:
    summaries: dict[str, str] = {}
    for path in sorted(outputs_dir.glob(f"{session_id}_research_dr_*.md")):
        if "__aggregation__" in path.name:
            continue
        content = path.read_text(encoding="utf-8")
        header_match = re.search(r"##\s+(Dr\.\s+\S+\s+\S+),", content)
        if header_match:
            expert_name = header_match.group(1).strip()
        else:
            stem = path.stem.replace(f"{session_id}_research_", "")
            expert_name = stem.replace("_", " ").title()
        summaries[expert_name] = content
    return summaries


def _parse_transcript(transcript_path: Path, expert_names: set[str]) -> list[TranscriptEntry]:
    text = transcript_path.read_text(encoding="utf-8")

    pattern = re.compile(
        r"\[Turn\s+(\d+)\]\s+\*\*(.+?)\*\*\s+\((.+?)\):\s*(.*?)(?=\[Turn\s+\d+\]|\[RAPPORTEUR\]|\[DISCUSSANT\]|\Z)",
        re.DOTALL,
    )
    entries: list[TranscriptEntry] = []
    for match in pattern.finditer(text):
        turn_num = int(match.group(1))
        agent_name = match.group(2).strip()
        discipline = match.group(3).strip()
        speech = match.group(4).strip()

        if agent_name in expert_names or any(
            n in agent_name for n in expert_names
        ):
            entries.append(
                TranscriptEntry(
                    turn=turn_num,
                    agent_name=agent_name,
                    discipline=discipline,
                    speech=speech,
                    phase="debate",
                )
            )
    return entries


def _parse_scorecard(scorecard_path: Path) -> list[EvidenceEntry]:
    """Parse a JSON evidence scorecard file into EvidenceEntry objects."""
    import json

    text = scorecard_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        entries: list[EvidenceEntry] = []
        for item in data:
            entries.append(
                EvidenceEntry(
                    claim=item.get("claim", ""),
                    agent_name=item.get("agent_name", ""),
                    claim_type=item.get("claim_type", "empirical"),
                    source_url=item.get("source_url", ""),
                    verification_status=item.get("verification_status", ""),
                    source_quote=item.get("source_quote", ""),
                    relevance_note=item.get("relevance_note"),
                )
            )
        return entries
    except Exception:
        return []


def load_session_from_outputs(
    session_id: str,
    outputs_dir: str = "outputs",
    query: str | None = None,
) -> CouncilState:
    """
    Reconstruct a CouncilState from saved output files.

    Reads:
      - {session_id}_panel.json
      - {session_id}_research_dr_*.md (one per expert)
      - {session_id}_transcript_r0.md
      - {session_id}_scorecard_r0.json

    Sets status to "auditing" so it can immediately enter Phase D.
    """
    out = Path(outputs_dir)

    panel_file = out / f"{session_id}_panel.json"
    if not panel_file.exists():
        raise FileNotFoundError(f"Panel file not found: {panel_file}")

    experts = _parse_experts_from_panel(panel_file)
    expert_names = {e.name for e in experts}

    research_summaries = _parse_research_summaries(out, session_id)

    transcript_file = out / f"{session_id}_transcript_r0.md"
    transcript: list[TranscriptEntry] = []
    if transcript_file.exists():
        transcript = _parse_transcript(transcript_file, expert_names)

    scorecard_file = out / f"{session_id}_scorecard_r0.json"
    evidence_scorecard: list[EvidenceEntry] = []
    if scorecard_file.exists():
        evidence_scorecard = _parse_scorecard(scorecard_file)

    resolved_query = query or "(resumed from outputs)"
    state = CouncilState(
        session_id=session_id,
        query=resolved_query,
        experts=experts,
        max_experts=len(experts),
        research_summaries=research_summaries,
        transcript=transcript,
        evidence_scorecard=evidence_scorecard,
        audit_round=0,
        status="auditing",
    )
    return state


def resume_and_save(
    session_id: str,
    outputs_dir: str = "outputs",
    query: str | None = None,
) -> CouncilState:
    """
    Load state from outputs and persist it to the SQLite DB.
    After calling this, you can use --session-id to resume from the CLI.
    """
    from council.db import save_state

    state = load_session_from_outputs(session_id, outputs_dir, query)
    save_state(state)
    return state
