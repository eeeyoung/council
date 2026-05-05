"""
tests/test_server.py

Tests for the FastAPI server endpoints.
Uses FastAPI TestClient with temporary output directories.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Prevent dotenv from loading real .env during tests
os.environ.setdefault("AI_PROVIDER", "ds")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-server-tests")

from council.server import OUTPUTS_DIR, GUI_DIR, app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with a temporary outputs directory."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr("council.server.OUTPUTS_DIR", outputs)
    monkeypatch.setattr("council.server.ROOT", tmp_path)
    monkeypatch.setattr("council.server.GUI_DIR", tmp_path / "gui")
    (tmp_path / "gui").mkdir(exist_ok=True)
    (tmp_path / "gui" / "index.html").write_text("<html></html>")
    return TestClient(app)


# ── Static serving ────────────────────────────────────────────────────────

def test_serve_root(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_serve_output_file(client):
    resp = client.get("/outputs/nonexistent_file.txt")
    # FastAPI StaticFiles returns 404 for missing files
    assert resp.status_code in (200, 404)


# ── GET /api/config ───────────────────────────────────────────────────────

def test_get_config(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert data["mode"] == "review"  # default


# ── GET /api/sessions ─────────────────────────────────────────────────────

def test_list_sessions_empty(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data == []  # empty outputs dir


def test_list_sessions_with_data(client, monkeypatch):
    """Create a mock session manifest and verify it shows up."""
    outputs = Path(str(monkeypatch))
    # We need to find the actual monkeypatched OUTPUTS_DIR
    import council.server as server_mod
    out_dir = server_mod.OUTPUTS_DIR

    sid = "test0001"
    panel_file = out_dir / f"{sid}_panel.json"
    panel_file.write_text(json.dumps([
        {"name": "Dr. Test", "discipline": "Physics", "bias": "None", "persona_prompt": "A tester."}
    ]))

    manifest = {
        "session_id": sid,
        "query": "Test query?",
        "status": "done",
        "created_at": None,
        "experts": [
            {"id": "dr_test", "name": "Dr. Test", "discipline": "Physics", "bias": "None", "persona_prompt": "A tester.", "color_index": 0}
        ],
        "phases_complete": ["A", "B", "C", "D", "E"],
        "files": {"panel": f"{sid}_panel.json", "research": [], "rounds": [], "dossier": None},
    }
    (out_dir / f"{sid}_manifest.json").write_text(json.dumps(manifest))

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


# ── GET /api/sessions/{id} ────────────────────────────────────────────────

def test_get_session_not_found(client):
    resp = client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404


def test_get_session_found(client):
    """Create a session manifest and verify the endpoint returns it."""
    import council.server as server_mod
    out_dir = server_mod.OUTPUTS_DIR

    sid = "test0002"
    manifest = {
        "session_id": sid,
        "query": "What is dark matter?",
        "status": "done",
        "created_at": None,
        "experts": [],
        "phases_complete": ["A"],
        "files": {"panel": None, "research": [], "rounds": [], "dossier": None},
    }
    (out_dir / f"{sid}_manifest.json").write_text(json.dumps(manifest))
    (out_dir / f"{sid}_panel.json").write_text("[]")

    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sid
    assert data["query"] == "What is dark matter?"


# ── POST /api/sessions/generate-panel ─────────────────────────────────────

@pytest.mark.skip(reason="Requires real LLM API key — run manually")
def test_generate_panel_endpoint(client):
    resp = client.post("/api/sessions/generate-panel", json={
        "query": "Test query?",
        "expert_count": 3,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "experts" in data


# ── /api/sessions/{id}/events (SSE) ────────────────────────────────────────

def test_session_events_not_found(client):
    resp = client.get("/api/sessions/nonexistent/events")
    assert resp.status_code == 404


def test_session_events_stream(client):
    """Create a minimal session and verify SSE stream starts correctly."""
    import council.server as server_mod
    out_dir = server_mod.OUTPUTS_DIR

    sid = "test0003"
    manifest = {
        "session_id": sid,
        "query": "Test?",
        "status": "done",
        "created_at": None,
        "experts": [],
        "audit_rounds": 0,
        "phases_complete": ["A"],
        "files": {"panel": None, "research": [], "rounds": [], "dossier": None},
    }
    (out_dir / f"{sid}_manifest.json").write_text(json.dumps(manifest))
    (out_dir / f"{sid}_panel.json").write_text("[]")

    resp = client.get(f"/api/sessions/{sid}/events")
    assert resp.status_code == 200
    # Verify it starts with an SSE event
    content = resp.text
    assert "event: session_start" in content or resp.headers.get("content-type", "").startswith("text/event-stream")


# ── POST /api/sessions/{id}/proceed ───────────────────────────────────────

def test_proceed_session_not_found(client):
    resp = client.post("/api/sessions/nonexistent/proceed", json={
        "query": "Test query?",
        "experts": [{"name": "Dr. X", "discipline": "Physics", "bias": "None", "persona_prompt": "A tester."}]
    })
    assert resp.status_code == 404
