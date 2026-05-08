"""
council/workspace/server.py

FastAPI server for the workspace system. Thin wrapper around Phase 2 agent
functions — each endpoint calls one module, no pipeline orchestration.

Usage:
  uv run python -m council.workspace.server
  uv run python -m council.workspace.server --port 8080
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from council.workspace.agents import (
    add_source_to_expert,
    expert_respond,
    expert_research,
    fact_check_source,
    form_opinion,
    moderator_propose_panel,
    rapporteur_synthesize,
    upload_file_to_expert,
)
from council.workspace.db import delete, list_all, load, save
from council.workspace.sse import (
    sse_event,
    stream_expert_response,
    stream_rapporteur_synthesis,
)
from council.workspace.state import Message, Panel, Symposium, WorkspaceState

app = FastAPI(title="COUNCIL Workspace API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)


def _load_or_404(ws_id: str) -> WorkspaceState:
    try:
        return load(ws_id)
    except ValueError:
        raise HTTPException(404, f"Workspace '{ws_id}' not found")


# ── Request models ───────────────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    query: str = ""


class CreatePanelRequest(BaseModel):
    query: str = ""
    function_type: str = ""
    function_detail: str = ""
    max_experts: int = 5


class UpdatePanelRequest(BaseModel):
    name: str | None = None
    query: str | None = None
    function_type: str | None = None
    function_detail: str | None = None


class UpdateExpertRequest(BaseModel):
    name: str | None = None
    discipline: str | None = None
    bias: str | None = None
    persona_prompt: str | None = None
    photo_url: str | None = None


class AddSourceRequest(BaseModel):
    url: str = ""
    title: str = ""
    snippet: str = ""
    full_text: str = ""
    enrich: bool = True


class MessageRequest(BaseModel):
    message: str


class ResearchRequest(BaseModel):
    research_goal: str = ""


class CreateSymposiumRequest(BaseModel):
    title: str = ""
    format: str = "structured"  # structured | free | one_on_one
    panel_id: str = ""
    expert_ids: list[str] | None = None


class SymposiumMessageRequest(BaseModel):
    message: str = ""
    expert_id: str = ""  # which expert should respond


# ── Workspace CRUD ───────────────────────────────────────────────────────────

@app.post("/api/workspace")
def create_workspace(req: CreateWorkspaceRequest):
    ws = WorkspaceState(query=req.query)
    save(ws)
    return {"id": ws.id, "query": ws.query}


@app.get("/api/workspace")
def list_workspaces():
    return list_all()


@app.get("/api/workspace/{ws_id}")
def get_workspace(ws_id: str):
    ws = _load_or_404(ws_id)

    return {
        "id": ws.id,
        "query": ws.query,
        "panels": [
            {
                "id": p.id,
                "name": p.name,
                "query": p.query,
                "function_type": p.function_type,
                "experts": [
                    {
                        "id": e.id,
                        "name": e.name,
                        "discipline": e.discipline,
                        "bias": e.bias,
                        "persona_prompt": e.persona_prompt,
                        "photo_url": e.photo_url,
                        "source_count": len(e.knowledge_pool.sources),
                        "opinion_count": len(e.knowledge_pool.opinions),
                    }
                    for e in p.experts
                ],
            }
            for p in ws.panels
        ],
        "symposia": [
            {
                "id": s.id,
                "title": s.title,
                "format": s.format,
                "participant_ids": s.participant_ids,
                "message_count": len(s.message_ids),
                "has_synthesis": bool(s.synthesis),
            }
            for s in ws.symposia
        ],
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


@app.delete("/api/workspace/{ws_id}")
def delete_workspace(ws_id: str):
    _load_or_404(ws_id)  # ensure exists
    delete(ws_id)
    return {"deleted": ws_id}


# ── Panels ───────────────────────────────────────────────────────────────────

@app.post("/api/workspace/{ws_id}/panels")
def create_panel(ws_id: str, req: CreatePanelRequest):
    ws = _load_or_404(ws_id)

    if req.query:
        experts = moderator_propose_panel(
            query=req.query,
            function_type=req.function_type,
            max_experts=req.max_experts,
        )
    else:
        experts = moderator_propose_panel(
            function_type=req.function_type or "balanced_overview",
            function_detail=req.function_detail,
            max_experts=req.max_experts,
        )

    if not experts:
        raise HTTPException(500, "Moderator failed to propose experts")

    panel = Panel(
        name=req.query[:60] if req.query else req.function_type,
        query=req.query,
        function_type=req.function_type,
        function_detail=req.function_detail,
        experts=experts,
    )
    ws.panels.append(panel)
    save(ws)

    return {"panel_id": panel.id, "experts": [{"id": e.id, "name": e.name, "discipline": e.discipline} for e in experts]}


@app.put("/api/workspace/{ws_id}/panels/{panel_id}")
def update_panel(ws_id: str, panel_id: str, req: UpdatePanelRequest):
    ws = _load_or_404(ws_id)
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, "Panel not found")

    if req.name is not None:
        panel.name = req.name
    if req.query is not None:
        panel.query = req.query
    if req.function_type is not None:
        panel.function_type = req.function_type
    if req.function_detail is not None:
        panel.function_detail = req.function_detail
    save(ws)
    return {"ok": True}


# ── Experts ──────────────────────────────────────────────────────────────────

@app.put("/api/workspace/{ws_id}/experts/{expert_id}")
def update_expert(ws_id: str, expert_id: str, req: UpdateExpertRequest):
    ws = _load_or_404(ws_id)
    expert = ws.get_expert(expert_id)
    if not expert:
        raise HTTPException(404, "Expert not found")

    for field in ("name", "discipline", "bias", "persona_prompt", "photo_url"):
        val = getattr(req, field)
        if val is not None:
            setattr(expert, field, val)
    save(ws)
    return {"ok": True}


@app.get("/api/workspace/{ws_id}/experts/{expert_id}/pool")
def get_expert_pool(ws_id: str, expert_id: str):
    ws = _load_or_404(ws_id)
    expert = ws.get_expert(expert_id)
    if not expert:
        raise HTTPException(404, "Expert not found")

    return {
        "sources": [
            {
                "id": s.id,
                "type": s.type,
                "url": s.url,
                "title": s.title,
                "snippet": s.snippet,
                "full_text_preview": s.full_text[:500] if s.full_text else "",
                "verification_status": s.verification_status,
                "verification_note": s.verification_note,
                "added_by": s.added_by,
            }
            for s in expert.knowledge_pool.sources
        ],
        "opinions": [
            {"id": o.id, "text": o.text, "source_ids": o.source_ids}
            for o in expert.knowledge_pool.opinions
        ],
    }


@app.post("/api/workspace/{ws_id}/experts/{expert_id}/sources")
def add_source(ws_id: str, expert_id: str, req: AddSourceRequest):
    ws = _load_or_404(ws_id)
    expert = ws.get_expert(expert_id)
    if not expert:
        raise HTTPException(404, "Expert not found")

    src = add_source_to_expert(
        expert=expert,
        workspace_id=ws_id,
        url=req.url,
        title=req.title,
        snippet=req.snippet,
        full_text=req.full_text,
        enrich=req.enrich,
    )
    save(ws)
    return {"source_id": src.id, "title": src.title, "has_full_text": bool(src.full_text)}


@app.post("/api/workspace/{ws_id}/experts/{expert_id}/upload")
async def upload_file(ws_id: str, expert_id: str):
    """File upload handled via multipart form. Use from fastapi import UploadFile, File."""
    raise HTTPException(501, "Use the /api/workspace/{ws_id}/experts/{expert_id}/upload/form endpoint with multipart")


# ── Expert messaging (SSE) ───────────────────────────────────────────────────

@app.post("/api/workspace/{ws_id}/experts/{expert_id}/message")
async def expert_message(ws_id: str, expert_id: str, req: MessageRequest):
    ws = _load_or_404(ws_id)
    expert = ws.get_expert(expert_id)
    if not expert:
        raise HTTPException(404, "Expert not found")

    async def event_stream():
        # Run the expert in a thread
        response = await asyncio.to_thread(
            expert_respond,
            expert=expert,
            workspace_id=ws_id,
            query=ws.query or "the research context",
            message=req.message,
        )
        ws.add_message(
            role="agent",
            agent_id=expert.id,
            agent_name=expert.name,
            content=response,
        )
        save(ws)

        async for event_type, data in stream_expert_response(
            expert_name=expert.name,
            discipline=expert.discipline,
            content=response,
        ):
            yield sse_event(event_type, data)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/workspace/{ws_id}/experts/{expert_id}/research")
async def expert_research_endpoint(ws_id: str, expert_id: str, req: ResearchRequest):
    ws = _load_or_404(ws_id)
    expert = ws.get_expert(expert_id)
    if not expert:
        raise HTTPException(404, "Expert not found")

    async def event_stream():
        yield sse_event("typing", {"name": expert.name, "discipline": expert.discipline, "type": "research"})
        await asyncio.sleep(0.5)

        sources = await asyncio.to_thread(
            expert_research,
            expert=expert,
            query=ws.query or req.research_goal,
            research_goal=req.research_goal,
        )
        for src in sources:
            await asyncio.to_thread(fact_check_source, src)
            expert.knowledge_pool.sources.append(src)

        save(ws)
        yield sse_event("research_complete", {
            "expert_id": expert_id,
            "sources_found": len(sources),
            "verified": sum(1 for s in sources if s.verification_status == "verified"),
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/workspace/{ws_id}/experts/{expert_id}/opinion")
async def expert_form_opinion(ws_id: str, expert_id: str, req: MessageRequest):
    ws = _load_or_404(ws_id)
    expert = ws.get_expert(expert_id)
    if not expert:
        raise HTTPException(404, "Expert not found")

    async def event_stream():
        yield sse_event("typing", {"name": expert.name, "discipline": expert.discipline, "type": "opinion"})
        await asyncio.sleep(0.5)

        opinion = await asyncio.to_thread(
            form_opinion,
            expert=expert,
            workspace_id=ws_id,
            query=req.message or ws.query,
        )
        save(ws)

        if opinion:
            yield sse_event("opinion_ready", {
                "expert_id": expert_id,
                "opinion": opinion.text,
                "source_ids": opinion.source_ids,
            })
        else:
            yield sse_event("error", {"message": "Could not form opinion — no verified sources in pool"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Symposia ─────────────────────────────────────────────────────────────────

@app.post("/api/workspace/{ws_id}/symposia")
def create_symposium(ws_id: str, req: CreateSymposiumRequest):
    ws = _load_or_404(ws_id)

    if req.expert_ids:
        participant_ids = req.expert_ids
    elif req.panel_id:
        panel = ws.get_panel(req.panel_id)
        if not panel:
            raise HTTPException(404, "Panel not found")
        participant_ids = [e.id for e in panel.experts]
    else:
        raise HTTPException(400, "Provide panel_id or expert_ids")

    sym = Symposium(
        title=req.title or "Symposium",
        format=req.format,
        participant_ids=participant_ids,
    )
    ws.symposia.append(sym)
    save(ws)

    return {"symposium_id": sym.id, "participants": participant_ids}


@app.post("/api/workspace/{ws_id}/symposia/{sym_id}/round")
async def symposium_round(ws_id: str, sym_id: str):
    """Run one structured debate round — each expert speaks in turn."""
    ws = _load_or_404(ws_id)
    sym = ws.get_symposium(sym_id)
    if not sym:
        raise HTTPException(404, "Symposium not found")

    participants = [ws.get_expert(eid) for eid in sym.participant_ids]
    participants = [e for e in participants if e is not None]
    if not participants:
        raise HTTPException(400, "No valid participants")

    async def event_stream():
        transcript_lines: list[str] = []
        query = ws.query or sym.title

        for i, expert in enumerate(participants):
            turn = i + 1

            # Typing
            yield sse_event("typing", {
                "name": expert.name,
                "discipline": expert.discipline,
                "type": "expert",
            })
            await asyncio.sleep(0.8)

            context = "\n".join(transcript_lines) if transcript_lines else "(You are the first speaker.)"
            prompt = (
                f"=== DEBATE TRANSCRIPT SO FAR ===\n{context}\n=== END TRANSCRIPT ===\n\n"
                f"Present your evidence-based position on: {query}\n\n"
                f"As turn {turn}, respond to previous speakers and present your unique "
                f"disciplinary perspective grounded in your knowledge pool."
            )

            speech = await asyncio.to_thread(
                expert_respond,
                expert=expert,
                workspace_id=ws_id,
                query=query,
                message=prompt,
            )
            transcript_lines.append(f"[Turn {turn}] **{expert.name}** ({expert.discipline}):\n{speech}")
            ws.add_message(
                role="agent",
                agent_id=expert.id,
                agent_name=expert.name,
                symposium_id=sym_id,
                content=speech,
                turn=turn,
            )

            yield sse_event("message", {
                "name": expert.name,
                "discipline": expert.discipline,
                "content": speech,
                "turn": turn,
            })
            await asyncio.sleep(0.3)

        save(ws)
        yield sse_event("round_complete", {"symposium_id": sym_id, "turns": len(participants)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/workspace/{ws_id}/symposia/{sym_id}/synthesize")
async def symposium_synthesize(ws_id: str, sym_id: str):
    ws = _load_or_404(ws_id)
    sym = ws.get_symposium(sym_id)
    if not sym:
        raise HTTPException(404, "Symposium not found")

    msgs = ws.get_messages_for_symposium(sym_id)
    if not msgs:
        raise HTTPException(400, "Symposium has no messages")

    async def event_stream():
        yield sse_event("typing", {"name": "Rapporteur", "discipline": "Synthesis", "type": "rapporteur"})
        await asyncio.sleep(1.0)

        transcript = "\n\n".join(
            f"[Turn {m.turn}] **{m.agent_name}**:\n{m.content}" if m.turn
            else f"**{m.agent_name}**:\n{m.content}"
            for m in msgs
            if m.role == "agent"
        )
        scorecard = str(sym.scorecard) if sym.scorecard else "[]"

        synthesis = await asyncio.to_thread(
            rapporteur_synthesize,
            transcript=transcript,
            scorecard=scorecard,
            query=ws.query,
        )
        sym.synthesis = synthesis
        save(ws)

        async for event_type, data in stream_rapporteur_synthesis(synthesis):
            yield sse_event(event_type, data)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Export ───────────────────────────────────────────────────────────────────

@app.post("/api/workspace/{ws_id}/export")
def export_workspace(ws_id: str):
    ws = _load_or_404(ws_id)

    export_data = {
        "workspace_id": ws.id,
        "query": ws.query,
        "panels": [p.model_dump() for p in ws.panels],
        "symposia": [s.model_dump() for s in ws.symposia],
        "messages": [m.model_dump() for m in ws.messages],
    }

    filename = f"{ws.id}_export.json"
    filepath = OUTPUTS_DIR / filename
    filepath.write_text(json.dumps(export_data, indent=2, ensure_ascii=False, default=str))

    return {"file": filename, "path": str(filepath)}


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "system": "workspace"}


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="COUNCIL Workspace Server")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
