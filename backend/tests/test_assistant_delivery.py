"""Actual HTTP chunks arrive before completion; reconnect never submits work."""

from copy import deepcopy
import socket
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest
from starlette.exceptions import HTTPException
import uvicorn

from app.api.assistant import router
from app.assistant import stream
from app.assistant.settings import AssistantSettings
from app.common.exceptions import (BusinessException, business_exception_handler,
                                   http_excpetion_hadler)
from app.config import Settings
from app.utils.jwt import create_access_token


@pytest.fixture
def delivery(monkeypatch):
    finished = threading.Event()
    reads, leases = [], []
    run_id = str(uuid4())
    run = {"id": run_id, "status": "running", "model_calls": 1, "tool_calls": 0}
    message = {"id": 1, "sequence": 2, "run_id": run_id, "role": "assistant",
        "content": "合成回复🙂\n" * 50, "citations": [], "redacted": False,
        "created_at": "2026-10-30T00:00:00Z"}

    async def snapshot(database, redis, settings, public_id, identity):
        assert public_id == run_id and identity.user_id == 1
        reads.append(public_id)
        return ({**run, "status": "succeeded"}, deepcopy(message)) if finished.is_set() else (dict(run), None)

    class Lease:
        def __init__(self, *args):
            self.closed = False
            leases.append(self)

        async def acquire(self):
            pass

        async def renew(self):
            pass

        async def close(self):
            self.closed = True

    monkeypatch.setattr(stream, "snapshot", snapshot)
    monkeypatch.setattr(stream, "ConnectionLease", Lease)
    monkeypatch.setattr(stream, "POLL_SECONDS", .01)
    monkeypatch.setattr(stream, "CHUNK_INTERVAL", .001)
    campus = Settings(database_url="mysql+asyncmy://test:unused@localhost/my_campus_test?charset=utf8mb4",
        redis_url="redis://localhost/15", jwt_secret="synthetic-delivery-only-signing-key-2026")
    app = FastAPI()
    app.state.settings = campus
    app.state.assistant_settings = AssistantSettings()
    app.state.database = app.state.redis = object()
    app.include_router(router, prefix="/api")
    app.add_exception_handler(BusinessException, business_exception_handler)
    app.add_exception_handler(HTTPException, http_excpetion_hadler)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    address = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, ws="none"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        yield SimpleNamespace(url=address + f"/api/assistant/runs/{run_id}/events", finished=finished,
            message=message, reads=reads, leases=leases,
            headers={"Authorization": "Bearer " + create_access_token(1, 0, campus)})
    finally:
        finished.set()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def test_http_delivers_status_before_terminal_answer_and_reconnects_by_cursor(delivery):
    with httpx.Client(timeout=5, trust_env=False) as client:
        with client.stream("GET", delivery.url, headers=delivery.headers) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-accel-buffering"] == "no"
            assert "no-store" in response.headers["cache-control"]
            lines = response.iter_lines()
            assert next(lines) == "event: status"
            assert not delivery.finished.is_set()
            delivery.finished.set()
            remaining = "\n".join(lines)
            assert "id: 1" in remaining and "event: delta" in remaining
            assert "event: done" in remaining and "合成回复" in remaining
        reconnect = client.get(delivery.url + "?after=1", headers=delivery.headers)
        assert reconnect.status_code == 200
        assert "id: 1\n" not in reconnect.text and "id: 2\n" in reconnect.text
        assert "event: done" in reconnect.text
        assert client.get(delivery.url).status_code == 401
        assert client.get(delivery.url + "?after=251", headers=delivery.headers).status_code == 422
    assert delivery.leases and all(lease.closed for lease in delivery.leases)


def test_disconnect_releases_subscription_without_cancelling_or_submitting_run(delivery):
    with httpx.Client(timeout=5, trust_env=False) as client:
        with client.stream("GET", delivery.url, headers=delivery.headers) as response:
            assert next(response.iter_lines()) == "event: status"
        deadline = time.monotonic() + 2
        while not all(lease.closed for lease in delivery.leases) and time.monotonic() < deadline:
            time.sleep(.01)
    assert all(lease.closed for lease in delivery.leases)
    assert not delivery.finished.is_set()
