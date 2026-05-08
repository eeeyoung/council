"""
council/workspace/state.py

WorkspaceState — the single source of truth for the workspace system.

Flat, no nested state machines. Panels own experts. Experts own knowledge pools.
Symposia reference participants across panels. Messages are the unified log.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


# ── Helpers ──────────────────────────────────────────────────────────────────

def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Knowledge Pool ───────────────────────────────────────────────────────────

class PoolSource(BaseModel):
    """One source in an expert's knowledge pool."""
    id: str = Field(default_factory=_new_id)
    type: str = "collected"  # uploaded | collected | verified | rejected
    url: str = ""
    title: str = ""
    snippet: str = ""
    full_text: str = ""          # populated for uploaded files
    verification_status: str = ""  # verified | misattributed | unverifiable | "" (pending)
    verification_note: str = ""
    added_by: str = "user"       # "user" or agent name
    added_at: datetime = Field(default_factory=_now)


class Opinion(BaseModel):
    """An expert's evidence-grounded opinion. Must cite pool sources."""
    id: str = Field(default_factory=_new_id)
    text: str
    source_ids: list[str] = Field(default_factory=list)  # references PoolSource.id
    created_at: datetime = Field(default_factory=_now)


class KnowledgePool(BaseModel):
    """An expert's accumulated knowledge — sources + opinions."""
    sources: list[PoolSource] = Field(default_factory=list)
    opinions: list[Opinion] = Field(default_factory=list)


# ── Expert ───────────────────────────────────────────────────────────────────

class Expert(BaseModel):
    """One expert persona with their knowledge pool."""
    id: str = Field(default_factory=_new_id)
    name: str
    discipline: str
    bias: str = ""
    persona_prompt: str = ""
    photo_url: str = ""            # user-customizable avatar
    knowledge_pool: KnowledgePool = Field(default_factory=KnowledgePool)


# ── Panel ────────────────────────────────────────────────────────────────────

class Panel(BaseModel):
    """A named panel of experts assembled for a research domain."""
    id: str = Field(default_factory=_new_id)
    name: str = ""                  # user-editable label, e.g. "Climate Economics"
    query: str = ""                 # the research question (if question-oriented)
    function_type: str = ""         # e.g. "feasibility_assessment", "due_diligence"
    function_detail: str = ""       # user's description of what they need
    experts: list[Expert] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


# ── Message ──────────────────────────────────────────────────────────────────

class Message(BaseModel):
    """One entry in the workspace conversation log."""
    id: str = Field(default_factory=_new_id)
    role: str                      # "user" | "agent" | "system"
    agent_id: str = ""             # which expert spoke (empty for user/system)
    agent_name: str = ""           # denormalized for display
    symposium_id: str = ""         # which symposium this belongs to, if any
    content: str                   # markdown
    mentioned_agent_ids: list[str] = Field(default_factory=list)
    turn: Optional[int] = None     # only set for structured debate turns
    timestamp: datetime = Field(default_factory=_now)


# ── Symposium ─────────────────────────────────────────────────────────────────

class Symposium(BaseModel):
    """A convened debate between experts from one or more panels."""
    id: str = Field(default_factory=_new_id)
    title: str = ""
    format: str = "structured"     # "structured" | "free" | "one_on_one"
    participant_ids: list[str] = Field(default_factory=list)  # Expert.id refs
    message_ids: list[str] = Field(default_factory=list)      # Message.id refs
    scorecard: list[dict] = Field(default_factory=list)       # evidence entries
    synthesis: str = ""            # Rapporteur output, if requested
    created_at: datetime = Field(default_factory=_now)


# ── WorkspaceState ───────────────────────────────────────────────────────────

class WorkspaceState(BaseModel):
    """The complete state of a COUNCIL workspace."""

    id: str = Field(default_factory=_new_id)
    query: str = ""                # overall research context (optional)
    created_at: datetime = Field(default_factory=_now)

    panels: list[Panel] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    symposia: list[Symposium] = Field(default_factory=list)

    # ── Convenience ──────────────────────────────────────────────────────────

    def get_expert(self, expert_id: str) -> Optional[Expert]:
        for panel in self.panels:
            for expert in panel.experts:
                if expert.id == expert_id:
                    return expert
        return None

    def get_panel(self, panel_id: str) -> Optional[Panel]:
        for panel in self.panels:
            if panel.id == panel_id:
                return panel
        return None

    def get_symposium(self, symposium_id: str) -> Optional[Symposium]:
        for sym in self.symposia:
            if sym.id == symposium_id:
                return sym
        return None

    def get_messages_for_symposium(self, symposium_id: str) -> list[Message]:
        return [m for m in self.messages if m.symposium_id == symposium_id]

    def add_message(self, **kwargs) -> Message:
        msg = Message(**kwargs)
        self.messages.append(msg)
        return msg
