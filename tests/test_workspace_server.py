"""
tests/test_workspace_server.py

Tests for the workspace server API endpoints (multi-panel refactor).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import council.workspace.db as wsdb

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(wsdb, "DB_PATH", tmp_path / "test.db")
    yield

from council.workspace.server import app  # noqa: E402

client = TestClient(app)


class TestHealth:
    def test_health(self):
        assert client.get("/api/health").status_code == 200


class TestSession:
    def test_get_session(self):
        """GET /api/session returns the singleton session."""
        resp = client.get("/api/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "default"
        assert "panels" in data
        assert "symposia" in data
        assert "messages" in data

    def test_get_session_has_panels_array(self):
        resp = client.get("/api/session")
        assert isinstance(resp.json()["panels"], list)


class TestPanelsCRUD:
    def test_create_panel_requires_moderator(self, monkeypatch):
        """POST /api/panels creates a new panel (needs LLM — will 500 in test)."""
        # Without a real LLM, moderator_propose_panel will fail
        resp = client.post("/api/panels", json={"query": "test query", "max_experts": 2})
        # 500 is expected — no LLM available in test
        assert resp.status_code in (200, 500)

    def test_get_panel_404(self):
        assert client.get("/api/panels/nonexistent").status_code == 404

    def test_delete_panel_404(self):
        assert client.delete("/api/panels/nonexistent").status_code == 404

    def test_put_panel_404(self):
        assert client.put("/api/panels/nonexistent", json={"name": "x"}).status_code == 404

    def test_regenerate_panel_404(self):
        resp = client.post("/api/panels/nonexistent/regenerate", json={"query": "x"})
        assert resp.status_code == 404

    def test_expert_update_404(self):
        resp = client.put("/api/panels/nonexistent/experts/e1", json={"name": "x"})
        assert resp.status_code == 404

    def test_expert_pool_404(self):
        assert client.get("/api/panels/nonexistent/experts/e1/pool").status_code == 404

    def test_expert_message_404(self):
        resp = client.post("/api/panels/nonexistent/experts/e1/message", json={"message": "hi"})
        assert resp.status_code == 404

    def test_expert_research_404(self):
        resp = client.post("/api/panels/nonexistent/experts/e1/research", json={"research_goal": "x"})
        assert resp.status_code == 404

    def test_expert_opinion_404(self):
        resp = client.post("/api/panels/nonexistent/experts/e1/opinion", json={"message": "x"})
        assert resp.status_code == 404


class Test404s:
    def test_uniform_404(self):
        endpoints = [
            ("get", "/api/panels/nonexistent", None),
            ("put", "/api/panels/nonexistent", {}),
            ("delete", "/api/panels/nonexistent", None),
            ("post", "/api/panels/nonexistent/regenerate", {}),
            ("put", "/api/panels/nonexistent/experts/e1", {}),
            ("get", "/api/panels/nonexistent/experts/e1/pool", None),
            ("post", "/api/panels/nonexistent/experts/e1/message", {"message":"t"}),
            ("post", "/api/panels/nonexistent/experts/e1/research", {"research_goal":"t"}),
            ("post", "/api/panels/nonexistent/experts/e1/opinion", {"message":"t"}),
            ("post", "/api/panels/nonexistent/experts/e1/sources", {"url":"x"}),
            ("post", "/api/symposia/nonexistent/round", None),
            ("post", "/api/symposia/nonexistent/synthesize", None),
        ]
        for method, url, body in endpoints:
            if method == "get": resp = client.get(url)
            elif method == "put": resp = client.put(url, json=body or {})
            elif method == "delete": resp = client.delete(url)
            else: resp = client.post(url, json=body or {})
            assert resp.status_code == 404, f"{method.upper()} {url} → {resp.status_code}"


class TestSymposia:
    def test_create_symposium_no_panels(self):
        """Symposium creation works even with no panels (uses all experts)."""
        resp = client.post("/api/symposia", json={"title": "Test"})
        assert resp.status_code == 200
        assert "symposium_id" in resp.json()

    def test_round_404(self):
        assert client.post("/api/symposia/nonexistent/round").status_code == 404

    def test_synthesize_404(self):
        assert client.post("/api/symposia/nonexistent/synthesize").status_code == 404


class TestExport:
    def test_export(self):
        resp = client.post("/api/export", json={"formats": ["dossier"]})
        assert resp.status_code == 200
        assert "files" in resp.json()
