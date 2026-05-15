"""
council/workspace/export.py

Compile session data into deliverable documents: dossier, decision memo,
evidence scorecard, transcript.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from council.workspace.state import Session

OUTPUTS_DIR = Path("outputs")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write(filename: str, content: str) -> Path:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    path = OUTPUTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return path


def _expert_section(expert) -> str:
    """Render one expert's profile + pool summary."""
    lines = [f"### {expert.name} — {expert.discipline}", ""]
    if expert.bias:
        lines.append(f"*Intellectual leaning:* {expert.bias}")
    if expert.persona_prompt:
        lines.append(f"*Persona:* {expert.persona_prompt}")
    lines.append("")

    pool = expert.knowledge_pool
    if pool.sources:
        lines.append(f"**Knowledge Pool** ({len(pool.sources)} sources):")
        for s in pool.sources:
            status = f"[{s.verification_status}]" if s.verification_status else "[pending]"
            lines.append(f"- {status} {s.title or s.url}")
            if s.snippet:
                lines.append(f"  > {s.snippet[:200]}")
        lines.append("")

    if pool.opinions:
        lines.append(f"**Opinions** ({len(pool.opinions)}):")
        for o in pool.opinions:
            lines.append(f"- {o.text}")
        lines.append("")

    return "\n".join(lines)


def _transcript_section(session: Session) -> str:
    """Render the full message log as a transcript."""
    if not session.messages:
        return "*No messages recorded.*"

    lines: list[str] = []
    for m in session.messages:
        role_label = {"user": "You", "agent": m.agent_name, "system": "System"}.get(m.role, m.role)
        turn = f" [Turn {m.turn}]" if m.turn else ""
        lines.append(f"**{role_label}**{turn}:")
        lines.append(m.content)
        lines.append("")
    return "\n".join(lines)


def _symposium_section(sym) -> str:
    """Render one symposium with synthesis."""
    lines = [f"## Symposium: {sym.title or sym.id}", ""]
    lines.append(f"Format: {sym.format} | Participants: {len(sym.participant_ids)}")
    lines.append("")

    if sym.synthesis:
        lines.append("### Synthesis")
        lines.append(sym.synthesis)
        lines.append("")

    if sym.scorecard:
        lines.append("### Evidence Scorecard")
        for entry in sym.scorecard:
            status = entry.get("verification_status", "")
            agent = entry.get("agent_name", "")
            claim = entry.get("claim", "")
            url = entry.get("source_url", "")
            lines.append(f"- [{status}] **{agent}**: \"{claim}\" → {url}")
        lines.append("")

    return "\n".join(lines)


# ── Export formats ───────────────────────────────────────────────────────────

def export_dossier(session: Session) -> Path:
    """Compile a full research dossier."""
    parts: list[str] = []

    parts.append(f"# COUNCIL Dossier: {(session.panels[0].query if session.panels else session.id) or session.id}")
    parts.append(f"*Compiled {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    parts.append("")

    # Abstract
    parts.append("## Abstract")
    parts.append(f"Research question: **{(session.panels[0].query if session.panels else None) or '(not specified)'}**")
    parts.append(f"Experts convened: {len([e for p in session.panels for e in p.experts])}")
    parts.append(f"Symposia held: {len(session.symposia)}")
    parts.append(f"Total messages: {len(session.messages)}")
    parts.append("")

    # Expert Panel
    parts.append("## Expert Panel")
    for e in [e for p in session.panels for e in p.experts]:
        parts.append(_expert_section(e))

    # Symposia
    if session.symposia:
        parts.append("## Symposia & Syntheses")
        for sym in session.symposia:
            parts.append(_symposium_section(sym))

    # Transcript
    parts.append("## Full Transcript")
    parts.append(_transcript_section(session))

    # Bibliography
    parts.append("## Bibliography")
    all_sources: list[tuple[str, str, str]] = []
    for e in [e for p in session.panels for e in p.experts]:
        for s in e.knowledge_pool.sources:
            all_sources.append((s.url, s.title, s.verification_status))
    if all_sources:
        for url, title, status in all_sources:
            status_mark = {"verified": "✓", "misattributed": "⚠", "unverifiable": "?"}.get(status, "")
            parts.append(f"- {status_mark} [{title or url}]({url})")
    else:
        parts.append("*No sources collected.*")

    content = "\n\n".join(parts)
    filename = f"dossier_{session.id}.md"
    return _write(filename, content)


def export_decision_memo(session: Session) -> Path:
    """Compile a decision memo — scored recommendation from the synthesis."""
    parts: list[str] = []

    parts.append(f"# Decision Memo: {(session.panels[0].query if session.panels else session.id) or session.id}")
    parts.append(f"*{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    parts.append("")

    parts.append("## Recommendation")
    # Extract from last synthesis if available
    synthesis = None
    for sym in reversed(session.symposia):
        if sym.synthesis:
            synthesis = sym.synthesis
            break

    if synthesis:
        # Extract Unified Hypothesis section
        import re
        uh_match = re.search(r"## Unified Hypothesis\n(.*?)(?=\n##|\Z)", synthesis, re.DOTALL)
        if uh_match:
            parts.append(uh_match.group(1).strip())
        else:
            parts.append(synthesis[:500])
    else:
        parts.append("*No synthesis available. Convene a symposium first.*")

    parts.append("")
    parts.append("## Confidence Assessment")

    if synthesis:
        # Count consensus strengths
        strong = synthesis.count("**Strength:** Strong")
        moderate = synthesis.count("**Strength:** Moderate")
        weak = synthesis.count("**Strength:** Weak")
        parts.append(f"- Strong consensus points: {strong}")
        parts.append(f"- Moderate consensus points: {moderate}")
        parts.append(f"- Weak consensus points: {weak}")
        parts.append(f"- Overall confidence: {'High' if strong >= moderate + weak else 'Moderate' if strong + moderate > weak else 'Low'}")
    parts.append("")

    parts.append("## Dissenting Views")
    if synthesis:
        dl_match = re.search(r"## Disagreement Landscape\n(.*?)(?=\n##|\Z)", synthesis, re.DOTALL)
        if dl_match:
            parts.append(dl_match.group(1).strip())
    parts.append("")

    parts.append("## Evidence Summary")
    verified_count = 0
    total_count = 0
    for e in [e for p in session.panels for e in p.experts]:
        for s in e.knowledge_pool.sources:
            total_count += 1
            if s.verification_status == "verified":
                verified_count += 1
    parts.append(f"- Total sources: {total_count}")
    parts.append(f"- Verified: {verified_count}")
    parts.append(f"- Unverified/disputed: {total_count - verified_count}")
    parts.append("")

    parts.append("## Panel")
    for e in [e for p in session.panels for e in p.experts]:
        parts.append(f"- **{e.name}** ({e.discipline}): {e.bias}")

    content = "\n\n".join(parts)
    filename = f"{session.id}_memo.md"
    return _write(filename, content)


def export_scorecard(session: Session) -> Path:
    """Export just the evidence scorecard as structured markdown."""
    lines = [f"# Evidence Scorecard: {(session.panels[0].query if session.panels else "") or session.id}", ""]

    for e in [e for p in session.panels for e in p.experts]:
        pool = e.knowledge_pool
        if not pool.sources:
            continue
        lines.append(f"## {e.name}")
        for s in pool.sources:
            status_icon = {"verified": "✓", "misattributed": "⚠", "unverifiable": "?"}.get(
                s.verification_status, "○")
            lines.append(f"- {status_icon} **{s.title or 'Untitled'}**")
            if s.url:
                lines.append(f"  [{s.url}]({s.url})")
            if s.snippet:
                lines.append(f"  > {s.snippet[:200]}")
            if s.verification_note:
                lines.append(f"  Note: {s.verification_note}")
        lines.append("")

    content = "\n".join(lines)
    filename = f"{session.id}_scorecard_export.md"
    return _write(filename, content)


def export_transcript(session: Session) -> Path:
    """Export just the transcript."""
    lines = [f"# Transcript: {(session.panels[0].query if session.panels else "") or session.id}", "",
             _transcript_section(session)]
    filename = f"{session.id}_transcript_export.md"
    return _write(filename, "\n".join(lines))


# ── Unified export ───────────────────────────────────────────────────────────

def export_all(session: Session, formats: list[str] | None = None) -> dict[str, str]:
    """Export all or specified formats. Returns {format: filename}."""
    if formats is None:
        formats = ["dossier", "memo", "scorecard", "transcript"]

    exporters = {
        "dossier": export_dossier,
        "memo": export_decision_memo,
        "scorecard": export_scorecard,
        "transcript": export_transcript,
    }

    result = {}
    for fmt in formats:
        if fmt in exporters:
            path = exporters[fmt](session)
            result[fmt] = path.name
    return result
