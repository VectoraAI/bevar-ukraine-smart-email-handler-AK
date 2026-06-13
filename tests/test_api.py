from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from src.storage.database import DatabaseManager


@pytest.fixture
def client(populated_db: DatabaseManager) -> Generator[TestClient, None, None]:
    import src.storage.database as db_module
    from src.agents.orchestrator import Orchestrator
    from src.api.app import app
    from src.api.routes import get_orchestrator

    # Override global singleton BEFORE TestClient starts (lifespan uses get_database)
    original = db_module._db_instance
    db_module._db_instance = populated_db

    def _override() -> Orchestrator:
        return Orchestrator(populated_db)

    app.dependency_overrides[get_orchestrator] = _override

    with TestClient(app) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    db_module._db_instance = original


class TestAPI:
    def test_health(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_stats(self, client: TestClient) -> None:
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.json()["total_emails"] == 5

    def test_query_empty(self, client: TestClient) -> None:
        resp = client.post("/api/query", json={"query": ""})
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_query_search(self, client: TestClient) -> None:
        resp = client.post("/api/query", json={"query": "grant application"})
        assert resp.status_code == 200
        assert "text" in resp.json()

    def test_get_email(self, client: TestClient) -> None:
        resp = client.get("/api/email/msg001@bevar.org")
        assert resp.status_code == 200
        assert "email" in resp.json()

    def test_get_email_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/email/nonexistent")
        assert resp.status_code == 200
        assert resp.json().get("error") == "Email not found"

    def test_ingestion_status(self, client: TestClient) -> None:
        resp = client.get("/api/ingestion/status")
        assert resp.status_code == 200

    def test_export_csv(self, client: TestClient) -> None:
        resp = client.get("/api/export/csv?q=")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_index_page(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Bevar Ukraine" in resp.text

    def test_top_senders(self, client: TestClient) -> None:
        resp = client.get("/api/top-senders")
        assert resp.status_code == 200
        assert "labels" in resp.json()

    def test_timeline(self, client: TestClient) -> None:
        resp = client.get("/api/timeline")
        assert resp.status_code == 200
        assert "labels" in resp.json()
