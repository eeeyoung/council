"""
tests/test_workspace_server.py

Phase 3 tests for session API endpoints.
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


class TestSessionCRUD:
    def test_create(self):
        resp = client.post("/api/sessions", json={"query": "test"})
        assert resp.status_code == 200
        assert "id" in resp.json()

    def test_list(self):
        client.post("/api/sessions", json={"query": "a"})
        client.post("/api/sessions", json={"query": "b"})
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_get(self):
        sid = client.post("/api/sessions", json={"query": "get me"}).json()["id"]
        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 200
        assert resp.json()["query"] == "get me"

    def test_get_404(self):
        assert client.get("/api/sessions/nonexistent").status_code == 404

    def test_delete(self):
        sid = client.post("/api/sessions", json={"query": "del"}).json()["id"]
        assert client.delete(f"/api/sessions/{sid}").status_code == 200
        assert client.get(f"/api/sessions/{sid}").status_code == 404


class Test404s:
    def test_uniform_404(self):
        endpoints = [
            ("get", "/api/sessions/nonex-123", None),
            ("delete", "/api/sessions/nonex-123", None),
            ("post", "/api/sessions/nonex-123/panels", {}),
            ("put", "/api/sessions/nonex-123", {}),
            ("put", "/api/sessions/nonex-123/experts/e1", {}),
            ("get", "/api/sessions/nonex-123/experts/e1/pool", None),
            ("post", "/api/sessions/nonex-123/experts/e1/message", {"message":"t"}),
            ("post", "/api/sessions/nonex-123/experts/e1/research", {"research_goal":"t"}),
            ("post", "/api/sessions/nonex-123/experts/e1/opinion", {"message":"t"}),
            ("post", "/api/sessions/nonex-123/experts/e1/sources", {"url":"x"}),
            ("post", "/api/sessions/nonex-123/symposia", {}),
            ("post", "/api/sessions/nonex-123/symposia/s1/round", {}),
            ("post", "/api/sessions/nonex-123/symposia/s1/synthesize", {}),
            ("post", "/api/sessions/nonex-123/export", {}),
        ]
        for method, url, body in endpoints:
            if method == "get": resp = client.get(url)
            elif method == "put": resp = client.put(url, json=body or {})
            elif method == "delete": resp = client.delete(url)
            else: resp = client.post(url, json=body or {})
            assert resp.status_code == 404, f"{method.upper()} {url} → {resp.status_code}"
