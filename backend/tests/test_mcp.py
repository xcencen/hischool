"""Private delegation, strict tool contracts and HTTP boundary without services."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.common.exceptions import BusinessException
from app.config import Settings
from app.mcp.auth import decode_delegation, issue_delegation
from app.mcp.catalog import TOOLS, ToolOutcome
from app.mcp.settings import MCPSettings, load_mcp_settings
from app.utils.jwt import create_access_token


CAMPUS = Settings(database_url="mysql+asyncmy://test:unused@localhost/my_campus_test",
    redis_url="redis://localhost/15", jwt_secret="m2-campus-test-signing-key-" * 2)
PRIVATE = MCPSettings(signing_secret="m2-independent-service-signing-key-" * 2)


class FakeRedis:
    revoked = False

    async def exists(self, key):
        return self.revoked

    async def eval(self, *args):
        return 1

    async def aclose(self):
        pass


class FakeDatabase:
    def __init__(self):
        self.users = {42: SimpleNamespace(id=42, role="student", auth_version=0, status=1),
                      43: SimpleNamespace(id=43, role="teacher", auth_version=0, status=1)}

    @asynccontextmanager
    async def session_factory(self):
        users = self.users

        class Session:
            async def scalar(self, query):
                return users.get(query.compile().params["id_1"])
        yield Session()

    async def dispose(self):
        pass


def delegated(*, user_id=42, tools=None, database=None, redis=None, settings=PRIVATE):
    db, cache = database or FakeDatabase(), redis or FakeRedis()
    async def run():
        async with db.session_factory() as session:
            return await issue_delegation(session, cache, CAMPUS, settings,
                create_access_token(user_id, 0, CAMPUS), run_id=str(uuid4()),
                tools=tools or ["campus_get_my_schedules"])
    return asyncio.run(run())


def test_independent_settings_have_no_repr_secrets_and_no_defaults_for_key():
    assert PRIVATE.signing_secret not in repr(PRIVATE)
    assert PRIVATE.url not in repr(PRIVATE)
    with pytest.raises(ValueError):
        load_mcp_settings({})


@pytest.mark.parametrize("url", ["https://evil.test/mcp", "http://169.254.169.254:80/mcp",
    "http://campus-mcp:8001/mcp?token=private", "http://private:secret@campus-mcp:8001/mcp",
    "http://campus-mcp:8001/other", "http://campus-mcp.evil.test:8001/mcp"])
def test_client_endpoint_is_fixed_to_private_service_or_loopback(url):
    with pytest.raises(ValueError) as error:
        replace(PRIVATE, url=url)
    assert url not in str(error.value)


def test_delegation_is_short_lived_resource_bound_and_not_a_campus_token():
    value = delegated()
    claims = decode_delegation(value.token, PRIVATE)
    assert claims.exp - claims.iat <= 60 and claims.exp <= claims.source_exp
    assert claims.sub == "42" and claims.tools == ["campus_get_my_schedules"]
    assert jwt.get_unverified_header(value.token)["typ"] == "campus-mcp+jwt"
    assert value.token not in repr(value)
    with pytest.raises(BusinessException):
        decode_delegation(create_access_token(42, 0, CAMPUS), PRIVATE)


@pytest.mark.parametrize("changes", [
    {"aud": "my-campus-web"}, {"iss": "untrusted"}, {"exp": 1},
    {"sub": "43 OR 1=1"}, {"auth_version": "0"},
    {"tools": ["campus_register_activity"]}, {"tools": ["campus_get_my_schedules"] * 2},
    {"resource": "http://localhost:9999/mcp"}, {"run_id": "another-users-run"},
    {"role": "admin"}, {"source_exp": 1},
])
def test_modified_claims_are_rejected_without_detail_leaks(changes):
    token = delegated().token
    claims = decode_delegation(token, PRIVATE).model_dump()
    claims.update(changes)
    altered = jwt.encode(claims, PRIVATE.signing_secret, algorithm="HS256", headers={"typ": "campus-mcp+jwt"})
    with pytest.raises(BusinessException) as error:
        decode_delegation(altered, PRIVATE)
    assert PRIVATE.signing_secret not in str(error.value)


def test_issuer_checks_current_identity_and_rejects_shared_signing_secret():
    database = FakeDatabase()
    database.users[42].auth_version = 1
    with pytest.raises(BusinessException) as error:
        delegated(database=database)
    assert error.value.code == 401
    with pytest.raises(BusinessException):
        delegated(redis=SimpleNamespace(exists=_revoked))
    with pytest.raises(BusinessException) as error:
        delegated(settings=replace(PRIVATE, signing_secret=CAMPUS.jwt_secret))
    assert error.value.code == 503


async def _revoked(key):
    return True


@pytest.mark.parametrize("name,args", [
    ("campus_get_my_schedules", {"date": "2026-02-30"}),
    ("campus_get_my_schedules", {"date": "today", "user_id": 43}),
    ("campus_list_notices", {"admin": True}),
    ("campus_list_notices", {"page": True}),
    ("campus_list_activities", {"page_size": "5"}),
    ("campus_get_activity", {"activity_id": 1, "actor": {"role": "admin"}}),
    ("campus_get_notice", {"notice_id": False}),
    ("campus_search_knowledge", {"query": "hello", "top_k": 6}),
    ("campus_search_knowledge", {"query": "hello", "url": "http://evil.test"}),
])
def test_raw_arguments_cannot_override_identity_or_policy(name, args):
    with pytest.raises(ValidationError):
        TOOLS[name].arguments.model_validate(args)


def test_all_schemas_have_no_identity_fields_and_expose_only_read_tools():
    assert len(TOOLS) == 6
    for spec in TOOLS.values():
        schema = spec.arguments.model_json_schema()
        assert schema["additionalProperties"] is False
        assert not set(schema["properties"]) & {"user_id", "role", "actor", "admin", "own_only", "token"}


def test_failure_envelope_cannot_smuggle_business_data_or_external_citations():
    from app.mcp.executor import outcome
    value = outcome("campus_get_notice", reason="not_found")
    assert not value["ok"] and value["data"] is None and value["citations"] == []
    with pytest.raises(ValidationError):
        ToolOutcome.model_validate({**value, "data": {"password": "private"}})


def test_executor_sanitizes_dependency_failure_and_propagates_cancellation(monkeypatch, caplog):
    from redis.exceptions import ConnectionError
    from app.mcp.executor import ToolExecutor
    from app.mcp.runtime import MCPResources

    database, cache = FakeDatabase(), FakeRedis()
    token = delegated(database=database, redis=cache).token
    executor = ToolExecutor(MCPResources(database, cache, None), PRIVATE)

    async def failed_limit(*args, **kwargs):
        raise ConnectionError("private-redis-connection")
    monkeypatch.setattr(cache, "eval", failed_limit)
    result = asyncio.run(executor.execute("campus_get_my_schedules", {}, token))
    assert result["reason"] == "unavailable" and result["data"] is None
    assert "private-redis-connection" not in str(result) + caplog.text

    async def allowed(*args, **kwargs):
        return 1
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(cache, "eval", allowed)
    monkeypatch.setattr(executor, "_query", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor.execute("campus_get_my_schedules", {}, token))


def test_http_boundary_and_real_sdk_messages(monkeypatch):
    pytest.importorskip("fastmcp", reason="Requires optional assistant profile")
    from fastapi.testclient import TestClient
    from app.mcp.executor import ToolExecutor
    from app.mcp.runtime import MCPResources
    from app.mcp.server import create_app

    database, cache = FakeDatabase(), FakeRedis()
    called = []

    async def query(self, db, name, args, user):
        called.append(user.id)
        return dict(start_date="2030-01-07", end_date="2030-01-07", timezone="Asia/Shanghai",
                    items=[], truncated=False), []
    monkeypatch.setattr(ToolExecutor, "_query", query)
    token = delegated(database=database, redis=cache).token
    app = create_app(PRIVATE, resources_factory=lambda: MCPResources(database, cache, None))
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}
    with TestClient(app, base_url="http://campus-mcp:8001") as client:
        assert client.get("/health").status_code == 200
        assert client.post("/mcp", json={}).status_code == 401
        assert client.post("/mcp", json={}, headers={**headers, "Origin": "https://evil.test"}).status_code == 403
        assert client.post("/mcp", json={}, headers={**headers, "Host": "evil.test"}).status_code == 403
        assert client.post("/mcp", json={}, headers=headers).status_code == 400
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "m2-test", "version": "1"}}}
        initialized = client.post("/mcp", json=initialize, headers=headers)
        assert initialized.status_code == 200
        assert initialized.json()["result"]["capabilities"] == {"tools": {"listChanged": False}}
        rpc = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        tools = client.post("/mcp", json=rpc, headers=headers).json()["result"]["tools"]
        assert [tool["name"] for tool in tools] == ["campus_get_my_schedules"]
        assert tools[0]["annotations"]["readOnlyHint"] is True
        call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "campus_get_my_schedules", "arguments": {"date": "2030-01-07"}}}
        response = client.post("/mcp", json=call, headers=headers)
        assert response.status_code == 200
        assert response.json()["result"]["structuredContent"]["ok"]
        assert called == [42]
        call["params"]["arguments"]["ctx"] = {"user_id": 43}
        value = client.post("/mcp", json=call, headers=headers).json()["result"]["structuredContent"]
        assert value["reason"] == "invalid_arguments" and called == [42]
        assert client.post("/mcp", json={**call, "params": {**call["params"], "task": {"ttl": 1000}}},
                           headers=headers).status_code == 400
        call["params"]["name"] = "campus_register_activity"
        assert client.post("/mcp", json=call, headers=headers).json()["result"]["structuredContent"]["reason"] == "unknown_tool"
        cache.revoked = True
        assert client.post("/mcp", json=initialize, headers=headers).status_code == 401
