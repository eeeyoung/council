"""
tests/test_workspace_server.py

Phase 3 tests for workspace API endpoints.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import council.workspace.db as wsdb

# Point workspace DB at a temp path before importing server
@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(wsdb, "DB_PATH", tmp_path / "test_workspace.db")
    yield


from council.workspace.server import app  # noqa: E402

client = TestClient(app)


class TestHealth:
    def test_health(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestWorkspaceCRUD:
    def test_create_workspace(self):
        resp = client.post("/api/workspace", json={"query": "test query"})
        assert resp.status_code == 200
        assert "id" in resp.json()

    def test_list_workspaces(self):
        client.post("/api/workspace", json={"query": "a"})
        client.post("/api/workspace", json={"query": "b"})
        resp = client.get("/api/workspace")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_get_workspace(self):
        resp = client.post("/api/workspace", json={"query": "get me"})
        ws_id = resp.json()["id"]
        resp2 = client.get(f"/api/workspace/{ws_id}")
        assert resp2.status_code == 200
        assert resp2.json()["query"] == "get me"

    def test_get_workspace_not_found(self):
        resp = client.get("/api/workspace/nonexistent")
        assert resp.status_code == 404

    def test_delete_workspace(self):
        resp = client.post("/api/workspace", json={"query": "delete me"})
        ws_id = resp.json()["id"]
        resp2 = client.delete(f"/api/workspace/{ws_id}")
        assert resp2.status_code == 200
        resp3 = client.get(f"/api/workspace/{ws_id}")
        assert resp3.status_code == 404


class TestExpertCRUD:
    def test_update_expert_not_found(self):
        resp = client.put(
            "/api/workspace/test-ws/experts/test-expert",
            json={"name": "New Name"},
        )
        assert resp.status_code == 404

    def test_get_pool_not_found(self):
        resp = client.get("/api/workspace/test-ws/experts/test-expert/pool")
        assert resp.status_code == 404

    def test_add_source_not_found(self):
        resp = client.post(
            "/api/workspace/test-ws/experts/test-expert/sources",
            json={"url": "https://example.com", "title": "Test"},
        )
        assert resp.status_code == 404


class TestSymposiumCRUD:
    def test_create_symposium_no_panel(self):
        client.post("/api/workspace", json={"query": "test"})
        # Need experts first — this should fail cleanly
        resp = client.post(
            "/api/workspace/test-ws/symposia",
            json={"title": "Test", "expert_ids": []},
        )
        assert resp.status_code == 404  # workspace not found

    def test_symposium_round_not_found(self):
        resp = client.post("/api/workspace/test-ws/symposia/test-sym/round")
        assert resp.status_code == 404

    def test_synthesize_not_found(self):
        resp = client.post("/api/workspace/test-ws/symposia/test-sym/synthesize")
        assert resp.status_code == 404


class TestExport:
    def test_export_not_found(self):
        resp = client.post("/api/workspace/test-ws/export")
        assert resp.status_code == 404


class TestErrorHandling:
    def test_missing_workspace_uniform_404(self):
        # Each tuple: (method, url, body)
        # SSE endpoints need valid body to pass Pydantic validation before hitting load()
        endpoints = [
            ("get", "/api/workspace/nonexistent-123", None),
            ("delete", "/api/workspace/nonexistent-123", None),
            ("post", "/api/workspace/nonexistent-123/panels", {}),
            ("put", "/api/workspace/nonexistent-123/panels/p1", {}),
            ("put", "/api/workspace/nonexistent-123/experts/e1", {}),
            ("get", "/api/workspace/nonexistent-123/experts/e1/pool", None),
            ("post", "/api/workspace/nonexistent-123/experts/e1/message", {"message": "test"}),
            ("post", "/api/workspace/nonexistent-123/experts/e1/research", {"research_goal": "test"}),
            ("post", "/api/workspace/nonexistent-123/experts/e1/opinion", {"message": "test"}),
            ("post", "/api/workspace/nonexistent-123/experts/e1/sources", {"url": "https://x.com"}),
            ("post", "/api/workspace/nonexistent-123/symposia", {"expert_ids": []}),
            ("post", "/api/workspace/nonexistent-123/symposia/s1/round", {}),
            ("post", "/api/workspace/nonexistent-123/symposia/s1/synthesize", {}),
            ("post", "/api/workspace/nonexistent-123/export", {}),
        ]
        for method, url, body in endpoints:
            if method == "get":
                resp = client.get(url)
            elif method == "put":
                resp = client.put(url, json=body or {})
            elif method == "delete":
                resp = client.delete(url)
            else:
                resp = client.post(url, json=body or {})
            assert resp.status_code == 404, f"{method.upper()} {url} returned {resp.status_code}, expected 404"
