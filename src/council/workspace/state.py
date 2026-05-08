"""
council/workspace/state.py

Session — the top-level entity. A session is a panel of experts assembled
for a research domain, with symposia and a unified message log.

No nesting — sessions are the highest level. Each has experts, symposia, messages.
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
    source_ids: list[str] = Field(default_factory=list)
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
    photo_url: str = ""
    knowledge_pool: KnowledgePool = Field(default_factory=KnowledgePool)


# ── Message ──────────────────────────────────────────────────────────────────

class Message(BaseModel):
    """One entry in the conversation log."""
    id: str = Field(default_factory=_new_id)
    role: str                      # "user" | "agent" | "system"
    agent_id: str = ""
    agent_name: str = ""
    symposium_id: str = ""
    content: str
    mentioned_agent_ids: list[str] = Field(default_factory=list)
    turn: Optional[int] = None
    timestamp: datetime = Field(default_factory=_now)


# ── Symposium ─────────────────────────────────────────────────────────────────

class Symposium(BaseModel):
    """A convened debate between experts."""
    id: str = Field(default_factory=_new_id)
    title: str = ""
    format: str = "structured"     # "structured" | "free" | "one_on_one"
    participant_ids: list[str] = Field(default_factory=list)
    message_ids: list[str] = Field(default_factory=list)
    scorecard: list[dict] = Field(default_factory=list)
    synthesis: str = ""
    created_at: datetime = Field(default_factory=_now)


# ── Session (top-level entity) ───────────────────────────────────────────────

class Session(BaseModel):
    """A COUNCIL session — one panel of experts, their symposia, and messages."""

    id: str = Field(default_factory=_new_id)
    name: str = ""
    query: str = ""
    function_type: str = ""
    function_detail: str = ""
    created_at: datetime = Field(default_factory=_now)

    experts: list[Expert] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    symposia: list[Symposium] = Field(default_factory=list)

    # ── Convenience ──────────────────────────────────────────────────────────

    def get_expert(self, expert_id: str) -> Optional[Expert]:
        for e in self.experts:
            if e.id == expert_id:
                return e
        return None

    def get_symposium(self, symposium_id: str) -> Optional[Symposium]:
        for s in self.symposia:
            if s.id == symposium_id:
                return s
        return None

    def get_messages_for_symposium(self, symposium_id: str) -> list[Message]:
        return [m for m in self.messages if m.symposium_id == symposium_id]

    def add_message(self, **kwargs) -> Message:
        msg = Message(**kwargs)
        self.messages.append(msg)
        return msg
