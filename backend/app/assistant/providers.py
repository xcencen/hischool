"""Budget-aware, non-streaming adapter for the pinned Bailian chat model.

No request starts before the caller has persisted its reservation. This module
returns only the answer, function arguments and safe usage fields; SDK response
objects, reasoning text and provider exceptions never leave the adapter.
"""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
import json
import logging
import os
from threading import Lock

import httpx

from app.ai.factory import get_chat_model
from app.ai.pricing import PriceTable
from app.ai.settings import LLMSettings
from app.mcp.catalog import TOOLS
from app.mcp.logging import private_client_logs


MAX_RESPONSE_BYTES = 262144
PROTOCOL_TOKEN_ALLOWANCE = 1024
MONEY_UNIT = Decimal("0.00000001")
_private_model_call = ContextVar("campus_private_model_call", default=False)
_filter_lock = Lock()


class ProviderFailure(RuntimeError):
    def __init__(self, reason, retryable=False, uncertain=True):
        allowed = {"configuration_missing", "pricing_missing", "tracing_enabled", "context_limit",
            "invalid_messages", "invalid_response", "invalid_tool_calls", "unknown_tool", "model_mismatch",
            "model_limit", "tool_limit", "rate_limited", "timeout", "provider_auth", "upstream",
            "unavailable", "unauthenticated", "forbidden", "output_limit"}
        self.reason = reason if reason in allowed else "unavailable"
        self.retryable, self.uncertain = bool(retryable), bool(uncertain)
        super().__init__("Assistant model request failed")


@dataclass(frozen=True)
class ToolRequest:
    id: str = field(repr=False)
    name: str
    arguments: dict = field(repr=False)


@dataclass(frozen=True)
class ModelReply:
    text: str = field(repr=False)
    tool_calls: list[ToolRequest] = field(default_factory=list, repr=False)
    usage: dict | None = None
    reasoning_observed: bool = False
    invalid_tool_calls: bool = False


def tool_schemas():
    return [{"type": "function", "function": {"name": name, "description": spec.description,
        "parameters": spec.arguments.model_json_schema()}} for name, spec in TOOLS.items()]


def encoded_size(value):
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ProviderFailure("invalid_messages", uncertain=False) from None


def _safe_usage(raw):
    if not isinstance(raw, dict):
        return None
    first, second = raw.get("prompt_tokens"), raw.get("completion_tokens")
    if any(type(value) is not int or value < 0 for value in (first, second)):
        return None
    result = {"input_tokens": first, "output_tokens": second}
    detail = raw.get("prompt_tokens_details")
    if isinstance(detail, dict) and "cached_tokens" in detail:
        cached = detail["cached_tokens"]
        if type(cached) is not int or not 0 <= cached <= first:
            return None
        result["input_token_details"] = {"cache_read": cached}
    detail = raw.get("completion_tokens_details")
    if isinstance(detail, dict):
        reasoning = detail.get("reasoning_tokens")
        if type(reasoning) is int and 0 <= reasoning <= second:
            result["output_token_details"] = {"reasoning": reasoning}
    return result


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        return not _private_model_call.get()


_private_filter = _PrivateFilter()


@contextmanager
def _quiet_sdk_logs():
    roots = ("openai", "langchain", "langchain_core", "langchain_openai", "langsmith")
    with _filter_lock:
        names = set(roots) | {"openai._base_client", "openai._client", "openai._response",
            "langchain_openai.chat_models.base", "langsmith.client", "langsmith.run_trees"}
        names.update(name for name in tuple(logging.root.manager.loggerDict)
                     if name.startswith(tuple(root + "." for root in roots)))
        for name in names:
            logger = logging.getLogger(name)
            if _private_filter not in logger.filters:
                logger.addFilter(_private_filter)
    token = _private_model_call.set(True)
    try:
        with private_client_logs():
            yield
    finally:
        _private_model_call.reset(token)


def check_private_runtime():
    if any(os.environ.get(name, "").strip().lower() in {"1", "true", "debug", "info"}
           for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING",
                        "LANGCHAIN_VERBOSE", "OPENAI_LOG")):
        raise ProviderFailure("tracing_enabled", uncertain=False)
    # These checks also cover tracing/debug enabled by Python rather than env.
    from langchain_core.globals import get_debug, get_verbose
    from langsmith.utils import tracing_is_enabled
    if get_debug() or get_verbose() or tracing_is_enabled():
        raise ProviderFailure("tracing_enabled", uncertain=False)


class _BoundedStream(httpx.AsyncByteStream):
    def __init__(self, inner, on_cancel):
        self.inner, self.on_cancel = inner, on_cancel

    async def __aiter__(self):
        size = 0
        try:
            async for block in self.inner:
                size += len(block)
                if size > MAX_RESPONSE_BYTES:
                    raise ProviderFailure("invalid_response")
                yield block
        except asyncio.CancelledError:
            self.on_cancel()
            raise

    async def aclose(self):
        await self.inner.aclose()


class _BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner, on_cancel):
        self.inner, self.on_cancel = inner, on_cancel

    async def handle_async_request(self, request):
        try:
            response = await self.inner.handle_async_request(request)
        except asyncio.CancelledError:
            self.on_cancel()
            raise
        if response.is_stream_consumed and len(response.content) > MAX_RESPONSE_BYTES:
            raise ProviderFailure("invalid_response")
        response.stream = _BoundedStream(response.stream, self.on_cancel)
        return response

    async def aclose(self):
        await self.inner.aclose()


def _classified_failure(error):
    # The pinned OpenAI SDK wraps transport/hook errors in APIConnectionError.
    # Inspect only types/status and our own fixed fields, never error strings.
    seen = set()
    current = error
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, asyncio.CancelledError):
            return asyncio.CancelledError()
        if isinstance(current, ProviderFailure):
            return ProviderFailure(current.reason, current.retryable, current.uncertain)
        if isinstance(current, (TimeoutError, httpx.TimeoutException)) or type(current).__name__ == "APITimeoutError":
            return ProviderFailure("timeout")
        status = getattr(current, "status_code", None)
        if status == 429:
            return ProviderFailure("rate_limited", retryable=True, uncertain=False)
        if status in {401, 403}:
            return ProviderFailure("provider_auth", uncertain=False)
        if type(status) is int and 500 <= status <= 599:
            return ProviderFailure("upstream")
        current = current.__cause__ or current.__context__
    return ProviderFailure("unavailable")


class ChatProvider:
    def __init__(self, settings: LLMSettings, prices: PriceTable, *, context_max_bytes=48000,
                 transport_factory=None):
        self.settings, self.prices = settings, prices
        self.context_max_bytes, self.transport_factory = context_max_bytes, transport_factory
        if type(context_max_bytes) is not int or not 4096 <= context_max_bytes <= 262144:
            raise ValueError("Invalid assistant context limit")
        if (not isinstance(prices, PriceTable) or prices.input_per_1m <= 0
                or prices.output_per_1m <= 0):
            raise ProviderFailure("pricing_missing", uncertain=False)

    def input_upper_bound(self, messages):
        if not isinstance(messages, list) or not messages:
            raise ProviderFailure("invalid_messages", uncertain=False)
        for item in messages:
            if (not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant", "tool"}
                    or not isinstance(item.get("content"), str)
                    or set(item) - {"role", "content", "tool_calls", "tool_call_id", "name"}):
                raise ProviderFailure("invalid_messages", uncertain=False)
        size = encoded_size({"messages": messages, "tools": tool_schemas()})
        if size > self.context_max_bytes:
            raise ProviderFailure("context_limit", uncertain=False)
        # UTF-8 bytes plus protocol overhead conservatively bound text tokens.
        return size + PROTOCOL_TOKEN_ALLOWANCE

    def estimate(self, messages):
        check_private_runtime()
        if not self.settings.configured:
            raise ProviderFailure("configuration_missing", uncertain=False)
        upper = self.input_upper_bound(messages)
        value = (upper * max(self.prices.input_per_1m, self.prices.cache_read_per_1m)
                 + self.settings.max_output_tokens * self.prices.output_per_1m) / Decimal(1_000_000)
        return value.quantize(MONEY_UNIT, rounding=ROUND_CEILING)

    async def aclose(self):
        """Each completion owns and closes its clients; no cross-run pool exists."""

    async def complete(self, messages):
        self.estimate(messages)
        wire = {"seen": False, "usage": None, "model": None, "cancelled": False}

        async def response_guard(response):
            if 300 <= response.status_code < 400:
                raise ProviderFailure("unavailable")
            if 200 <= response.status_code < 300:
                try:
                    payload = json.loads(await response.aread())
                    wire.update(seen=True, usage=_safe_usage(payload.get("usage")), model=payload.get("model"))
                except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
                    raise ProviderFailure("invalid_response") from None

        transport = self.transport_factory() if self.transport_factory else httpx.AsyncHTTPTransport(retries=0)
        try:
            with _quiet_sdk_logs():
                async with httpx.AsyncClient(transport=_BoundedTransport(transport,
                        lambda: wire.update(cancelled=True)), trust_env=False,
                        follow_redirects=False, timeout=httpx.Timeout(self.settings.timeout_s, connect=3),
                        event_hooks={"response": [response_guard]}) as http_async:
                    with httpx.Client(trust_env=False, follow_redirects=False) as http_sync:
                        model = get_chat_model(settings=self.settings, http_client=http_sync,
                                               http_async_client=http_async)
                        async with asyncio.timeout(self.settings.timeout_s):
                            result = await model.bind_tools(tool_schemas(), tool_choice="auto").ainvoke(
                                messages, config={"callbacks": []})
                        observed_model = wire["model"] if wire["seen"] else (result.response_metadata or {}).get("model_name")
                        if observed_model != self.settings.model_id:
                            raise ProviderFailure("model_mismatch")
                        text = result.content
                        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
                            raise ProviderFailure("invalid_response")
                        calls = [ToolRequest(id=item.get("id"), name=item.get("name"),
                            arguments=item.get("args")) for item in (result.tool_calls or [])]
                        # Raw wire usage avoids LangChain's normalization of missing
                        # prompt/completion counters into misleading zeroes.
                        usage = wire["usage"] if wire["seen"] else None
                        return ModelReply(text=text, tool_calls=calls, usage=usage,
                            reasoning_observed=(result.response_metadata or {}).get("reasoning_observed") is True,
                            invalid_tool_calls=bool(result.invalid_tool_calls))
        except ProviderFailure:
            raise
        except asyncio.CancelledError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderFailure("timeout") from None
        except Exception as error:
            # LangChain 1.0.3's agenerate(return_exceptions=True) can replace a
            # child CancelledError with an unrelated AttributeError. Preserve
            # the transport observation without retaining exception contents.
            if wire["cancelled"]:
                raise asyncio.CancelledError() from None
            raise _classified_failure(error) from None
