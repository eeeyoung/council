"""
council/workspace/state.py

Session — the top-level entity. A session contains multiple Panels (each with
their own experts and research domain), symposia, and a unified message log.
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
    origin: str = "curated"      # "curated" (user-added) | "discovered" (expert-found)
    source_type: str = "url"     # "url" | "pdf" | "doc" | "txt" | "other"
    type: str = "collected"      # lifecycle: uploaded | collected | verified | rejected
    url: str = ""
    title: str = ""
    snippet: str = ""
    full_text: str = ""          # populated for uploaded files OR trafilatura-extracted markdown
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


# ── Panel ────────────────────────────────────────────────────────────────────

class Panel(BaseModel):
    """A named panel of experts assembled for a research domain."""
    id: str = Field(default_factory=_new_id)
    name: str = ""
    query: str = ""
    function_type: str = ""
    function_detail: str = ""
    experts: list["Expert"] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


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

class ArchiveRound(BaseModel):
    """One completed debate round saved to the archive."""
    round_number: int = 1
    message_ids: list[str] = Field(default_factory=list)
    synthesis: str = ""
    created_at: datetime = Field(default_factory=_now)


class Symposium(BaseModel):
    """A convened debate between experts."""
    id: str = Field(default_factory=_new_id)
    title: str = ""
    format: str = "structured"     # "structured" | "free" | "one_on_one"
    participant_ids: list[str] = Field(default_factory=list)
    message_ids: list[str] = Field(default_factory=list)
    scorecard: list[dict] = Field(default_factory=list)
    synthesis: str = ""
    archive: list[ArchiveRound] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    @property
    def has_synthesis(self) -> bool:
        return bool(self.synthesis)


# ── Session (top-level entity) ───────────────────────────────────────────────

class Session(BaseModel):
    """A COUNCIL session — multiple panels, their symposia, and messages."""

    id: str = "default"
    created_at: datetime = Field(default_factory=_now)

    panels: list[Panel] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    symposia: list[Symposium] = Field(default_factory=list)

    # ── Convenience ──────────────────────────────────────────────────────────

    def get_panel(self, panel_id: str) -> Optional[Panel]:
        for p in self.panels:
            if p.id == panel_id:
                return p
        return None

    def get_expert(self, expert_id: str) -> Optional[Expert]:
        """Find an expert across all panels by ID."""
        for p in self.panels:
            for e in p.experts:
                if e.id == expert_id:
                    return e
        return None

    def get_expert_with_panel(self, expert_id: str) -> tuple[str, Expert] | None:
        """Find an expert across all panels. Returns (panel_id, Expert) or None."""
        for p in self.panels:
            for e in p.experts:
                if e.id == expert_id:
                    return (p.id, e)
        return None

    def get_expert_by_name(self, name: str) -> Optional[Expert]:
        """Find an expert across all panels by name."""
        for p in self.panels:
            for e in p.experts:
                if e.name == name:
                    return e
        return None

    def get_experts_flat(self) -> list[dict]:
        """Return all experts across all panels with their panel_id."""
        result = []
        for p in self.panels:
            for e in p.experts:
                result.append({"panel_id": p.id, "expert": e})
        return result

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

    # ── Migration ────────────────────────────────────────────────────────────

    @classmethod
    def migrate_from_v1(cls, data: dict) -> "Session":
        """Convert old flat-expert Session JSON to new panel-based Session."""
        old_experts = data.get("experts", [])
        if old_experts:
            panel = Panel(
                name=data.get("name") or data.get("query", "")[:60],
                query=data.get("query", ""),
                function_type=data.get("function_type", ""),
                function_detail=data.get("function_detail", ""),
                experts=[Expert(**e) if isinstance(e, dict) else e for e in old_experts],
            )
            panels = [panel]
        else:
            panels = []

        return cls(
            id="default",
            panels=panels,
            messages=[Message(**m) if isinstance(m, dict) else m for m in data.get("messages", [])],
            symposia=[Symposium(**s) if isinstance(s, dict) else s for s in data.get("symposia", [])],
        )
