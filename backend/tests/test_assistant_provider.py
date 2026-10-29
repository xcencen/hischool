"""Actual pinned SDK wire behavior with HTTP substitutes and private logging."""

import asyncio
from dataclasses import asdict, replace
from decimal import Decimal
import json
import logging

import httpx
import pytest

pytest.importorskip("langchain_openai", reason="Requires optional assistant profile")

from app.ai.pricing import PriceTable
from app.ai.settings import LLMSettings, MODEL_ID
from app.assistant.providers import (ChatProvider, MAX_RESPONSE_BYTES, PROTOCOL_TOKEN_ALLOWANCE,
    ProviderFailure, encoded_size, tool_schemas)


SETTINGS = LLMSettings(api_key="private-model-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
PRICES = PriceTable(Decimal("2"), Decimal("8"), Decimal("0.2"), "test-version", "test-only")
MESSAGES = [{"role":"system", "content":"test policy"}, {"role":"user", "content":"private-query"}]


def response(*, usage=None, reasoning=None, model=MODEL_ID, tool_calls=None):
    return {"id":"synthetic", "object":"chat.completion", "created":1, "model":model,
        "choices":[{"index":0, "finish_reason":"tool_calls" if tool_calls else "stop",
        "message":{"role":"assistant", "content":"Synthetic answer", **({"tool_calls":tool_calls} if tool_calls else {}),
        **({"reasoning_content":reasoning} if reasoning else {})}}],
        **({"usage":usage} if usage is not None else {})}


def provider(handler, **kwargs):
    return ChatProvider(SETTINGS, PRICES, transport_factory=lambda: httpx.MockTransport(handler), **kwargs)


def test_complete_uses_approved_wire_schema_and_keeps_only_safe_metadata(caplog):
    caplog.set_level(logging.DEBUG)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response(usage={"prompt_tokens":100, "completion_tokens":20,
            "prompt_tokens_details":{"cached_tokens":10}, "completion_tokens_details":{"reasoning_tokens":5}},
            reasoning="private-reasoning-text"))
    target = provider(handle)
    reply = asyncio.run(target.complete(MESSAGES))
    sent = json.loads(calls[0].content)
    assert sent["model"] == MODEL_ID and sent["max_tokens"] == 2048
    assert "max_completion_tokens" not in sent and len(sent["tools"]) == 6
    assert all(item["function"]["parameters"]["additionalProperties"] is False for item in sent["tools"])
    assert len(calls) == 1 and reply.reasoning_observed
    assert reply.usage == {"input_tokens":100, "output_tokens":20, "input_token_details":{"cache_read":10},
                           "output_token_details":{"reasoning":5}}
    safe = json.dumps(asdict(reply)) + caplog.text + repr(reply)
    assert "private-query" not in safe and "private-model-key" not in safe and "private-reasoning-text" not in safe
    logging.getLogger("httpx").info("unrelated-request-visible")
    assert "unrelated-request-visible" in caplog.text


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens":10}, {"completion_tokens":2},
    {"prompt_tokens":None, "completion_tokens":2}, {"prompt_tokens":10, "completion_tokens":None},
    {"prompt_tokens":10, "completion_tokens":2,"prompt_tokens_details":{"cached_tokens":999}}])
def test_partial_or_absent_wire_usage_stays_unknown_instead_of_sdk_zeroes(usage):
    target = provider(lambda request: httpx.Response(200, json=response(usage=usage)))
    reply = asyncio.run(target.complete(MESSAGES))
    assert reply.usage is None


def test_conservative_reservation_uses_full_utf8_input_and_output_ceiling():
    target = provider(lambda request: pytest.fail("Estimate must not connect"))
    size = encoded_size({"messages":MESSAGES, "tools":tool_schemas()}) + PROTOCOL_TOKEN_ALLOWANCE
    assert target.input_upper_bound(MESSAGES) == size
    raw = (Decimal(size) * Decimal("2") + Decimal(2048) * Decimal("8")) / Decimal(1_000_000)
    assert target.estimate(MESSAGES) >= raw
    assert target.estimate(MESSAGES) - raw < Decimal("0.00000001")
    with pytest.raises(ProviderFailure) as error:
        target.estimate([{"role":"user", "content":"x" * 50000}])
    assert error.value.reason == "context_limit" and not error.value.uncertain


@pytest.mark.parametrize("status,reason,retryable,uncertain", [
    (429, "rate_limited", True, False), (401, "provider_auth", False, False),
    (403, "provider_auth", False, False), (500, "upstream", False, True),
    (503, "upstream", False, True), (307, "unavailable", False, True),
])
def test_http_failures_are_sanitized_and_never_automatically_replayed(status, reason, retryable, uncertain, caplog):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location":"https://evil.test/private"},
            json={"error":{"message":"private-provider-body", "type":"upstream", "code":"test"}})
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(provider(handle).complete(MESSAGES))
    assert (error.value.reason,error.value.retryable,error.value.uncertain) == (reason,retryable,uncertain)
    assert len(calls) == 1 and calls[0].url.host == "dashscope.aliyuncs.com"
    assert "private-provider-body" not in str(error.value) + caplog.text


def test_unknown_model_or_oversized_response_is_rejected_without_echoing_body():
    for payload in (response(model="private-other-model"), {"large":"x" * MAX_RESPONSE_BYTES}):
        with pytest.raises(ProviderFailure) as error:
            asyncio.run(provider(lambda request: httpx.Response(200, json=payload)).complete(MESSAGES))
        assert error.value.reason in {"model_mismatch", "invalid_response"}
        assert "private-other-model" not in str(error.value)


def test_timeout_is_uncertain_and_cancellation_propagates():
    def timeout(request):
        raise httpx.ReadTimeout("private-timeout")
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(provider(timeout).complete(MESSAGES))
    assert error.value.reason == "timeout" and error.value.uncertain
    async def cancelled(request):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider(cancelled).complete(MESSAGES))


def test_actual_task_cancel_and_overall_deadline_remain_distinct():
    async def run():
        entered = asyncio.Event()
        async def pending(request):
            entered.set()
            await asyncio.sleep(5)
            return httpx.Response(200, json=response())
        target = provider(pending)
        task = asyncio.create_task(target.complete(MESSAGES))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        bounded = ChatProvider(replace(SETTINGS, timeout_s=1), PRICES,
            transport_factory=lambda: httpx.MockTransport(pending))
        with pytest.raises(ProviderFailure) as error:
            await bounded.complete(MESSAGES)
        assert error.value.reason == "timeout" and error.value.uncertain
    asyncio.run(run())


@pytest.mark.parametrize("name", ["LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING",
                                 "LANGCHAIN_VERBOSE", "OPENAI_LOG"])
def test_tracing_is_refused_before_estimation_or_network(name, monkeypatch):
    monkeypatch.setenv(name, "true")
    with pytest.raises(ProviderFailure) as error:
        provider(lambda request: pytest.fail("Unexpected model request")).estimate(MESSAGES)
    assert error.value.reason == "tracing_enabled" and not error.value.uncertain


def test_python_debug_and_tracing_context_are_also_refused():
    from langchain_core.globals import get_debug, set_debug
    from langsmith.run_helpers import tracing_context
    old = get_debug()
    try:
        set_debug(True)
        with pytest.raises(ProviderFailure, match="model request failed"):
            provider(lambda request: pytest.fail("Unexpected model request")).estimate(MESSAGES)
    finally:
        set_debug(old)
    with tracing_context(enabled=True):
        with pytest.raises(ProviderFailure) as error:
            provider(lambda request: pytest.fail("Unexpected model request")).estimate(MESSAGES)
        assert error.value.reason == "tracing_enabled"


def test_function_calls_are_returned_for_graph_validation_without_sdk_side_effects():
    calls = [{"id":"call_one", "type":"function", "function":{"name":"campus_get_notice",
               "arguments":json.dumps({"notice_id":1,"user_id":999})}}]
    reply = asyncio.run(provider(lambda request: httpx.Response(200, json=response(tool_calls=calls))).complete(MESSAGES))
    assert reply.tool_calls[0].arguments == {"notice_id":1,"user_id":999}
    assert reply.usage is None


def test_owned_transport_is_closed_after_success():
    closed = []
    class Owned(httpx.MockTransport):
        async def aclose(self):
            closed.append(True)
    target = ChatProvider(SETTINGS, PRICES, transport_factory=lambda: Owned(
        lambda request: httpx.Response(200,json=response())))
    asyncio.run(target.complete(MESSAGES))
    asyncio.run(target.aclose())
    assert closed == [True]
