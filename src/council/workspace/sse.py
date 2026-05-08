"""
council/workspace/sse.py

SSE event emitters for workspace operations. Same event shapes as the
current pipeline system so the GUI can reuse listeners.

Events:
  typing        — {"name": "...", "discipline": "...", "type": "expert"|"rapporteur"}
  message       — {"name": "...", "discipline": "...", "content": "...", "turn": ...}
  scorecard_ready — {"symposium_id": "..."}
  synthesis_ready — {"symposium_id": "..."}
  error         — {"message": "..."}
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator


async def stream_expert_response(
    expert_name: str,
    discipline: str,
    content: str,
    turn: int | None = None,
    typing_delay: float = 0.8,
) -> AsyncGenerator[tuple[str, dict], None]:
    """Stream an expert's response: typing indicator → full message."""
    # Typing indicator
    yield "typing", {
        "name": expert_name,
        "discipline": discipline,
        "type": "expert",
    }
    await asyncio.sleep(typing_delay)

    # Full message
    yield "message", {
        "name": expert_name,
        "discipline": discipline,
        "content": content,
        "turn": turn,
    }


async def stream_rapporteur_synthesis(
    content: str,
    typing_delay: float = 1.0,
) -> AsyncGenerator[tuple[str, dict], None]:
    """Stream the rapporteur writing the synthesis."""
    yield "typing", {
        "name": "Rapporteur",
        "discipline": "Synthesis",
        "type": "rapporteur",
    }
    await asyncio.sleep(typing_delay)

    yield "message", {
        "name": "Rapporteur",
        "discipline": "Synthesis",
        "content": content,
    }


def sse_event(event_type: str, data: dict) -> str:
    """Format an SSE event string."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
