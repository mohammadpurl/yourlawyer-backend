"""Integration tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data


def test_stats_endpoint():
    """Test stats endpoint."""
    response = client.get("/rag/stats")
    assert response.status_code == 200
    data = response.json()
    assert "num_vectors" in data
    assert "collection" in data


def test_sources_endpoint():
    """Test sources endpoint."""
    response = client.get("/rag/sources")
    assert response.status_code == 200
    data = response.json()
    assert "total_files" in data
    assert "total_chunks" in data
    assert "sources" in data



