# tests/test_api.py
"""Tests for the FastAPI endpoints."""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_root():
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Codebase AI"
    assert "endpoints" in data


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"


def test_repo_tree_not_found():
    res = client.get("/api/repo/nonexistent/tree")
    assert res.status_code == 404
