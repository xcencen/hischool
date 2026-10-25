"""Bounded synthetic capability checks; no campus data or business tool execution."""

import asyncio
from dataclasses import replace
from decimal import Decimal
import os

from app.ai.factory import get_chat_model
from app.ai.pricing import compute_cost


TOOLS = [{"type": "function", "function": {
    "name": "campus_get_my_schedules", "description": "查询本人课表，身份由系统注入。",
    "parameters": {"type": "object", "properties": {
        "date": {"type": "string", "enum": ["today", "tomorrow", "this_week"]}},
        "required": ["date"], "additionalProperties": False}}}]
PROMPT = "你是校园助手。查询课表只能使用提供的工具。身份由系统注入。"
QUERY = "请查询我明天的课表。"
REQUEST_COUNT = 4
OUTPUT_LIMIT = 128
THINKING_OUTPUT_LIMIT = 1024
# Conservative synthetic-request allowance, including provider tool templates.
INPUT_LIMIT = 8192


class ProbeUnavailable(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("Chat capability probe could not complete")


def budget_reservation(table, max_cost, *, requests=REQUEST_COUNT, thinking_requests=0):
    if table is None:
        raise ProbeUnavailable("pricing_missing")
    if (not isinstance(max_cost, Decimal) or not max_cost.is_finite()
            or not Decimal("0") < max_cost <= Decimal("5")):
        raise ProbeUnavailable("invalid_budget")
    if table.input_per_1m <= 0 or table.output_per_1m <= 0:
        raise ProbeUnavailable("pricing_invalid")
    rate = max(table.input_per_1m, table.cache_read_per_1m)
    reserve = requests * (INPUT_LIMIT * rate + OUTPUT_LIMIT * table.output_per_1m
                              ) / Decimal(1_000_000)
    reserve += thinking_requests * (INPUT_LIMIT * rate + THINKING_OUTPUT_LIMIT
                                    * table.output_per_1m) / Decimal(1_000_000)
    if reserve > max_cost:
        raise ProbeUnavailable("budget_insufficient")
    return reserve


def safe_reason(error):
    if isinstance(error, ProbeUnavailable):
        return error.reason
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    status = getattr(error, "status_code", None)
    if status in {401, 403}:
        return "authentication_or_quota"
    if status == 429:
        return "rate_limited"
    if type(status) is int and 500 <= status <= 599:
        return "upstream"
    return "unavailable"


def _check_result(message, settings, table, *, output_limit=OUTPUT_LIMIT):
    model = (message.response_metadata or {}).get("model_name")
    if model != settings.model_id:
        raise ProbeUnavailable("model_mismatch")
    cost = compute_cost(settings.model_id, message.usage_metadata, table=table)
    if cost["usage_unknown"]:
        raise ProbeUnavailable("usage_unknown")
    if cost["input_tokens"] > INPUT_LIMIT or cost["output_tokens"] > output_limit:
        raise ProbeUnavailable("usage_out_of_bounds")
    return cost


def _tool_valid(message):
    calls = message.tool_calls or []
    return (not message.invalid_tool_calls and len(calls) == 1
            and calls[0]["name"] == "campus_get_my_schedules"
            and calls[0]["args"] == {"date": "tomorrow"})


async def live_probe(settings, table, *, max_cost, model_factory=None, check_thinking=False):
    if not settings.configured:
        raise ProbeUnavailable("configuration_missing")
    if any(os.environ.get(name, "").lower() in {"1", "true", "debug"} for name in (
            "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "OPENAI_LOG")):
        raise ProbeUnavailable("external_tracing_enabled")
    request_limit = REQUEST_COUNT + (2 if check_thinking else 0)
    reserve = budget_reservation(table, max_cost, thinking_requests=2 if check_thinking else 0)
    settings = replace(settings, max_output_tokens=OUTPUT_LIMIT)
    model = (model_factory or get_chat_model)(settings=settings)
    clients = [model]
    cases, spent, attempts = [], Decimal("0"), 0
    reasoning = {}
    reasoning_observed = {}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        # No SDK retries; one deadline covers all four synthetic model requests.
        async with asyncio.timeout(120):
            requests = [
                ("stream", "none"), ("tool_auto", "auto"),
                ("tool_required", "required"),
                ("tool_named", "campus_get_my_schedules"),
            ]
            for case_id, choice in requests:
                if attempts >= REQUEST_COUNT:
                    raise ProbeUnavailable("request_limit")
                attempts += 1
                target = model.bind_tools(TOOLS, tool_choice=choice)
                messages = [SystemMessage(content=PROMPT), HumanMessage(
                    content="只回复 OK。" if case_id == "stream" else QUERY)]
                async with asyncio.timeout(45):
                    if case_id == "stream":
                        message = None
                        async for chunk in target.astream(messages):
                            message = chunk if message is None else message + chunk
                        if message is None:
                            raise ProbeUnavailable("empty_stream")
                    else:
                        message = await target.ainvoke(messages)
                cost = _check_result(message, settings, table)
                spent += Decimal(cost["total_cost"])
                valid = bool(message.content) and not message.tool_calls if case_id == "stream" else _tool_valid(message)
                cases.append({"case": case_id, "passed": bool(valid),
                    "input_tokens": cost["input_tokens"], "output_tokens": cost["output_tokens"]})
                if not valid:
                    raise ProbeUnavailable("capability_failed")
            if check_thinking:
                for enabled in (False, True):
                    attempts += 1
                    thinking_model = (model_factory or get_chat_model)(settings=replace(
                        settings, enable_thinking=enabled, max_output_tokens=THINKING_OUTPUT_LIMIT))
                    clients.append(thinking_model)
                    async with asyncio.timeout(30):
                        message = await thinking_model.ainvoke([HumanMessage(content=
                            "袋中有5个红球和3个蓝球，不放回抽2个，都是红球的概率是多少？只给最简分数。")])
                    cost = _check_result(message, settings, table, output_limit=THINKING_OUTPUT_LIMIT)
                    spent += Decimal(cost["total_cost"])
                    count = (message.usage_metadata.get("output_token_details") or {}).get("reasoning")
                    reasoning[str(enabled).lower()] = count if type(count) is int and count >= 0 else None
                    reasoning_observed[str(enabled).lower()] = message.response_metadata.get("reasoning_observed")
                off_ok = reasoning["false"] == 0 or (
                    reasoning["false"] is None and reasoning_observed["false"] is False)
                on_ok = bool(reasoning["true"]) or reasoning_observed["true"] is True
                if not off_ok or not on_ok:
                    raise ProbeUnavailable("thinking_effect_not_verified")
        return {"status": "passed", "model": settings.model_id,
                "thinking_requested": settings.enable_thinking,
                "thinking_effectiveness": "verified" if check_thinking else "not_verified",
                "reasoning_tokens": reasoning, "requests": attempts,
                "reasoning_observed": reasoning_observed,
                "reserved_cost_cny": str(reserve), "estimated_cost_cny": str(spent),
                "price_version": table.version, "cases": cases}
    except Exception as error:
        return {"status": "failed", "reason": safe_reason(error), "requests": attempts,
                "reserved_cost_cny": str(reserve), "known_cost_cny": str(spent),
                "estimated_cost_cny": None, "incomplete_usage_possible": True,
                "reasoning_tokens": reasoning, "reasoning_observed": reasoning_observed, "cases": cases}
    finally:
        # ChatOpenAI owns these clients; this probe never retains them for reuse.
        for owned in clients:
            client = getattr(owned, "root_async_client", None)
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
            client = getattr(owned, "root_client", None)
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


def offline_probe(settings, table):
    return {"status": "configured" if settings.configured else "not_configured",
            "configured": settings.configured, "model": settings.model_id,
            "key_loaded": bool(settings.api_key), "endpoint_configured": bool(settings.base_url),
            "thinking_requested": settings.enable_thinking, "pricing_configured": table is not None,
            "planned_requests": REQUEST_COUNT, "live_verified": False}
