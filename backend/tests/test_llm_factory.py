"""Verify the real LangChain HTTP payload and streaming contract without a model."""

import asyncio
from dataclasses import replace
import json

import httpx
import pytest

pytest.importorskip("langchain_openai", reason="Install requirements-assistant-dev.txt for M1 SDK tests")

from app.ai.factory import get_chat_model
from app.ai.registry import MODEL_REGISTRY
from app.ai.settings import LLMSettings, MODEL_ID


def settings(**changes):
    return replace(LLMSettings(api_key="synthetic-test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"), **changes)


def test_factory_requires_explicit_configuration_and_role():
    with pytest.raises(ValueError):
        get_chat_model(settings=LLMSettings())
    with pytest.raises(ValueError):
        get_chat_model("unapproved-role", settings=settings())


def test_factory_refuses_model_without_tool_capability(monkeypatch):
    spec = MODEL_REGISTRY[MODEL_ID]
    monkeypatch.setitem(MODEL_REGISTRY, MODEL_ID, replace(
        spec, capabilities=replace(spec.capabilities, tools=False)))
    with pytest.raises(ValueError, match="does not support tools"):
        get_chat_model(settings=settings())


@pytest.mark.parametrize("thinking", [False, True])
def test_thinking_and_limits_are_sent_in_actual_http_body(thinking):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion",
            "created": 1, "model": MODEL_ID, "choices": [{"index": 0,
            "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            model = get_chat_model(settings=settings(enable_thinking=thinking), http_async_client=transport)
            try:
                result = await model.ainvoke("synthetic test only")
                assert result.usage_metadata["input_tokens"] == 10
                assert result.response_metadata["model_name"] == MODEL_ID
                assert model.max_retries == 0
            finally:
                await model.root_async_client.close()
                model.root_client.close()

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0]["model"] == MODEL_ID
    assert requests[0]["enable_thinking"] is thinking
    assert requests[0]["max_tokens"] == 2048
    assert "extra_body" not in requests[0] and "response_format" not in requests[0]


def test_real_sdk_stream_assembles_text_and_usage():
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        chunks = [
            {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": MODEL_ID,
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "OK"}, "finish_reason": None}]},
            {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": MODEL_ID,
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": MODEL_ID,
             "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
        ]
        payload = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=payload)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            model = get_chat_model(settings=settings(), http_async_client=transport)
            try:
                total = None
                async for chunk in model.astream("synthetic stream"):
                    total = chunk if total is None else total + chunk
                assert total.content == "OK"
                assert total.usage_metadata["output_tokens"] == 2
            finally:
                await model.root_async_client.close()
                model.root_client.close()

    asyncio.run(run())
    assert bodies[0]["stream_options"] == {"include_usage": True}


def test_sdk_does_not_implicitly_retry_authentication_failure():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "synthetic private marker"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            model = get_chat_model(settings=settings(), http_async_client=transport)
            try:
                with pytest.raises(Exception):
                    await model.ainvoke("synthetic failure")
            finally:
                await model.root_async_client.close()
                model.root_client.close()

    asyncio.run(run())
    assert len(calls) == 1


def test_reasoning_body_is_reduced_to_observation_flag():
    def respond(request):
        return httpx.Response(200, json={"id": "synthetic", "object": "chat.completion",
            "created": 1, "model": MODEL_ID, "choices": [{"index": 0,
            "message": {"role": "assistant", "content": "OK", "reasoning_content": "private-reasoning-body"},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            model = get_chat_model(settings=settings(), http_async_client=transport)
            try:
                result = await model.ainvoke("synthetic")
                assert result.response_metadata["reasoning_observed"] is True
                assert "private-reasoning-body" not in json.dumps(result.model_dump())
            finally:
                await model.root_async_client.close()
                model.root_client.close()
    asyncio.run(run())


@pytest.mark.parametrize("overrides", [{"model": "unapproved"}, {"max_tokens": 4096},
    {"extra_body": {"model": "unapproved"}}])
def test_invocation_cannot_override_protected_parameters(overrides):
    def respond(request):
        pytest.fail("Protected parameters reached HTTP transport")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            model = get_chat_model(settings=settings(), http_async_client=transport)
            try:
                with pytest.raises(ValueError):
                    await model.ainvoke("synthetic", **overrides)
            finally:
                await model.root_async_client.close()
                model.root_client.close()
    asyncio.run(run())
