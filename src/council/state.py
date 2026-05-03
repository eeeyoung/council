"""
council/state.py

CouncilState — the single source of truth for the entire symposium lifecycle.
Serializable via Pydantic so it can be persisted to SQLite (Stage 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ExpertDefinition(BaseModel):
    """One expert persona as produced by the ModeratorAgent."""

    name: str = Field(..., description="Plausible academic name, e.g. 'Dr. Lena Hartmann'")
    discipline: str = Field(..., description="Primary field, e.g. 'Theoretical Astrophysics'")
    bias: str = Field(..., description="Known intellectual leaning or methodological preference")
    persona_prompt: str = Field(
        ..., description="2-3 sentence vivid character description used as agent backstory"
    )

    def __str__(self) -> str:
        return f"{self.name} ({self.discipline}) — Bias: {self.bias}"


class TranscriptEntry(BaseModel):
    """One turn in the debate transcript."""

    turn: int
    agent_name: str
    discipline: str
    speech: str
    phase: Literal["research", "debate", "audit"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceEntry(BaseModel):
    """One claim-to-citation mapping produced by the RecorderAgent."""

    claim: str
    agent_name: str
    source_url: str  # "UNCITED" if no match found
    relevance_note: Optional[str] = None


class AuditResult(BaseModel):
    """Host B's verdict on a synthesis."""

    round: int
    approved: bool
    verdict: Literal["APPROVED", "REJECTED"]
    issues: list[str] = Field(default_factory=list)
    conflict_mandate: Optional[str] = None  # Injected into next debate round if rejected


class CouncilState(BaseModel):
    """
    The complete state of a COUNCIL symposium session.
    Persisted to SQLite after every phase (Stage 4).
    """

    # --- Session identity ---
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    query: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # --- Panel (Phase A) ---
    experts: list[ExpertDefinition] = Field(default_factory=list)
    max_experts: int = 6

    # --- Research (Phase B) ---
    research_summaries: dict[str, str] = Field(
        default_factory=dict,
        description="Keyed by expert name → their research summary text",
    )

    # --- Debate (Phase C) ---
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    evidence_scorecard: list[EvidenceEntry] = Field(default_factory=list)

    # --- Audit (Phase D) ---
    audit_round: int = 0
    max_audit_rounds: int = 3
    audit_history: list[AuditResult] = Field(default_factory=list)
    synthesis: Optional[str] = None
    conflict_mandate: Optional[str] = None  # Active mandate for the current debate round

    # --- Final output (Phase E) ---
    dossier_path: Optional[str] = None

    # --- Lifecycle ---
    status: Literal[
        "curating", "researching", "debating", "auditing", "compiling", "done"
    ] = "curating"

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #

    @property
    def transcript_text(self) -> str:
        """Render transcript as a readable string for prompt injection."""
        if not self.transcript:
            return "(No contributions yet — you are the first speaker.)"
        lines: list[str] = []
        for entry in self.transcript:
            lines.append(f"[Turn {entry.turn}] {entry.agent_name} ({entry.discipline}):")
            lines.append(entry.speech)
            lines.append("")
        return "\n".join(lines)

    @property
    def evidence_scorecard_text(self) -> str:
        """Render evidence scorecard as readable text for prompt injection."""
        if not self.evidence_scorecard:
            return "(Evidence scorecard not yet compiled.)"
        lines: list[str] = []
        for e in self.evidence_scorecard:
            cited = e.source_url if e.source_url != "UNCITED" else "⚠ UNCITED"
            lines.append(f"• [{e.agent_name}] \"{e.claim}\" → {cited}")
        return "\n".join(lines)

    @property
    def next_turn_number(self) -> int:
        return len(self.transcript) + 1

    def add_transcript_entry(
        self, agent_name: str, discipline: str, speech: str, phase: str = "debate"
    ) -> None:
        self.transcript.append(
            TranscriptEntry(
                turn=self.next_turn_number,
                agent_name=agent_name,
                discipline=discipline,
                speech=speech,
                phase=phase,  # type: ignore[arg-type]
            )
        )

    def apply_audit_result(self, result: AuditResult) -> None:
        self.audit_history.append(result)
        self.audit_round += 1
        if not result.approved:
            self.conflict_mandate = result.conflict_mandate
            self.status = "debating"
        else:
            self.conflict_mandate = None
            self.status = "compiling"
