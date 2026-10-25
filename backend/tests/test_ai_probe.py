"""Capability results must reflect real observations, including failed/unknown states."""

import asyncio
from decimal import Decimal
import json

import pytest

pytest.importorskip("langchain_core", reason="M1 optional assistant dependencies")
from langchain_core.messages import AIMessage, AIMessageChunk

from app.ai.probe import ProbeUnavailable, live_probe
from app.ai.settings import LLMSettings, MODEL_ID
from test_ai_foundation import price_table


SETTINGS = LLMSettings(api_key="private-key-marker",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")


class FakeModel:
    def __init__(self, *, fail=None, usage=True, invalid=False):
        self.calls, self.fail, self.usage, self.invalid = [], fail, usage, invalid
        self.reasoning = None

    def bind_tools(self, tools, *, tool_choice):
        self.calls.append(tool_choice)
        return self

    async def astream(self, messages):
        if self.fail:
            raise self.fail
        yield AIMessageChunk(content="OK", response_metadata={"model_name": MODEL_ID},
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
                **({"output_token_details": {"reasoning": self.reasoning}}
                   if self.reasoning is not None else {})}
            if self.usage else None)

    async def ainvoke(self, messages):
        return AIMessage(content="", response_metadata={"model_name": MODEL_ID},
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
                **({"output_token_details": {"reasoning": self.reasoning}}
                   if self.reasoning is not None else {})},
            tool_calls=[{"id": "synthetic", "name": "campus_get_my_schedules",
                         "args": {"date": "tomorrow", **({"user_id": 999} if self.invalid else {})}}])


def run(model):
    return asyncio.run(live_probe(SETTINGS, price_table(), max_cost=Decimal("5"),
                                 model_factory=lambda **kwargs: model))


def test_probe_checks_stream_auto_required_named_without_executing_business_tools():
    model = FakeModel()
    result = run(model)
    assert result["status"] == "passed" and result["requests"] == 4
    assert model.calls == ["none", "auto", "required", "campus_get_my_schedules"]
    assert result["thinking_effectiveness"] == "not_verified"
    assert "private-key-marker" not in json.dumps(result)


@pytest.mark.parametrize("error,reason", [
    (RuntimeError("private-key-marker private-response-body"), "unavailable"),
    (TimeoutError("private timeout"), "timeout"),
])
def test_probe_sanitizes_failures_and_stops_requests(error, reason):
    model = FakeModel(fail=error)
    result = run(model)
    assert result["status"] == "failed" and result["reason"] == reason
    assert result["requests"] == 1 and len(model.calls) == 1
    assert "private" not in json.dumps(result)


def test_missing_usage_stops_probe_instead_of_recording_free_success():
    result = run(FakeModel(usage=False))
    assert result["status"] == "failed" and result["reason"] == "usage_unknown"
    assert result["requests"] == 1


def test_identity_override_arguments_fail_strict_tool_validation():
    result = run(FakeModel(invalid=True))
    assert result["status"] == "failed" and result["reason"] == "capability_failed"
    assert result["requests"] == 2


def test_cancellation_propagates_normally():
    with pytest.raises(asyncio.CancelledError):
        run(FakeModel(fail=asyncio.CancelledError()))


def test_thinking_effect_requires_actual_usage_evidence_for_both_modes():
    def factory(**kwargs):
        model = FakeModel()
        model.reasoning = 1 if kwargs["settings"].enable_thinking else 0
        return model
    result = asyncio.run(live_probe(SETTINGS, price_table(), max_cost=Decimal("5"),
        model_factory=factory, check_thinking=True))
    assert result["status"] == "passed" and result["requests"] == 6
    assert result["reasoning_tokens"] == {"false": 0, "true": 1}
    assert result["thinking_effectiveness"] == "verified"


def test_missing_thinking_metadata_cannot_pass_effectiveness_gate():
    result = asyncio.run(live_probe(SETTINGS, price_table(), max_cost=Decimal("5"),
        model_factory=lambda **kwargs: FakeModel(), check_thinking=True))
    assert result["status"] == "failed" and result["reason"] == "thinking_effect_not_verified"


def test_live_preflight_refuses_cloud_tracing_before_creating_model(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(ProbeUnavailable) as error:
        run(FakeModel())
    assert error.value.reason == "external_tracing_enabled"
