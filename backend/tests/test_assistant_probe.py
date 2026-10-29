"""M3 live-probe guard rails exercised entirely with synthetic providers."""

import asyncio
from decimal import Decimal
import json

import pytest

pytest.importorskip("langgraph", reason="Requires optional assistant profile")

from app.ai.pricing import PriceTable
from app.ai.settings import LLMSettings
from app.assistant import probe
from app.assistant.providers import ModelReply, ProviderFailure, ToolRequest


SETTINGS = LLMSettings(api_key="private-probe-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
PRICES = PriceTable(Decimal("2"), Decimal("8"), Decimal("0.2"), "test", "synthetic")


class SyntheticProvider:
    def __init__(self, *, upper="0.01", usage=True, fail=None):
        self.upper, self.usage, self.fail = Decimal(upper), usage, fail
        self.calls, self.closed = [], False

    def estimate(self, messages):
        return self.upper

    async def complete(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise self.fail
        count = len(self.calls)
        usage = {"input_tokens":10, "output_tokens":5} if self.usage is True else self.usage
        if count == 1:
            return ModelReply("", [ToolRequest("call_one", "campus_list_notices", {})], usage=usage)
        if count == 2:
            return ModelReply("演示图书馆今晚22点关闭 [S1]。", usage=usage)
        if count == 3:
            return ModelReply("已记住。", usage=usage)
        return ModelReply("紫竹", usage=usage)

    async def aclose(self):
        self.closed = True


def run(provider, limit="5"):
    return asyncio.run(probe.live_probe(SETTINGS, PRICES, max_cost=Decimal(limit), provider=provider))


def test_synthetic_tool_roundtrip_and_multiturn_do_not_open_campus_resources(monkeypatch):
    from app.database import Database
    monkeypatch.setattr(Database, "__init__", lambda *args: pytest.fail("Unexpected campus database"))
    target = SyntheticProvider()
    value = run(target)
    assert value["status"] == "passed" and value["synthetic_only"]
    assert value["requests"] == 4 and value["simulated_tool_calls"] == 1
    assert value["tool_roundtrip"] and value["multi_turn"] and target.closed
    assert len(target.calls[3]) == 4 and target.calls[3][-2]["content"] == "已记住。"
    encoded = json.dumps(value, ensure_ascii=False)
    assert "private-probe-key" not in encoded and "紫竹" not in encoded and "模拟通知" not in encoded


def test_insufficient_budget_sends_zero_requests_and_closes_provider():
    target = SyntheticProvider()
    value = run(target, "0.000001")
    assert value["status"] == "failed" and value["requests"] == 0 and target.calls == []
    assert Decimal(value["charged_upper_cny"]) == 0 and target.closed


def test_probe_never_exceeds_ten_model_requests_even_if_graph_calls_repeatedly(monkeypatch):
    async def repeated_graph(**kwargs):
        for _ in range(11):
            await kwargs["model_call"]([{"role":"user", "content":"synthetic"}])
        pytest.fail("Eleventh request should have been denied")
    monkeypatch.setattr(probe, "execute_graph", repeated_graph)
    target = SyntheticProvider(upper="0.001")
    value = run(target)
    assert value["status"] == "failed" and value["requests"] == len(target.calls) == 10
    assert value["reason"] == "model_limit" and target.closed


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens":10},
    {"input_tokens":10,"output_tokens":5,"input_token_details":{"cache_read":99}}])
def test_unknown_or_invalid_usage_charges_upper_bound_and_stops(usage):
    target = SyntheticProvider(usage=usage)
    value = run(target)
    assert value["status"] == "failed" and value["requests"] == 1 and target.closed
    assert Decimal(value["charged_upper_cny"]) == target.upper
    assert value["usage"] == []


@pytest.mark.parametrize("failure", [ProviderFailure("timeout"), RuntimeError("private-provider-error")])
def test_dispatched_failures_keep_conservative_cost_without_echoing_exception(failure):
    target = SyntheticProvider(fail=failure)
    value = run(target)
    assert value["status"] == "failed" and value["requests"] == 1 and target.closed
    assert Decimal(value["charged_upper_cny"]) == target.upper
    assert "private-provider-error" not in json.dumps(value)


@pytest.mark.parametrize("limit", [Decimal("0"),Decimal("5.01"),Decimal("NaN"),5])
def test_live_probe_requires_explicit_finite_budget_before_any_request(limit):
    target = SyntheticProvider()
    with pytest.raises(ValueError):
        asyncio.run(probe.live_probe(SETTINGS, PRICES, max_cost=limit, provider=target))
    assert target.calls == []
