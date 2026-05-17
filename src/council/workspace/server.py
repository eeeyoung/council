"""
council/workspace/server.py

FastAPI server for the workspace system. Thin wrapper around agent functions —
each endpoint calls one module, no pipeline orchestration.

Single-session model: one implicit "default" session. No session CRUD.

Usage:
  uv run python -m council.workspace.server
  uv run python -m council.workspace.server --port 8080
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from council.tools.library_tool import (
    _fetch_and_extract,
    _fetch_and_extract_md,
    _verify_source,
)
from council.workspace.agents import (
    add_source_to_expert,
    expert_respond,
    expert_research,
    form_opinion,
    moderator_propose_panel,
    polish_query,
    propose_expert,
    rapporteur_synthesize,
    upload_file_to_expert,
)
from council.workspace.db import get_or_create_default, save
from council.workspace.sse import (
    sse_event,
    stream_expert_response,
    stream_rapporteur_synthesis,
)
from council.workspace.state import ArchiveRound, Expert, Panel, Session, Symposium

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("council")

# ── App setup ───────────────────────────────────────────────────────────────

GUI_DIR = Path(__file__).resolve().parents[3] / "gui"

app = FastAPI(title="COUNCIL Academy API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_session() -> Session:
    return get_or_create_default()


def _find_expert(session: Session, expert_id: str) -> Expert:
    """Find an expert across all panels. Raises 404 if not found."""
    expert = session.get_expert(expert_id)
    if not expert:
        raise HTTPException(404, f"Expert '{expert_id}' not found")
    return expert


def _find_expert_with_panel(session: Session, expert_id: str) -> tuple[str, Expert]:
    """Find an expert across all panels. Returns (panel_id, Expert). Raises 404."""
    result = session.get_expert_with_panel(expert_id)
    if not result:
        raise HTTPException(404, f"Expert '{expert_id}' not found")
    return result


def _get_expert_panel_id(session: Session, expert_id: str) -> str:
    """Get the panel_id for an expert. Raises 404."""
    panel_id, _ = _find_expert_with_panel(session, expert_id)
    return panel_id


# ── Request models ──────────────────────────────────────────────────────────

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
    target_sources: int = 3        # how many VERIFIED sources to aim for
    time_limit_seconds: int = 120  # max duration for the whole research run


class CreateSymposiumRequest(BaseModel):
    title: str = ""
    format: str = "structured"  # structured | free | one_on_one
    panel_id: str = ""          # Mode A: use this panel's experts + query
    expert_ids: list[str] | None = None  # Mode B: hand-picked experts
    query: str = ""             # Mode B: custom question


class VerifySourceRequest(BaseModel):
    url: str = ""
    quote: str = ""
    claim: str = ""


class PolishQueryRequest(BaseModel):
    query: str


class ProposeExpertRequest(BaseModel):
    query: str
    existing_experts: list[dict] = []


class AddExpertRequest(BaseModel):
    name: str
    discipline: str = ""
    bias: str = ""
    persona_prompt: str = ""


class UpdateSourceRequest(BaseModel):
    verification_status: str  # "verified" | "misattributed" | "unverifiable"


# ── Session (singleton) ─────────────────────────────────────────────────────

@app.get("/api/session")
def get_session():
    """Return the singleton session with all panels, symposia, and messages."""
    t0 = time.time()
    ws = _get_session()

    expert_total = sum(len(p.experts) for p in ws.panels)
    resp = {
        "id": ws.id,
        "panels": [
            {
                "id": p.id,
                "name": p.name,
                "query": p.query,
                "function_type": p.function_type,
                "function_detail": p.function_detail,
                "expert_count": len(p.experts),
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
                "created_at": p.created_at.isoformat() if p.created_at else None,
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
                "has_synthesis": s.has_synthesis,
                "archive": [
                    {
                        "round_number": a.round_number,
                        "synthesis": a.synthesis,
                        "message_count": len(a.message_ids),
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in s.archive
                ],
            }
            for s in ws.symposia
        ],
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "agent_id": m.agent_id,
                "agent_name": m.agent_name,
                "symposium_id": m.symposium_id,
                "content": m.content,
                "turn": m.turn,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in ws.messages
        ],
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }
    log.info("[session] GET /api/session → %d panels, %d experts, %d msgs, %d symposia (%.1fs)",
             len(ws.panels), expert_total, len(ws.messages), len(ws.symposia), time.time() - t0)
    return resp


# ── Panels ──────────────────────────────────────────────────────────────────

@app.post("/api/panels")
def create_panel(req: CreatePanelRequest):
    """Create a new panel — appends, does not replace existing panels."""
    t0 = time.time()
    ws = _get_session()

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
        elapsed = time.time() - t0
        log.error("[panel] POST /api/panels → 500 Moderator failed (%.1fs)", elapsed)
        raise HTTPException(500, "Moderator failed to propose experts")

    panel = Panel(
        name=req.query[:60] if req.query else (req.function_type or "Untitled Panel"),
        query=req.query,
        function_type=req.function_type,
        function_detail=req.function_detail,
        experts=experts,
    )
    ws.panels.append(panel)
    save(ws)

    log.info("[panel] POST /api/panels → panel_id=%s query=%r experts=%d (%.1fs)",
             panel.id, req.query[:80] if req.query else "(none)", len(experts), time.time() - t0)
    return {
        "panel_id": panel.id,
        "experts": [{"id": e.id, "name": e.name, "discipline": e.discipline} for e in experts],
    }


@app.get("/api/panels/{panel_id}")
def get_panel(panel_id: str):
    ws = _get_session()
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, f"Panel '{panel_id}' not found")
    return {
        "id": panel.id,
        "name": panel.name,
        "query": panel.query,
        "function_type": panel.function_type,
        "function_detail": panel.function_detail,
        "expert_count": len(panel.experts),
        "experts": [
            {"id": e.id, "name": e.name, "discipline": e.discipline} for e in panel.experts
        ],
        "created_at": panel.created_at.isoformat() if panel.created_at else None,
    }


@app.put("/api/panels/{panel_id}")
def update_panel(panel_id: str, req: UpdatePanelRequest):
    ws = _get_session()
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, f"Panel '{panel_id}' not found")

    changes = []
    for field in ("name", "query", "function_type", "function_detail"):
        val = getattr(req, field)
        if val is not None:
            setattr(panel, field, val)
            changes.append(field)
    save(ws)
    log.info("[panel] PUT /api/panels/%s → changed=%s", panel_id, ",".join(changes) or "none")
    return {"ok": True}


@app.delete("/api/panels/{panel_id}")
def delete_panel(panel_id: str):
    ws = _get_session()
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, f"Panel '{panel_id}' not found")
    expert_count = len(panel.experts)
    ws.panels = [p for p in ws.panels if p.id != panel_id]
    save(ws)
    log.info("[panel] DELETE /api/panels/%s → removed, experts=%d", panel_id, expert_count)
    return {"deleted": panel_id}


@app.post("/api/panels/{panel_id}/regenerate")
def regenerate_panel(panel_id: str, req: CreatePanelRequest):
    t0 = time.time()
    ws = _get_session()
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, f"Panel '{panel_id}' not found")

    old_count = len(panel.experts)
    query = req.query or panel.query
    experts = moderator_propose_panel(
        query=query,
        function_type=req.function_type or panel.function_type,
        function_detail=req.function_detail or panel.function_detail,
        max_experts=req.max_experts,
    )
    if not experts:
        elapsed = time.time() - t0
        log.error("[panel] POST /api/panels/%s/regenerate → 500 Moderator failed (%.1fs)", panel_id, elapsed)
        raise HTTPException(500, "Moderator failed to propose experts")

    panel.experts = experts
    if query:
        panel.query = query
    save(ws)
    log.info("[panel] POST /api/panels/%s/regenerate → %d→%d experts (%.1fs)",
             panel_id, old_count, len(experts), time.time() - t0)
    return {
        "panel_id": panel_id,
        "experts": [{"id": e.id, "name": e.name, "discipline": e.discipline} for e in experts],
    }


@app.delete("/api/panels/{panel_id}/experts/{expert_id}")
def delete_expert(panel_id: str, expert_id: str):
    """Remove a single expert from a panel."""
    ws = _get_session()
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, f"Panel '{panel_id}' not found")
    for i, e in enumerate(panel.experts):
        if e.id == expert_id:
            removed = panel.experts.pop(i)
            save(ws)
            log.info("[panel] DELETE …/experts/%s → removed %s from %s", expert_id[:8], removed.name, panel_id)
            return {"ok": True, "removed": removed.name}
    raise HTTPException(404, f"Expert '{expert_id}' not found in panel")


@app.post("/api/panels/{panel_id}/experts")
def add_expert_to_panel(panel_id: str, req: AddExpertRequest):
    """Add a single expert to a panel."""
    ws = _get_session()
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, f"Panel '{panel_id}' not found")
    from council.workspace.state import Expert
    expert = Expert(
        name=req.name,
        discipline=req.discipline,
        bias=req.bias,
        persona_prompt=req.persona_prompt,
    )
    panel.experts.append(expert)
    save(ws)
    log.info("[panel] POST …/experts → added %s (%s) to %s", expert.name, expert.discipline, panel_id)
    return {
        "expert_id": expert.id,
        "name": expert.name,
        "discipline": expert.discipline,
    }


# ── Experts ─────────────────────────────────────────────────────────────────

@app.put("/api/panels/{panel_id}/experts/{expert_id}")
def update_expert(panel_id: str, expert_id: str, req: UpdateExpertRequest):
    ws = _get_session()
    panel = ws.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, f"Panel '{panel_id}' not found")
    expert = next((e for e in panel.experts if e.id == expert_id), None)
    if not expert:
        raise HTTPException(404, f"Expert '{expert_id}' not found in panel '{panel_id}'")

    changes = []
    for field in ("name", "discipline", "bias", "persona_prompt", "photo_url"):
        val = getattr(req, field)
        if val is not None:
            setattr(expert, field, val)
            changes.append(field)
    save(ws)
    log.info("[expert] PUT /api/panels/%s/experts/%s → changed=%s", panel_id, expert_id, ",".join(changes))
    return {"ok": True}


@app.get("/api/panels/{panel_id}/experts/{expert_id}/pool")
def get_expert_pool(panel_id: str, expert_id: str):
    ws = _get_session()
    expert = _find_expert(ws, expert_id)

    def _serialize(s):
        return {
            "id": s.id,
            "origin": s.origin,
            "source_type": s.source_type,
            "type": s.type,
            "url": s.url,
            "title": s.title,
            "snippet": s.snippet,
            "full_text_preview": s.full_text[:500] if s.full_text else "",
            "verification_status": s.verification_status,
            "verification_note": s.verification_note,
            "added_by": s.added_by,
        }

    return {
        "curated": [_serialize(s) for s in expert.knowledge_pool.sources if s.origin == "curated"],
        "discovered": [_serialize(s) for s in expert.knowledge_pool.sources if s.origin == "discovered"],
        "opinions": [
            {"id": o.id, "text": o.text, "source_ids": o.source_ids}
            for o in expert.knowledge_pool.opinions
        ],
    }


@app.get("/api/panels/{panel_id}/experts/{expert_id}/sources/{source_id}/full")
def get_source_full_text(panel_id: str, expert_id: str, source_id: str):
    """Return the full extracted text for a source (for click-to-open in GUI)."""
    ws = _get_session()
    expert = _find_expert(ws, expert_id)
    for s in expert.knowledge_pool.sources:
        if s.id == source_id:
            if not s.full_text:
                raise HTTPException(404, "No full text available for this source")
            return {
                "id": s.id,
                "title": s.title,
                "full_text": s.full_text,
                "source_type": s.source_type,
            }
    raise HTTPException(404, "Source not found")


@app.patch("/api/panels/{panel_id}/experts/{expert_id}/sources/{source_id}")
def update_source_status(panel_id: str, expert_id: str, source_id: str, req: UpdateSourceRequest):
    """Update a source's verification status. User can override the fact-checker."""
    ws = _get_session()
    expert = _find_expert(ws, expert_id)
    for s in expert.knowledge_pool.sources:
        if s.id == source_id:
            s.verification_status = req.verification_status
            s.type = "verified" if req.verification_status == "verified" else s.type
            save(ws)
            log.info("[source] status updated %s → %s by user", source_id[:8], req.verification_status)
            return {"ok": True, "verification_status": s.verification_status}
    raise HTTPException(404, "Source not found")


@app.delete("/api/panels/{panel_id}/experts/{expert_id}/sources/{source_id}")
def delete_source(panel_id: str, expert_id: str, source_id: str):
    """Remove a source from the expert's knowledge pool."""
    ws = _get_session()
    expert = _find_expert(ws, expert_id)
    for i, s in enumerate(expert.knowledge_pool.sources):
        if s.id == source_id:
            del expert.knowledge_pool.sources[i]
            save(ws)
            log.info("[source] deleted source %s from %s", source_id[:8], expert.name)
            return {"ok": True}
    raise HTTPException(404, "Source not found")


@app.post("/api/panels/{panel_id}/experts/{expert_id}/sources")
def add_source(panel_id: str, expert_id: str, req: AddSourceRequest):
    t0 = time.time()
    ws = _get_session()
    expert = _find_expert(ws, expert_id)

    src = add_source_to_expert(
        expert=expert,
        session_id=ws.id,
        url=req.url,
        title=req.title,
        snippet=req.snippet,
        full_text=req.full_text,
        enrich=req.enrich,
    )
    save(ws)
    log.info("[source] POST …/experts/%s/sources → url=%r enriched=%s (%.1fs)",
             expert_id, (req.url or req.title)[:80], req.enrich, time.time() - t0)
    return {"source_id": src.id, "title": src.title, "has_full_text": bool(src.full_text)}


@app.post("/api/panels/{panel_id}/experts/{expert_id}/upload")
async def upload_file_endpoint(panel_id: str, expert_id: str, file: UploadFile = File(...)):
    t0 = time.time()
    ws = _get_session()
    expert = _find_expert(ws, expert_id)

    import tempfile
    suffix = Path(file.filename or "upload").suffix or ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    src = upload_file_to_expert(
        expert=expert,
        session_id=ws.id,
        file_path=tmp_path,
    )

    try:
        Path(tmp_path).unlink()
    except Exception:
        pass

    if not src:
        raise HTTPException(400, "Could not parse file. PDFs must contain extractable text (not scanned images). Supported formats: PDF, TXT, MD.")

    save(ws)
    log.info("[upload] POST …/experts/%s/upload → file=%r size=%dKB (%.1fs)",
             expert_id, file.filename, len(src.full_text) // 1024, time.time() - t0)
    return {"source_id": src.id, "title": src.title, "size": len(src.full_text)}


# ── Expert messaging (SSE) ──────────────────────────────────────────────────

@app.post("/api/panels/{panel_id}/experts/{expert_id}/message")
async def expert_message(panel_id: str, expert_id: str, req: MessageRequest):
    t0 = time.time()
    ws = _get_session()
    expert = _find_expert(ws, expert_id)

    async def event_stream():
        # Save the user's message
        ws.add_message(role="user", agent_id=expert.id, content=req.message)

        # Use the expert's own panel's query, or a generic fallback
        query = "the research context"
        result = ws.get_expert_with_panel(expert_id)
        if result:
            panel = ws.get_panel(result[0])
            if panel and panel.query:
                query = panel.query

        response = await asyncio.to_thread(
            expert_respond,
            expert=expert,
            session_id=ws.id,
            query=query,
            message=req.message,
        )
        ws.add_message(
            role="agent",
            agent_id=expert.id,
            agent_name=expert.name,
            content=response,
        )
        save(ws)

        wc = len(response.split())
        log.info("[expert] POST …/experts/%s/message → %r → %d words (%.1fs)",
                 expert_id, req.message[:60], wc, time.time() - t0)

        async for event_type, data in stream_expert_response(
            expert_name=expert.name,
            discipline=expert.discipline,
            content=response,
        ):
            yield sse_event(event_type, data)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/panels/{panel_id}/experts/{expert_id}/research")
async def expert_research_endpoint(panel_id: str, expert_id: str, req: ResearchRequest):
    """Research loop: find sources → fact-check → accept/reject → repeat.
    Stops when target verified count is met or time limit expires."""
    t0 = time.time()
    ws = _get_session()
    expert = _find_expert(ws, expert_id)
    target = max(1, min(req.target_sources, 20))
    deadline = time.time() + max(10, min(req.time_limit_seconds, 600))

    query = ""
    result = ws.get_expert_with_panel(expert_id)
    if result:
        panel = ws.get_panel(result[0])
        if panel and panel.query:
            query = panel.query

    async def event_stream():
        nonlocal query
        yield sse_event("typing", {"name": expert.name, "discipline": expert.discipline, "type": "research"})
        await asyncio.sleep(0.5)

        verified_count = 0
        total_found = 0
        rejected = 0
        rejected_titles: list[str] = []  # feed back to the expert so they avoid repeats

        # Collect existing library URLs/titles so the expert doesn't re-find them
        existing_urls = {s.url for s in expert.knowledge_pool.sources if s.url}

        # Build panel peers list for contrast awareness
        panel_peers = None
        if result:
            the_panel = ws.get_panel(result[0])
            if the_panel and len(the_panel.experts) > 1:
                panel_peers = [
                    {"name": e.name, "discipline": e.discipline, "bias": e.bias}
                    for e in the_panel.experts if e.id != expert_id
                ]
        existing_titles = {s.title for s in expert.knowledge_pool.sources if s.title}

        log.info("[research] starting for %s — target=%d timeout=%ds", expert.name, target, req.time_limit_seconds)

        while verified_count < target and time.time() < deadline:
            remaining = time.time() - deadline
            # Build research goal instructing the expert to find one source, avoiding rejects and duplicates
            goal = f"Find 3-5 high-quality, citable sources about: {query or req.research_goal}. Return ALL sources you find — the Fact-Checker will verify each one. "
            if existing_urls:
                goal += f"DO NOT find these already-in-library URLs: {'; '.join(list(existing_urls)[-10:])}. "
            if rejected_titles:
                goal += f"AVOID these already-rejected sources: {', '.join(rejected_titles[-5:])}. "

            sources = await asyncio.to_thread(
                expert_research,
                expert=expert,
                query=query or req.research_goal,
                research_goal=goal,
                panel_peers=panel_peers,
            )

            for src in sources:
                if verified_count >= target or time.time() >= deadline:
                    break
                total_found += 1

                status = src.verification_status or "unverifiable"

                if status in ("verified", "misattributed"):
                    # Enrich with trafilatura full-text extraction (best-effort)
                    if src.url:
                        try:
                            md = await asyncio.to_thread(_fetch_and_extract_md, src.url, 10)
                            if md:
                                src.full_text = md
                        except Exception:
                            pass
                    expert.knowledge_pool.sources.append(src)
                    if status == "verified":
                        verified_count += 1
                    # Refresh dedup set
                    if src.url:
                        existing_urls.add(src.url)
                    log.info("[research] %s: ✓ %s — %s", expert.name, status, (src.title or src.url)[:60])
                    yield sse_event("source_found", {
                        "source_id": src.id,
                        "title": src.title or src.url,
                        "url": src.url,
                        "snippet": (src.snippet or "")[:200],
                        "status": status,
                        "verified_count": verified_count,
                        "total_found": total_found,
                        "target": target,
                        "elapsed": round(time.time() - t0, 2),
                    })
                else:
                    rejected += 1
                    rejected_titles.append(src.title or src.url or '?')
                    log.info("[research] %s: ✗ %s — %s", expert.name, status, (src.title or src.url)[:60])
                    yield sse_event("source_found", {
                        "source_id": src.id,
                        "title": src.title or src.url,
                        "url": src.url,
                        "snippet": (src.snippet or "")[:200],
                        "status": status,
                        "verified_count": verified_count,
                        "total_found": total_found,
                        "target": target,
                        "elapsed": round(time.time() - t0, 2),
                    })

            # If no sources were returned at all, break to avoid infinite loop
            if not sources:
                log.info("[research] %s: no sources returned, stopping", expert.name)
                break

        save(ws)
        elapsed = round(time.time() - t0, 1)
        log.info("[research] %s complete — found=%d verified=%d rejected=%d (%.1fs)",
                 expert.name, total_found, verified_count, rejected, elapsed)

        yield sse_event("research_complete", {
            "expert_id": expert_id,
            "sources_found": total_found,
            "verified": verified_count,
            "rejected": rejected,
            "elapsed": elapsed,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/panels/{panel_id}/experts/{expert_id}/opinion")
async def expert_form_opinion(panel_id: str, expert_id: str, req: MessageRequest):
    t0 = time.time()
    ws = _get_session()
    expert = _find_expert(ws, expert_id)

    async def event_stream():
        yield sse_event("typing", {"name": expert.name, "discipline": expert.discipline, "type": "opinion"})
        await asyncio.sleep(0.5)

        query = req.message
        if not query:
            result = ws.get_expert_with_panel(expert_id)
            if result:
                panel = ws.get_panel(result[0])
                if panel and panel.query:
                    query = panel.query

        opinion = await asyncio.to_thread(
            form_opinion,
            expert=expert,
            session_id=ws.id,
            query=query,
        )
        save(ws)

        if opinion:
            log.info("[opinion] POST …/experts/%s/opinion → sources=%d (%.1fs)",
                     expert_id, len(opinion.source_ids), time.time() - t0)
            yield sse_event("opinion_ready", {
                "expert_id": expert_id,
                "opinion": opinion.text,
                "source_ids": opinion.source_ids,
            })
        else:
            log.warning("[opinion] POST …/experts/%s/opinion → failed (no verified sources)", expert_id)
            yield sse_event("error", {"message": "Could not form opinion — no verified sources in pool"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Symposia ────────────────────────────────────────────────────────────────

@app.post("/api/symposia")
def create_symposium(req: CreateSymposiumRequest):
    """Create a symposium in one of two modes:
    - Mode A: panel_id → use that panel's experts + query
    - Mode B: expert_ids + query → hand-picked experts with custom question
    - Fallback: all experts across all panels
    """
    t0 = time.time()
    ws = _get_session()
    participant_ids: list[str] = []
    query = req.query or ""
    mode = "custom"

    if req.expert_ids:
        participant_ids = req.expert_ids
        query = req.query or "Symposium"
        mode = "custom"
    elif req.panel_id:
        panel = ws.get_panel(req.panel_id)
        if not panel:
            raise HTTPException(404, f"Panel '{req.panel_id}' not found")
        participant_ids = [e.id for e in panel.experts]
        query = panel.query or req.title
        mode = "panel"
    else:
        participant_ids = [e.id for p in ws.panels for e in p.experts]
        query = req.title or "Cross-panel Symposium"
        mode = "all"

    sym = Symposium(
        title=req.title or query[:60],
        format=req.format,
        participant_ids=participant_ids,
    )
    ws.symposia.append(sym)
    save(ws)

    log.info("[symposium] POST /api/symposia → sym_id=%s mode=%s participants=%d (%.1fs)",
             sym.id, mode, len(participant_ids), time.time() - t0)
    return {"symposium_id": sym.id, "participants": participant_ids}


@app.post("/api/symposia/{sym_id}/round")
async def symposium_round(sym_id: str):
    """Run one structured debate round — each expert speaks in turn."""
    ws = _get_session()
    sym = ws.get_symposium(sym_id)
    if not sym:
        raise HTTPException(404, "Symposium not found")

    participants: list[Expert] = []
    for eid in sym.participant_ids:
        expert = ws.get_expert(eid)
        if expert:
            participants.append(expert)

    if not participants:
        raise HTTPException(400, "No valid participants")

    async def event_stream():
        t0 = time.time()
        transcript_lines: list[str] = []
        # Try to get query from the first participant's panel
        query = sym.title or "the research context"
        if participants:
            result = ws.get_expert_with_panel(participants[0].id)
            if result:
                p = ws.get_panel(result[0])
                if p and p.query:
                    query = p.query

        for i, expert in enumerate(participants):
            turn = i + 1
            t_turn = time.time()

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
                session_id=ws.id,
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

            wc = len(speech.split())
            elapsed = time.time() - t_turn
            log.info("[round] sym_id=%s turn=%d/%d expert=%r (%d words, %.1fs)",
                     sym_id, turn, len(participants), expert.name, wc, elapsed)

            yield sse_event("message", {
                "name": expert.name,
                "discipline": expert.discipline,
                "content": speech,
                "turn": turn,
            })
            await asyncio.sleep(0.3)

        save(ws)
        total_elapsed = time.time() - t0
        log.info("[round] sym_id=%s round_complete → %d turns, saved (%.1fs total)",
                 sym_id, len(participants), total_elapsed)
        yield sse_event("round_complete", {"symposium_id": sym_id, "turns": len(participants)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/symposia/{sym_id}/synthesize")
async def symposium_synthesize(sym_id: str):
    """Rapporteur synthesizes the symposium debate."""
    ws = _get_session()
    sym = ws.get_symposium(sym_id)
    if not sym:
        raise HTTPException(404, "Symposium not found")

    msgs = ws.get_messages_for_symposium(sym_id)
    if not msgs:
        raise HTTPException(400, "Symposium has no messages")

    async def event_stream():
        t0 = time.time()
        yield sse_event("typing", {"name": "Rapporteur", "discipline": "Synthesis", "type": "rapporteur"})
        await asyncio.sleep(1.0)

        transcript = "\n\n".join(
            f"[Turn {m.turn}] **{m.agent_name}**:\n{m.content}" if m.turn
            else f"**{m.agent_name}**:\n{m.content}"
            for m in msgs
            if m.role == "agent"
        )
        scorecard = str(sym.scorecard) if sym.scorecard else "[]"

        query = sym.title
        for eid in sym.participant_ids:
            result = ws.get_expert_with_panel(eid)
            if result:
                p = ws.get_panel(result[0])
                if p and p.query:
                    query = p.query
                    break

        synthesis = await asyncio.to_thread(
            rapporteur_synthesize,
            transcript=transcript,
            scorecard=scorecard,
            query=query,
        )
        sym.synthesis = synthesis
        save(ws)

        wc = len(synthesis.split())
        log.info("[synthesize] sym_id=%s → %d words from %d msgs (%.1fs)",
                 sym_id, wc, len(msgs), time.time() - t0)

        async for event_type, data in stream_rapporteur_synthesis(synthesis):
            yield sse_event(event_type, data)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/symposia/{sym_id}/new-round")
def symposium_new_round(sym_id: str):
    """Archive the current round and start a fresh one."""
    ws = _get_session()
    sym = ws.get_symposium(sym_id)
    if not sym:
        raise HTTPException(404, "Symposium not found")

    if not sym.message_ids:
        raise HTTPException(400, "No messages to archive")

    # Determine round number
    next_num = len(sym.archive) + 1

    # Archive current round
    sym.archive.append(ArchiveRound(
        round_number=next_num,
        message_ids=list(sym.message_ids),
        synthesis=sym.synthesis,
    ))

    # Clear for new round
    sym.synthesis = ""
    sym.scorecard = []
    sym.message_ids = []

    save(ws)
    log.info("[symposium] new round %d for %s — %d messages archived",
             next_num, sym_id, len(sym.archive[-1].message_ids))
    return {"ok": True, "round": next_num + 1, "archive_count": len(sym.archive)}


# ── Export ──────────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    formats: list[str] = ["dossier", "memo", "scorecard", "transcript"]


@app.post("/api/export")
def export_session(req: ExportRequest = ExportRequest()):
    from council.workspace.export import export_all

    t0 = time.time()
    ws = _get_session()
    result = export_all(ws, req.formats)
    log.info("[export] POST /api/export → formats=%s files=%d (%.1fs)",
             ",".join(req.formats), len(result), time.time() - t0)
    return {"files": result, "session_id": ws.id}


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "system": "academy"}


# ── Source Verification ────────────────────────────────────────────────────────


@app.post("/api/verify-source")
def verify_source_endpoint(req: VerifySourceRequest):
    """Verify a source URL against an optional quote. No LLM, no session.

    Calls _verify_source() directly — stateless, no side effects.
    Returns JSON with status, normalized_url, note, and extracted
    markdown preview when available.
    """
    t0 = time.time()
    try:
        normalized_url, status, note = _verify_source(
            source_url=req.url,
            source_quote=req.quote,
        )
    except Exception as exc:
        log.error("[verify] _verify_source raised: %s", exc)
        return {
            "url": req.url,
            "status": "unverifiable",
            "note": f"Verification error: {exc}",
            "elapsed": round(time.time() - t0, 2),
        }

    elapsed = round(time.time() - t0, 2)
    log.info(
        "[verify] POST /api/verify-source → status=%s url=%r (%.2fs)",
        status, (normalized_url or req.url)[:80], elapsed,
    )

    result = {
        "url": normalized_url,
        "status": status,
        "note": note,
        "elapsed": elapsed,
    }

    # When verified via full-page text, include the extracted markdown preview
    # (useful for the GUI and as preparation for knowledge-pool persistence)
    if "full-page text" in note:
        md = _fetch_and_extract_md(req.url, timeout=5)
        if md:
            result["extracted_md_preview"] = md[:500]
            result["extracted_md_length"] = len(md)

    return result


# ── Panel editing helpers ─────────────────────────────────────────────────────


@app.post("/api/polish-query")
def polish_query_endpoint(req: PolishQueryRequest):
    """Refine a research question using an LLM. Stateless."""
    t0 = time.time()
    polished = polish_query(req.query)
    elapsed = round(time.time() - t0, 2)
    log.info("[polish] POST /api/polish-query → %d→%d chars (%.2fs)",
             len(req.query), len(polished), elapsed)
    return {"original": req.query, "polished": polished, "elapsed": elapsed}


@app.post("/api/propose-expert")
def propose_expert_endpoint(req: ProposeExpertRequest):
    """Propose a single gap-filling expert for a panel. Stateless."""
    t0 = time.time()
    result = propose_expert(query=req.query, existing_experts=req.existing_experts)
    elapsed = round(time.time() - t0, 2)
    if result:
        log.info("[propose] POST /api/propose-expert → %s (%s) (%.2fs)",
                 result["name"], result["discipline"], elapsed)
    return {"expert": result, "elapsed": elapsed}


# ── GUI static files ────────────────────────────────────────────────────────

_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


@app.get("/")
def serve_root():
    return FileResponse(GUI_DIR / "workspace.html", headers=_NO_CACHE)


@app.get("/workspace")
def serve_workspace_page():
    return FileResponse(GUI_DIR / "workspace.html", headers=_NO_CACHE)


@app.get("/gui/{filename}")
def serve_gui_file(filename: str):
    path = GUI_DIR / filename
    if path.suffix in (".html", ".css", ".js") and path.exists():
        return FileResponse(path, headers=_NO_CACHE)
    raise HTTPException(404)


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="COUNCIL Workspace Server")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
