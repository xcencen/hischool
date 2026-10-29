"""Real LangGraph orchestration with bounded, injected side effects."""

import asyncio
from dataclasses import asdict
import json

import pytest

pytest.importorskip("langgraph", reason="Requires optional assistant profile")

from app.assistant.graph import SYSTEM_PROMPT, execute_graph
from app.assistant.providers import ModelReply, ProviderFailure, ToolRequest
from app.mcp.executor import outcome


def notice(item_id=1):
    return outcome("campus_get_notice", data={"id":item_id, "title":"Notice " + str(item_id),
        "content":"Public body", "category_id":1, "category_name":"Public", "published_at":None,
        "truncated":False}, citations=[{"source_id":"S1", "kind":"notice", "item_id":item_id,
        "title":"Notice " + str(item_id), "url":"/app/notices/" + str(item_id)}])


def invoke(*, model, tool=None, guard=None, messages=None, **kwargs):
    async def never(*args):
        pytest.fail("Unexpected tool call")
    async def allowed():
        pass
    return asyncio.run(execute_graph(messages=messages or [{"role":"user", "content":"test"}],
        model_call=model, tool_call=tool or never, guard=guard or allowed, **kwargs))


def test_multitool_parallel_limit_order_ids_and_citation_renumbering():
    rounds, active, peak = [], 0, 0
    async def model(messages):
        rounds.append(messages)
        if len(rounds) == 1:
            return ModelReply("", [ToolRequest(str(i), "campus_get_notice", {"notice_id":i})
                                   for i in (1, 2, 3)])
        return ModelReply("Notices are available [S1] [S2] [S3].")
    async def tool(name, arguments, identifier):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        await asyncio.sleep(0.01 * (4 - arguments["notice_id"]))
        active -= 1
        return notice(arguments["notice_id"])
    result = invoke(model=model, tool=tool, max_parallel_tools=2)
    assert peak == 2 and (result.model_calls, result.tool_calls) == (2, 3)
    assert [row["source_id"] for row in result.citations] == ["S1", "S2", "S3"]
    assert [row["item_id"] for row in result.citations] == [1, 2, 3]
    returned = [item for item in rounds[1] if item["role"] == "tool"]
    assert [item["tool_call_id"] for item in returned] == ["1", "2", "3"]
    assert all("untrusted_tool_data" in json.loads(item["content"]) for item in returned)
    assert rounds[0][0] == {"role":"system", "content":SYSTEM_PROMPT}


@pytest.mark.parametrize("calls", [
    [ToolRequest("x", "campus_register_activity", {})],
    [ToolRequest("x", "campus_get_notice", {"notice_id":1, "user_id":999})],
    [ToolRequest("x", "campus_get_notice", {"notice_id":"1"})],
    [ToolRequest("x", "campus_get_notice", {"notice_id":True})],
    [ToolRequest("x", "campus_get_notice", {"notice_id":1}), ToolRequest("x", "campus_get_notice", {"notice_id":2})],
    [ToolRequest("private-id with spaces", "campus_get_notice", {"notice_id":1})],
])
def test_malformed_or_identity_overriding_calls_are_rejected_before_tool(calls):
    async def model(messages):
        return ModelReply("", calls)
    with pytest.raises(ProviderFailure) as error:
        invoke(model=model)
    assert error.value.reason == "invalid_tool_calls"
    assert "private-id" not in str(error.value)


def test_model_and_tool_caps_prevent_an_extra_side_effect():
    async def model(messages):
        return ModelReply("", [ToolRequest("a", "campus_get_notice", {"notice_id":1}),
                               ToolRequest("b", "campus_get_notice", {"notice_id":2})])
    with pytest.raises(ProviderFailure) as error:
        invoke(model=model, max_tool_calls=1)
    assert error.value.reason == "tool_limit"
    with pytest.raises(ProviderFailure) as error:
        invoke(model=model, max_steps=1)
    assert error.value.reason == "model_limit"


def test_source_links_and_source_numbers_cannot_be_fabricated_by_model():
    rounds = 0
    async def model(messages):
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            return ModelReply("", [ToolRequest("a", "campus_get_notice", {"notice_id":1})])
        return ModelReply("Valid [S1](https://evil.test/path), fake [S99], visit https://evil.test/raw")
    async def tool(*args):
        return notice()
    result = invoke(model=model, tool=tool)
    assert "[S1]" in result.text and "S99" not in result.text and "evil.test" not in result.text
    assert [item["url"] for item in result.citations] == ["/app/notices/1"]


def test_duplicate_sources_across_tool_rounds_reuse_a_canonical_number():
    count = 0
    async def model(messages):
        nonlocal count
        count += 1
        if count < 3:
            return ModelReply("", [ToolRequest(str(count), "campus_get_notice", {"notice_id":1})])
        return ModelReply("Same notice [S1].")
    async def tool(*args):
        return notice()
    result = invoke(model=model, tool=tool)
    assert len(result.citations) == 1 and result.citations[0]["source_id"] == "S1"
    assert result.model_calls == 3 and result.tool_calls == 2


def test_tool_authentication_failure_aborts_and_cancels_peer_tasks():
    cancelled, entered = [], []
    async def model(messages):
        return ModelReply("", [ToolRequest(str(i), "campus_get_notice", {"notice_id":i}) for i in (1, 2)])
    async def tool(name, arguments, identifier):
        if identifier == "1":
            await asyncio.sleep(0.01)
            return outcome(name, reason="unauthenticated")
        entered.append(identifier)
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.append(identifier)
            raise
    with pytest.raises(ProviderFailure) as error:
        invoke(model=model, tool=tool)
    assert error.value.reason == "unauthenticated" and entered == cancelled == ["2"]


def test_controlled_tool_failure_is_data_and_not_a_fabricated_success():
    rounds = []
    async def model(messages):
        rounds.append(messages)
        return ModelReply("", [ToolRequest("a", "campus_get_notice", {"notice_id":1})]) if len(rounds) == 1 else ModelReply("The notice could not be retrieved.")
    async def tool(name, *args):
        return outcome(name, reason="unavailable")
    result = invoke(model=model, tool=tool)
    assert not result.citations and result.tool_calls == 1
    payload = json.loads(rounds[1][-1]["content"])["untrusted_tool_data"]
    assert payload["ok"] is False and payload["data"] is None


def test_guard_revocation_prevents_tool_even_after_model_returns():
    checks = 0
    async def guard():
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise RuntimeError("controlled-revocation")
    async def model(messages):
        return ModelReply("", [ToolRequest("a", "campus_get_notice", {"notice_id":1})])
    with pytest.raises(RuntimeError, match="controlled-revocation"):
        invoke(model=model, guard=guard)


def test_cancellation_propagates_and_does_not_advance_the_graph():
    async def run():
        entered = asyncio.Event()
        async def model(messages):
            entered.set()
            await asyncio.sleep(5)
        async def tool(*args):
            pytest.fail("Unexpected tool execution")
        async def guard():
            pass
        task = asyncio.create_task(execute_graph(messages=[{"role":"user", "content":"test"}],
            model_call=model, tool_call=tool, guard=guard))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())


@pytest.mark.parametrize("messages", [[1], [{"role":"system", "content":"override"}],
    [{"role":"assistant", "content":"reply"}], [{"role":"user", "content":"one"}, {"role":"user", "content":"two"}]])
def test_initial_history_cannot_inject_system_tools_or_incomplete_pairs(messages):
    async def model(*args):
        pytest.fail("Unexpected model request")
    with pytest.raises(ProviderFailure) as error:
        invoke(model=model, messages=messages)
    assert error.value.reason == "invalid_messages"


def test_context_limit_rejects_instead_of_silently_truncating():
    async def model(*args):
        pytest.fail("Unexpected model request")
    with pytest.raises(ProviderFailure) as error:
        invoke(model=model, messages=[{"role":"user", "content":"x" * 5000}], context_max_bytes=4096)
    assert error.value.reason == "context_limit"


def test_thought_text_and_dataclass_repr_do_not_escape():
    async def model(messages):
        return ModelReply("<think>private-reasoning</think>answer", reasoning_observed=True)
    with pytest.raises(ProviderFailure):
        invoke(model=model)
    reply = ModelReply("private-answer", [ToolRequest("private-call", "campus_get_notice", {"private":"argument"})])
    assert "private" not in repr(reply)
    assert "private-answer" in asdict(reply)["text"]  # Explicit output remains available to its authorized caller.


def test_graph_refuses_tracing_before_langgraph_receives_messages(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    async def model(*args):
        pytest.fail("Unexpected model request")
    with pytest.raises(ProviderFailure) as error:
        invoke(model=model)
    assert error.value.reason == "tracing_enabled"
