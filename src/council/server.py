"""
council/server.py

Lightweight FastAPI server for the COUNCIL GUI.

Serves:
  - GUI static files  (gui/)
  - Output files      (outputs/)
  - REST session API  (/api/sessions)
  - SSE replay stream (/api/sessions/{id}/events)

Usage:
    uv run python -m council.server
    uv run python -m council.server --port 8000 --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import council.config  # noqa: F401 — triggers load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT        = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = ROOT / "outputs"
GUI_DIR     = ROOT / "gui"

# Server mode — set by CLI before uvicorn starts
SERVER_MODE: str = "review"

app = FastAPI(title="COUNCIL Server", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Manifest helpers ─────────────────────────────────────────────────────────

def _build_manifest(session_id: str) -> dict | None:
    """
    Return the manifest for a session.
    Reads _manifest.json if it exists; otherwise auto-generates one from
    whatever output files are present (supports sessions predating this feature).
    """
    manifest_path = OUTPUTS_DIR / f"{session_id}_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Backfill persona_prompt if missing (older manifests)
        panel_file = OUTPUTS_DIR / f"{session_id}_panel.json"
        if panel_file.exists():
            panel_raw = json.loads(panel_file.read_text(encoding="utf-8"))
            panel_by_name = {e["name"]: e.get("persona_prompt", "") for e in panel_raw}
            for expert in manifest.get("experts", []):
                if "persona_prompt" not in expert:
                    expert["persona_prompt"] = panel_by_name.get(expert.get("name", ""), "")
        return manifest

    # Auto-generate for legacy sessions
    panel_file = OUTPUTS_DIR / f"{session_id}_panel.json"
    if not panel_file.exists():
        return None

    experts_raw = json.loads(panel_file.read_text(encoding="utf-8"))
    experts = [
        {
            "id":             e.get("name", "").replace(".", "").replace(" ", "_").lower(),
            "name":           e.get("name", ""),
            "discipline":     e.get("discipline", ""),
            "bias":           e.get("bias", ""),
            "persona_prompt": e.get("persona_prompt", ""),
            "color_index":    i,
        }
        for i, e in enumerate(experts_raw)
    ]

    # Research files
    research_files = []
    for expert in experts:
        f = OUTPUTS_DIR / f"{session_id}_research_{expert['id']}.md"
        if f.exists():
            research_files.append({"expert_id": expert["id"], "expert_name": expert["name"], "file": f.name})
    agg = OUTPUTS_DIR / f"{session_id}_research___aggregation__.md"
    if agg.exists():
        research_files.append({"expert_id": "__aggregation__", "expert_name": "Aggregator Summary", "file": agg.name})

    # Rounds — try new _r0 format first, fall back to legacy (no suffix)
    rounds = []
    for r in range(10):
        t = OUTPUTS_DIR / f"{session_id}_transcript_r{r}.md"
        s = OUTPUTS_DIR / f"{session_id}_scorecard_r{r}.md"
        c = OUTPUTS_DIR / f"{session_id}_consensus_r{r + 1}.md"
        if t.exists() or s.exists():
            rounds.append({
                "round":     r,
                "transcript": t.name if t.exists() else None,
                "scorecard":  s.name if s.exists() else None,
                "consensus":  c.name if c.exists() else None,
            })

    if not rounds:  # legacy single-file format
        t = OUTPUTS_DIR / f"{session_id}_transcript.md"
        s = OUTPUTS_DIR / f"{session_id}_scorecard.md"
        if t.exists() or s.exists():
            rounds.append({
                "round":     0,
                "transcript": t.name if t.exists() else None,
                "scorecard":  s.name if s.exists() else None,
                "consensus":  None,
            })

    dossier = OUTPUTS_DIR / f"{session_id}_dossier.md"

    phases_complete = []
    if panel_file.exists():             phases_complete.append("A")
    if research_files:                  phases_complete.append("B")
    if rounds:                          phases_complete.append("C")
    if any(r.get("consensus") for r in rounds): phases_complete.append("D")
    if dossier.exists():                phases_complete.append("E")

    return {
        "session_id":    session_id,
        "query":         "",
        "status":        "done" if dossier.exists() else "partial",
        "created_at":    None,
        "experts":       experts,
        "audit_rounds":  len(rounds),
        "files": {
            "panel":    panel_file.name,
            "research": research_files,
            "rounds":   rounds,
            "dossier":  dossier.name if dossier.exists() else None,
        },
        "phases_complete": phases_complete,
    }


def _write_manifest(state) -> None:
    """Write/update outputs/{session_id}_manifest.json."""
    from council.state import CouncilState

    experts = []
    for i, e in enumerate(state.experts):
        expert_id = e.name.replace(".", "").replace(" ", "_").lower()
        experts.append({
            "id": expert_id,
            "name": e.name,
            "discipline": e.discipline,
            "bias": e.bias,
            "persona_prompt": e.persona_prompt,
            "color_index": i,
        })

    research_files: list[dict] = []
    for expert in experts:
        f = OUTPUTS_DIR / f"{state.session_id}_research_{expert['id']}.md"
        if f.exists():
            research_files.append({
                "expert_id": expert["id"],
                "expert_name": expert["name"],
                "file": f.name,
            })
    agg = OUTPUTS_DIR / f"{state.session_id}_research___aggregation__.md"
    if agg.exists():
        research_files.append({
            "expert_id": "__aggregation__",
            "expert_name": "Aggregator Summary",
            "file": agg.name,
        })

    rounds: list[dict] = []
    for r in range(10):
        t = OUTPUTS_DIR / f"{state.session_id}_transcript_r{r}.md"
        s = OUTPUTS_DIR / f"{state.session_id}_scorecard_r{r}.md"
        c = OUTPUTS_DIR / f"{state.session_id}_consensus_r{r + 1}.md"
        if t.exists() or s.exists():
            rounds.append({
                "round": r,
                "transcript": t.name if t.exists() else None,
                "scorecard": s.name if s.exists() else None,
                "consensus": c.name if c.exists() else None,
            })

    if not rounds:
        t = OUTPUTS_DIR / f"{state.session_id}_transcript.md"
        s = OUTPUTS_DIR / f"{state.session_id}_scorecard.md"
        if t.exists() or s.exists():
            rounds.append({
                "round": 0,
                "transcript": t.name if t.exists() else None,
                "scorecard": s.name if s.exists() else None,
                "consensus": None,
            })

    panel = OUTPUTS_DIR / f"{state.session_id}_panel.json"
    dossier = OUTPUTS_DIR / f"{state.session_id}_dossier.md"

    phases_complete: list[str] = []
    if panel.exists():             phases_complete.append("A")
    if research_files:             phases_complete.append("B")
    if rounds:                     phases_complete.append("C")
    if any(r.get("consensus") for r in rounds): phases_complete.append("D")
    if dossier.exists():           phases_complete.append("E")

    manifest = {
        "session_id": state.session_id,
        "query": state.query,
        "status": state.status,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "experts": experts,
        "audit_rounds": len(rounds),
        "files": {
            "panel": panel.name if panel.exists() else None,
            "research": research_files,
            "rounds": rounds,
            "dossier": dossier.name if dossier.exists() else None,
        },
        "phases_complete": phases_complete,
    }

    OUTPUTS_DIR.mkdir(exist_ok=True)
    manifest_path = OUTPUTS_DIR / f"{state.session_id}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


# ─── API routes ───────────────────────────────────────────────────────────────

@app.get("/api/sessions")
def list_sessions() -> list[dict]:
    """List all sessions discovered from outputs/, newest first."""
    OUTPUTS_DIR.mkdir(exist_ok=True)
    seen: set[str] = set()
    sessions: list[dict] = []

    for f in sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        # Session IDs are the 8-char hex prefix before the first underscore
        parts = f.stem.split("_", 1)
        sid = parts[0]
        if len(sid) != 8 or sid in seen:
            continue
        manifest = _build_manifest(sid)
        if manifest:
            seen.add(sid)
            sessions.append({
                "session_id":      sid,
                "query":           manifest.get("query", ""),
                "status":          manifest.get("status", "unknown"),
                "phases_complete": manifest.get("phases_complete", []),
            })

    return sessions


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    """Return the full manifest for one session."""
    manifest = _build_manifest(session_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return manifest


@app.get("/api/sessions/{session_id}/events")
async def session_events(session_id: str) -> StreamingResponse:
    """
    SSE stream that replays a completed session with realistic timing.
    Used by the GUI's 'Live Replay' mode — no LLM tokens consumed.
    """
    manifest = _build_manifest(session_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    from council.simulator import simulate_session

    async def event_stream():
        async for event_type, data in simulate_session(session_id, manifest):
            yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Live-mode endpoints ──────────────────────────────────────────────────────


class GeneratePanelRequest(BaseModel):
    query: str = Field(..., min_length=10, description="Research question")
    expert_count: int = Field(default=5, ge=2, le=6, description="Number of experts")


class ProceedRequest(BaseModel):
    query: str
    experts: list[dict]  # Raw expert dicts from GUI editor


@app.get("/api/config")
def get_config() -> dict:
    """Return server configuration so the GUI can adapt to the current mode."""
    return {"mode": SERVER_MODE}


@app.post("/api/sessions/generate-panel")
def generate_panel(req: GeneratePanelRequest) -> dict:
    """
    Run the Moderator LLM to produce an expert panel.
    Creates a new CouncilState, persists it, writes panel JSON and manifest.
    Returns session_id with the panel for the GUI wizard.
    """
    from council.agents.moderator import run_curation
    from council.db import init_db, save_state
    from council.state import CouncilState

    init_db()

    state = CouncilState(
        query=req.query,
        max_experts=req.expert_count,
    )

    experts = run_curation(state)
    state.experts = experts
    state.status = "researching"
    save_state(state)

    # Write panel JSON
    panel_file = OUTPUTS_DIR / f"{state.session_id}_panel.json"
    panel_file.write_text(
        json.dumps([e.model_dump() for e in experts], indent=2),
        encoding="utf-8",
    )

    _write_manifest(state)

    return {
        "session_id": state.session_id,
        "query": state.query,
        "experts": [e.model_dump() for e in experts],
    }


@app.post("/api/sessions/{session_id}/proceed")
def proceed_session(session_id: str, req: ProceedRequest) -> dict:
    """
    Save the user-edited expert panel so the live pipeline can start.
    The pipeline begins when the GUI connects to GET /{session_id}/live.
    """
    from council.db import load_state, save_state
    from council.state import ExpertDefinition

    try:
        state = load_state(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if state.status != "researching":
        raise HTTPException(
            status_code=409,
            detail=f"Session is in status '{state.status}', expected 'researching'",
        )

    state.query = req.query
    state.experts = [ExpertDefinition(**e) for e in req.experts]
    save_state(state)

    return {"session_id": session_id, "status": "ready"}


@app.get("/api/sessions/{session_id}/live")
async def session_live(session_id: str) -> StreamingResponse:
    """
    SSE stream that runs the full live pipeline (Phases B-E) in real time.
    Uses the actual LLM-powered crews — no tokens consumed via replay.
    """
    from council.db import load_state
    from council.live_runner import run_live_session

    try:
        state = load_state(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if state.status != "researching":
        raise HTTPException(
            status_code=409,
            detail=f"Session is in status '{state.status}', expected 'researching'",
        )

    async def event_stream():
        async for event_type, data in run_live_session(state):
            yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Output file serving ──────────────────────────────────────────────────────

@app.get("/outputs/{filename}")
def serve_output(filename: str) -> FileResponse:
    path = OUTPUTS_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(path)


# ─── GUI static files (must be mounted last) ──────────────────────────────────

if GUI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(GUI_DIR), html=True), name="gui")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="council.server",
        description="COUNCIL GUI Server — serves the web UI and session API",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument(
        "--mode", default="review", choices=["review", "live"],
        help="Server mode: 'review' (offline, default) or 'live' (real-time sessions)",
    )
    return parser.parse_args()


def main() -> None:
    import uvicorn
    global SERVER_MODE
    args = _parse_args()
    SERVER_MODE = args.mode
    print(f"COUNCIL Server [{SERVER_MODE.upper()}] — http://{args.host}:{args.port}")
    print("Open the URL above in your browser to access the GUI.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
