"""Actual MCP SDK over ASGI plus hostile-response boundary checks."""

import asyncio
import json
import logging
from uuid import uuid4

import httpx
import pytest

pytest.importorskip("fastmcp", reason="Requires optional assistant profile")

from app.mcp.auth import decode_delegation
from app.mcp.client import BoundedTransport, CampusMCPClient, MAX_WIRE_BYTES, PrivateTransportError, guard_response
from app.mcp.executor import ToolExecutor, outcome
from app.mcp.runtime import MCPResources
from app.mcp.server import create_app, valid_rpc
from app.utils.jwt import create_access_token
from test_mcp import CAMPUS, PRIVATE, FakeDatabase, FakeRedis


def test_sdk_roundtrip_and_concurrent_identities_do_not_share_tokens(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    async def query(self, db, name, args, user):
        await asyncio.sleep(0.01)
        return dict(start_date="2030-01-07", end_date="2030-01-07", timezone="Asia/Shanghai",
            items=[dict(id=user.id, course_id=1, course_name="owner-"+str(user.id), course_code="TEST",
                class_date="2030-01-07", start_time="08:00:00", end_time="09:00:00", period="1", location="test")],
            truncated=False), []
    monkeypatch.setattr(ToolExecutor, "_query", query)

    async def run():
        database, cache = FakeDatabase(), FakeRedis()
        app = create_app(PRIVATE, resources_factory=lambda: MCPResources(database, cache, None))
        observations = []

        class Observe(httpx.ASGITransport):
            async def handle_async_request(self, request):
                claims = decode_delegation(request.headers["Authorization"][7:], PRIVATE)
                observations.append((claims.sub, claims.run_id, tuple(claims.tools)))
                return await super().handle_async_request(request)

        async with app.inner.router.lifespan_context(app.inner):
            async def call(user_id):
                client = CampusMCPClient(CAMPUS, PRIVATE, database, cache,
                    transport_factory=lambda: Observe(app=app))
                token = create_access_token(user_id, 0, CAMPUS)
                return await client.call("campus_get_my_schedules", {"date": "2030-01-07"},
                    campus_token=token, run_id=str(uuid4()))
            first, second = await asyncio.gather(call(42), call(43))
        assert first["ok"] and second["ok"], (first, second)
        assert first["data"]["items"][0]["course_name"] == "owner-42"
        assert second["data"]["items"][0]["course_name"] == "owner-43"
        assert {row[0] for row in observations} == {"42", "43"}
        assert all(row[2] == ("campus_get_my_schedules",) for row in observations)
    asyncio.run(run())
    assert "owner-42" not in caplog.text and "Sending client message" not in caplog.text
    logging.getLogger("httpx").info("unrelated-request-visible")
    assert "unrelated-request-visible" in caplog.text


@pytest.mark.parametrize("status", [302, 307, 308, 401, 500])
def test_redirects_and_internal_errors_never_forward_credentials_or_bodies(status, caplog):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "http://evil.test/private"},
                              text="private-provider-body")

    async def run():
        client = CampusMCPClient(CAMPUS, PRIVATE, FakeDatabase(), FakeRedis(),
                                transport_factory=lambda: httpx.MockTransport(respond))
        return await client.call("campus_get_my_schedules", {},
            campus_token=create_access_token(42, 0, CAMPUS), run_id=str(uuid4()))
    result = asyncio.run(run())
    assert not result["ok"] and result["reason"] == "unavailable"
    assert len(calls) == 1 and calls[0].url.host == "campus-mcp"
    assert "private-provider-body" not in json.dumps(result) + caplog.text


def test_oversized_response_is_bounded_even_for_already_buffered_transports():
    async def run():
        async with httpx.AsyncClient(transport=BoundedTransport(httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * (MAX_WIRE_BYTES + 1))))) as client:
            with pytest.raises(PrivateTransportError):
                await client.get("http://campus-mcp:8001/mcp")
    asyncio.run(run())


def test_malformed_or_untrusted_structured_result_is_sanitized():
    response = httpx.Response(200, request=httpx.Request("POST", PRIVATE.url,
        json={"method": "tools/call"}), json={"jsonrpc": "2.0", "id": 1, "result": {
            "content": [], "structuredContent": {**outcome("campus_get_notice", reason="not_found"),
            "data": {"password": "private-result"}}}})
    with pytest.raises(PrivateTransportError) as error:
        asyncio.run(guard_response(response))
    assert "private-result" not in str(error.value)


@pytest.mark.parametrize("method", [None, [], {}, "resources/read", "prompts/get", "tasks/list"])
def test_rpc_boundary_rejects_unadvertised_or_malformed_methods(method):
    assert not valid_rpc({"jsonrpc": "2.0", "id": 1, "method": method})


def test_client_rejects_invalid_arguments_before_minting_or_network(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(database, "session_factory", lambda: pytest.fail("Unexpected identity/network work"))
    client = CampusMCPClient(CAMPUS, PRIVATE, database, FakeRedis())
    result = asyncio.run(client.call("campus_get_activity", {"activity_id": 1, "user_id": 43},
        campus_token="not-a-token", run_id=str(uuid4())))
    assert result["reason"] == "invalid_arguments"
