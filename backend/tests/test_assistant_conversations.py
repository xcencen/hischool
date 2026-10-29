"""Strict requests, bounded complete context, public DTO and HTTP boundaries."""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.api.assistant import router
from app.assistant.conversations import bounded_context, conversation_response
from app.assistant.schemas import ConversationCreate, ConversationUpdate, RunCreate, RunRetry, run_response
from app.assistant.settings import AssistantSettings
from app.common.exceptions import BusinessException, business_exception_handler
from app.database import get_db
from app.dependencies.auth import get_current_user


@pytest.mark.parametrize("model,raw", [
    (ConversationCreate, {"title": "one", "owner_id": 2}),
    (ConversationCreate, {"title": 12}), (ConversationCreate, {"title": "  "}),
    (ConversationCreate, {"title": "\ud800"}),
    (ConversationUpdate, {}), (ConversationUpdate, {"title": None}),
    (ConversationUpdate, {"state": "deleted"}),
    (RunCreate, {"content": "hello", "request_key": "one", "model": "override"}),
    (RunCreate, {"content": "hello", "request_key": "one", "cost_limit": "1000"}),
    (RunCreate, {"content": "hello", "request_key": "one", "user_id": 2}),
    (RunCreate, {"content": "x" * 4001, "request_key": "one"}),
    (RunCreate, {"content": "\ud800", "request_key": "one"}),
    (RunCreate, {"content": "hello", "request_key": True}),
    (RunRetry, {"request_key": "中文"}), (RunRetry, {"request_key": "with space"}),
])
def test_assistant_requests_reject_identity_policy_and_invalid_fields(model, raw):
    with pytest.raises(ValidationError):
        model.model_validate(raw)


def message(run_id, sequence, role, content):
    return SimpleNamespace(run_id=run_id, sequence=sequence, role=role, content=content)


def test_context_drops_whole_oldest_pairs_and_never_keeps_orphaned_messages():
    rows = [message(1, 1, "user", "old question"), message(1, 2, "assistant", "old answer"),
            message(2, 3, "user", "new question"), message(2, 4, "assistant", "new answer"),
            message(3, 5, "user", "orphaned"), message(4, 6, "assistant", "orphaned answer"),
            message(5, 7, "user", None), message(5, 8, "assistant", "redacted pair")]
    assert bounded_context(rows, turns=1, max_bytes=1000) == [
        {"role": "user", "content": "new question"}, {"role": "assistant", "content": "new answer"}]
    assert bounded_context(rows, turns=8, max_bytes=120) == [
        {"role": "user", "content": "new question"}, {"role": "assistant", "content": "new answer"}]
    assert bounded_context(rows, turns=8, max_bytes=1) == []


def test_context_budget_counts_utf8_bytes_and_keeps_a_complete_turn():
    rows = [message(1, 1, "user", "中" * 30), message(1, 2, "assistant", "文" * 30),
            message(2, 3, "user", "最新"), message(2, 4, "assistant", "回答")]
    value = bounded_context(rows, turns=8, max_bytes=220)
    assert value == [{"role": "user", "content": "最新"}, {"role": "assistant", "content": "回答"}]


def test_public_run_response_contains_no_session_or_lease_secrets():
    now = datetime(2030, 1, 1)
    row = SimpleNamespace(public_id=str(uuid4()), conversation_public_id=str(uuid4()),
        status="failed", reason="timeout", cancel_requested=False, model_calls=1, tool_calls=0,
        cost_limit=Decimal("0.1"), reserved=Decimal("0"), spent=Decimal("0.002"),
        budget_day=date(2030, 1, 1), create_time=now, started_at=now, finished_at=now,
        deadline_at=now, source_jti="private-login", source_exp=123, lease_token="private-lease",
        owner_id=42, auth_version=10, request_hash="private-hash")
    result = run_response(row)
    assert result["spent"] == "0.002" and result["created_at"].endswith("Z")
    assert not set(result) & {"source_jti", "source_exp", "lease_token", "auth_version", "request_hash", "owner_id"}
    assert "private" not in str(result)


def test_expired_conversation_metadata_does_not_reveal_title():
    row = SimpleNamespace(public_id=str(uuid4()), title="private title", state="active",
        expires_at=datetime(2029, 1, 1), active_run_id=None, create_time=datetime(2028, 1, 1),
        update_time=datetime(2028, 1, 1))
    result = conversation_response(row, now=datetime(2030, 1, 1))
    assert result["state"] == "expired" and "private" not in str(result)


def test_every_assistant_endpoint_requires_campus_bearer():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_exception_handler(BusinessException, business_exception_handler)

    async def no_database():
        yield None
    app.dependency_overrides[get_db] = no_database
    identity = str(uuid4())
    with TestClient(app) as client:
        for method, path, body in (("GET", "/conversations", None),
                ("POST", "/conversations", {"title": "one"}),
                ("GET", "/conversations/" + identity, None),
                ("PATCH", "/conversations/" + identity, {"title": "two"}),
                ("DELETE", "/conversations/" + identity, None),
                ("GET", "/conversations/" + identity + "/messages", None),
                ("POST", "/conversations/" + identity + "/runs", {"content": "hello", "request_key": "one"}),
                ("GET", "/conversations/" + identity + "/runs", None),
                ("GET", "/runs/" + identity, None),
                ("POST", "/runs/" + identity + "/cancel", None),
                ("POST", "/runs/" + identity + "/retry", {"request_key": "two"}),
                ("GET", "/budget", None), ("GET", "/alerts", None),
                ("POST", "/alerts/1/ack", None)):
            result = client.request(method, "/api/assistant" + path, json=body)
            assert result.status_code == 401, (method, path, result.status_code)


def test_invalid_assistant_policy_is_safe_and_budget_is_private(monkeypatch):
    from app.assistant import budget

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_exception_handler(BusinessException, business_exception_handler)
    actor = SimpleNamespace(id=42, role="student", status=1, auth_version=0)

    async def current_user(request: Request):
        request.state.token_payload = {"sub": "42"}
        return actor
    async def no_database():
        yield None
    async def snapshot(db, owner_id, day, **kwargs):
        assert owner_id == 42 and not kwargs["include_global"]
        return {"day": day.isoformat(), "currency": "CNY", "user": {"spent": "0"}}
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = no_database
    monkeypatch.setattr(budget, "snapshot", snapshot)
    with TestClient(app) as client:
        result = client.get("/api/assistant/budget")
        assert result.status_code == 200 and result.headers["Cache-Control"] == "private, no-store"
        assert result.json()["data"]["policy"]["retention_days"] == 7
        monkeypatch.setenv("CAMPUS_ASSISTANT_ENABLED", "invalid-private-setting")
        result = client.get("/api/assistant/budget")
        assert result.status_code == 503 and "invalid-private-setting" not in result.text
