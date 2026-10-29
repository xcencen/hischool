"""Explicit synthetic-only M3 cloud probe; never opens campus storage or MCP."""

from decimal import Decimal

from app.ai.pricing import compute_cost
from app.ai.settings import MODEL_ID
from app.assistant.graph import execute_graph
from app.assistant.providers import ChatProvider, ProviderFailure
from app.mcp.catalog import ToolOutcome


async def live_probe(settings, prices, *, max_cost, provider=None):
    if (not isinstance(max_cost, Decimal) or not max_cost.is_finite() or not 0 < max_cost <= 5):
        raise ValueError("Explicit probe budget must be greater than zero and at most 5 CNY")
    if not settings.configured or prices is None:
        raise ValueError("Configure the approved model and explicit prices")
    provider = provider or ChatProvider(settings, prices)
    calls, tool_calls, charged = 0, 0, Decimal(0)
    observations = []

    async def guard():
        return None

    async def model_call(messages):
        nonlocal calls, charged
        upper = provider.estimate(messages)
        if calls >= 10 or charged + upper > max_cost:
            raise ProviderFailure("model_limit", uncertain=False)
        calls += 1
        try:
            reply = await provider.complete(messages)
        except BaseException:
            charged += upper
            raise
        try:
            cost = compute_cost(MODEL_ID, reply.usage, table=prices)
        except (ValueError, TypeError, AttributeError):
            charged += upper
            raise ProviderFailure("invalid_response") from None
        if cost["total_cost"] is None:
            charged += upper
            raise ProviderFailure("invalid_response")
        charged += Decimal(cost["total_cost"])
        if charged > max_cost:
            raise ProviderFailure("model_limit", uncertain=False)
        observations.append({key: cost[key] for key in ("input_tokens", "output_tokens", "cache_read_tokens")})
        return reply

    async def synthetic_tool(name, arguments, call_id):
        nonlocal tool_calls
        tool_calls += 1
        # Only this fabricated notice exists. No actor, campus session, source
        # file, identity store or MCP endpoint is available to this function.
        if name == "campus_list_notices":
            return ToolOutcome(tool=name, run_id="synthetic-m3", ok=True,
                data={"items": [{"id": 1, "title": "模拟通知：演示图书馆延时开放",
                    "content": "纯合成验收数据。演示图书馆今晚延时开放至22点。", "category_id": 1,
                    "category_name": "模拟分类", "published_at": "2026-10-29T00:00:00Z", "truncated": False}],
                    "total": 1, "page": arguments.get("page", 1), "page_size": arguments.get("page_size", 5)},
                citations=[{"source_id": "S1", "kind": "notice", "item_id": 1,
                    "title": "模拟通知", "url": "/app/notices/1"}], observed_at="2026-10-29T00:00:00Z").model_dump(mode="json")
        return ToolOutcome(tool=name, ok=False, reason="not_found",
                           observed_at="2026-10-29T00:00:00Z").model_dump(mode="json")

    result = {"status": "failed", "synthetic_only": True}
    try:
        first = await execute_graph(messages=[{"role": "user", "content":
            "这是纯合成验收。请调用校园通知列表工具，然后仅依据返回的模拟通知，用一句话说明演示图书馆今晚何时关闭并引用来源。"}],
            model_call=model_call, tool_call=synthetic_tool, guard=guard, max_steps=3)
        second = await execute_graph(messages=[{"role": "user", "content": "请记住演示代号是紫竹。只回复已记住。"}],
            model_call=model_call, tool_call=synthetic_tool, guard=guard, max_steps=2)
        third = await execute_graph(messages=[{"role": "user", "content": "请记住演示代号是紫竹。只回复已记住。"},
            {"role": "assistant", "content": second.text}, {"role": "user", "content": "刚才的演示代号是什么？只回复代号。"}],
            model_call=model_call, tool_call=synthetic_tool, guard=guard, max_steps=2)
        passed = tool_calls > 0 and bool(first.citations) and "22" in first.text and "紫竹" in third.text
        result.update(status="passed" if passed else "failed", tool_roundtrip=bool(first.citations),
                      multi_turn="紫竹" in third.text)
    except ProviderFailure as error:
        result["reason"] = error.reason
    except Exception:
        result["reason"] = "unavailable"
    finally:
        await provider.aclose()
    result.update(requests=calls, simulated_tool_calls=tool_calls, charged_upper_cny=str(charged),
                  price_version=prices.version, usage=observations)
    return result
