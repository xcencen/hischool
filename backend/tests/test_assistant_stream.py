"""SSE framing, bounded replay and failure behavior without inference or I/O."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.assistant import stream
from app.assistant.settings import AssistantSettings
from app.common.exceptions import BusinessException


class Request:
    async def is_disconnected(self):
        return False


class Lease:
    def __init__(self):
        self.renewals, self.closed = 0, False

    async def renew(self):
        self.renewals += 1

    async def close(self):
        self.closed = True


def terminal(content="校园🙂" * 60):
    return {"id": "synthetic-run", "status": "succeeded", "model_calls": 1}, {
        "id": 1, "sequence": 2, "run_id": "synthetic-run", "role": "assistant", "content": content,
        "citations": [], "redacted": False, "created_at": "2026-10-30T00:00:00Z"}


def decode(block):
    lines = block.decode().strip().splitlines()
    data = next((json.loads(line[6:]) for line in lines if line.startswith("data: ")), None)
    name = next((line[7:] for line in lines if line.startswith("event: ")), None)
    identifier = next((int(line[4:]) for line in lines if line.startswith("id: ")), None)
    return name, data, identifier


@pytest.fixture(autouse=True)
def fast_segments(monkeypatch):
    monkeypatch.setattr(stream, "CHUNK_INTERVAL", 0)
    monkeypatch.setattr(stream, "POLL_SECONDS", 0)


def test_sse_json_framing_keeps_untrusted_newlines_inside_data():
    block = stream.event("delta", {"text": "第一行\nevent: injected\n\rdata: secret🙂"}, identifier=2)
    assert decode(block) == ("delta", {"text": "第一行\nevent: injected\n\rdata: secret🙂"}, 2)
    assert block.count(b"\nevent:") == 1 and block.endswith(b"\n\n")


@pytest.mark.parametrize("payload", [{}, {"sub": "1", "auth_version": True, "jti": "a", "exp": 1},
    {"sub": "-1", "auth_version": 0, "jti": "a", "exp": 1},
    {"sub": "１２", "auth_version": 0, "jti": "a", "exp": 1},
    {"sub": "1", "auth_version": 0, "jti": "", "exp": 1},
    {"sub": "1", "auth_version": 0, "jti": "a", "exp": True}])
def test_invalid_identity_is_controlled_and_contains_no_claim_values(payload):
    with pytest.raises(BusinessException) as error:
        stream.Identity.from_payload(payload)
    assert error.value.code == 401


def test_identity_keeps_only_required_claims_and_hides_session_identifier():
    value = stream.Identity.from_payload({"sub": "1", "auth_version": 2, "jti": "private-login", "exp": 42,
                                          "unused": "private-user-input"})
    assert value.user_id == 1 and value.auth_version == 2
    assert "private" not in repr(value)


def test_completed_answer_segments_preserve_unicode_and_authoritative_message():
    async def run():
        state, lease = terminal(), Lease()
        async def load():
            return deepcopy(state)
        blocks = [decode(value) async for value in stream.events(Request(), load, lease, after=0, max_duration=5)]
        assert blocks[0] == ("status", {"run": state[0]}, None)
        pieces = [value for name, value, _ in blocks if name == "delta"]
        assert "".join(value["text"] for value in pieces) == state[1]["content"]
        assert [value["sequence"] for value in pieces] == list(range(1, len(pieces)+1))
        assert all(len(value["text"]) <= 64 for value in pieces)
        assert [identifier for name, _, identifier in blocks if name == "delta"] == list(range(1, len(pieces)+1))
        assert blocks[-1] == ("done", {"run": state[0], "message": state[1]}, None)
        assert lease.closed and lease.renewals >= len(pieces) + 2
    asyncio.run(run())


def test_reconnect_cursor_replays_only_remaining_segments_without_new_inference():
    async def run():
        state, lease = terminal("中"*130), Lease()
        async def load():
            return deepcopy(state)
        blocks = [decode(value) async for value in stream.events(Request(), load, lease, after=2, max_duration=5)]
        assert [(data["text"], identifier) for name, data, identifier in blocks if name == "delta"] == [("中中", 3)]
        assert blocks[-1][0] == "done" and lease.closed
    asyncio.run(run())


def test_waiting_run_reports_state_before_answer_and_failed_run_has_no_body():
    async def run():
        lease, observed = Lease(), 0
        async def load():
            nonlocal observed
            observed += 1
            if observed == 1:
                return {"id": "x", "status": "queued", "model_calls": 0}, None
            return {"id": "x", "status": "failed", "reason": "timeout", "model_calls": 1}, None
        blocks = [decode(value) async for value in stream.events(Request(), load, lease, after=0, max_duration=5)]
        assert [name for name, _, _ in blocks] == ["status", "status", "done"]
        assert blocks[-1][1]["message"] is None and lease.closed
    asyncio.run(run())


@pytest.mark.parametrize("code,reason", [(401,"unauthenticated"),(404,"not_found"),(410,"expired"),(503,"unavailable")])
def test_revocation_or_retention_between_segments_closes_and_discards_rest(code, reason):
    async def run():
        state, lease, reads = terminal("x"*130), Lease(), 0
        async def load():
            nonlocal reads
            reads += 1
            if reads >= 3:
                raise BusinessException("private-error-and-body", code=code)
            return deepcopy(state)
        blocks = [decode(value) async for value in stream.events(Request(), load, lease, after=0, max_duration=5)]
        assert [name for name, _, _ in blocks] == ["status", "delta", "error"]
        assert blocks[-1][1] == {"reason": reason} and lease.closed
        assert "private" not in repr(blocks)
    asyncio.run(run())


def test_deleted_or_changed_reply_cannot_replace_answer_mid_stream():
    async def run():
        lease, reads = Lease(), 0
        async def load():
            nonlocal reads
            reads += 1
            return terminal("x"*130 if reads == 1 else "private-changed-body")
        blocks = [decode(value) async for value in stream.events(Request(), load, lease, after=0, max_duration=5)]
        assert [name for name, _, _ in blocks] == ["status", "error"] and lease.closed
        assert "private-changed-body" not in repr(blocks)
    asyncio.run(run())


def test_disconnect_releases_connection_without_reading_more_body():
    async def run():
        lease = Lease()
        class Disconnected:
            async def is_disconnected(self):
                return True
        async def load():
            raise AssertionError("Disconnected request must not query a reply")
        assert not [value async for value in stream.events(Disconnected(), load, lease, after=0, max_duration=5)]
        assert lease.closed
    asyncio.run(run())


def test_cancelled_stream_propagates_cancellation_and_releases_lease():
    async def run():
        lease = Lease()
        async def load():
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            async for _ in stream.events(Request(), load, lease, after=0, max_duration=5):
                pass
        assert lease.closed
    asyncio.run(run())


def test_failure_after_headers_has_only_safe_error_reason():
    async def run():
        lease = Lease()
        async def load():
            raise RuntimeError("private-connection-string")
        blocks = [decode(value) async for value in stream.events(Request(), load, lease, after=0, max_duration=5)]
        assert blocks == [("error", {"reason":"unavailable"}, None)] and lease.closed
    asyncio.run(run())


def test_connection_duration_is_bounded(monkeypatch):
    async def run():
        lease = Lease()
        async def load():
            return {"id":"x", "status":"running"}, None
        blocks = [decode(value) async for value in stream.events(Request(), load, lease, after=0, max_duration=0)]
        assert blocks == [("error", {"reason":"unavailable"}, None)] and lease.closed
    asyncio.run(run())


class Redis:
    def __init__(self):
        self.calls = []
    async def eval(self, *arguments):
        self.calls.append(arguments)
        return 1


def test_open_validates_before_headers_and_sets_proxy_and_cache_policy(monkeypatch):
    async def run():
        cache, observed = Redis(), []
        async def load(*args):
            observed.append(args[-1])
            return terminal("Hello")
        monkeypatch.setattr(stream, "snapshot", load)
        result = await stream.open_stream(Request(), object(), cache, AssistantSettings(), "run",
            {"sub":"1","auth_version":0,"jti":"private-login","exp":42}, after=0)
        assert result.status_code == 200 and result.media_type == "text/event-stream"
        assert result.headers["cache-control"] == "private, no-store, no-transform"
        assert result.headers["x-accel-buffering"] == "no"
        assert observed[0].user_id == 1 and "private-login" not in repr(cache.calls)
        blocks = [decode(value) async for value in result.body_iterator]
        assert blocks[-1][0] == "done"
        await result.background()
    asyncio.run(run())


@pytest.mark.parametrize("cursor", [-1, 251, True, "1"])
def test_bad_cursor_does_not_open_connection(cursor):
    async def run():
        cache = Redis()
        with pytest.raises(BusinessException) as error:
            await stream.open_stream(Request(), object(), cache, AssistantSettings(), "run", {}, after=cursor)
        assert error.value.code == 422 and not cache.calls
    asyncio.run(run())


def test_initial_owner_error_is_http_failure_and_does_not_consume_capacity(monkeypatch):
    async def run():
        cache = Redis()
        async def load(*args):
            raise BusinessException("运行不存在", code=404)
        monkeypatch.setattr(stream, "snapshot", load)
        with pytest.raises(BusinessException) as error:
            await stream.open_stream(Request(), object(), cache, AssistantSettings(), "run",
                {"sub":"1","auth_version":0,"jti":"private-login","exp":42})
        assert error.value.code == 404 and not cache.calls
    asyncio.run(run())
