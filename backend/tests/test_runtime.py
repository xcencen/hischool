"""Readiness must not compromise the independent liveness endpoint."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.bootstrap.config import BootstrapSettings
from app.main import create_app


@pytest.mark.parametrize("available,expected", [(True, 200), (False, 503)])
def test_readiness_liveness_and_cleanup(monkeypatch, available, expected):
    from app import runtime

    session = SimpleNamespace(execute=AsyncMock())
    redis = SimpleNamespace(ping=AsyncMock(return_value=True), aclose=AsyncMock())
    if not available:
        session.execute.side_effect = ConnectionError("sensitive-database-password")
        redis.ping.side_effect = ConnectionError("sensitive-redis-address")

    @asynccontextmanager
    async def session_factory():
        yield session

    database = SimpleNamespace(session_factory=session_factory, dispose=AsyncMock())
    settings = SimpleNamespace(database_url="test", redis_url="test")
    monkeypatch.setattr(runtime, "load_settings", lambda: settings)
    monkeypatch.setattr(runtime, "Database", lambda _: database)
    monkeypatch.setattr(runtime.Redis, "from_url", lambda *args, **kwargs: redis)
    with TestClient(create_app(BootstrapSettings(), mode="campus")) as client:
        response = client.get("/api/ready")
        assert response.status_code == expected
        assert response.json()["data"] == {"mysql": available, "redis": available}
        assert "sensitive" not in response.text
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/auth/login", json={}).status_code == 404
    database.dispose.assert_awaited_once()
    redis.aclose.assert_awaited_once()


def test_bootstrap_has_no_readiness_route():
    with TestClient(create_app(BootstrapSettings(), mode="bootstrap")) as client:
        assert client.get("/api/ready").status_code == 404
        assert client.get("/api/health").status_code == 200


def test_invalid_mode_fails_explicitly():
    with pytest.raises(ValueError, match="APP_MODE"):
        create_app(BootstrapSettings(), mode="unexpected")
