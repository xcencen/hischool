"""Private SDK client with per-call delegation and locally trusted schemas."""

import asyncio
from datetime import timedelta
import json

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from app.common.exceptions import BusinessException
from app.mcp.auth import issue_delegation
from app.mcp.catalog import TOOLS, ToolOutcome
from app.mcp.executor import MAX_RESULT_BYTES, outcome
from app.mcp.logging import private_client_logs


MAX_WIRE_BYTES = MAX_RESULT_BYTES * 4


class PrivateTransportError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("Private MCP transport failed")


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        total = 0
        async for chunk in self.stream:
            total += len(chunk)
            if total > MAX_WIRE_BYTES:
                raise PrivateTransportError("invalid_response")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner):
        self.inner = inner

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if response.is_stream_consumed and len(response.content) > MAX_WIRE_BYTES:
            raise PrivateTransportError("invalid_response")
        response.stream = BoundedStream(response.stream)
        return response

    async def aclose(self):
        await self.inner.aclose()


async def guard_response(response):
    # The MCP SDK can follow same-origin redirects independently of httpx's flag.
    # Reject them in the response hook before the SDK can forward credentials.
    if 300 <= response.status_code < 400:
        raise PrivateTransportError("unavailable")
    if response.status_code == 429:
        raise PrivateTransportError("rate_limited")
    if not 200 <= response.status_code < 300:
        # Internal credential errors must not be confused with the browser JWT.
        raise PrivateTransportError("unavailable")
    raw = await response.aread()
    if not raw and response.status_code in {202, 204}:
        return
    try:
        payload = json.loads(raw)
        types.JSONRPCMessage.model_validate(payload)
        if "error" in payload:
            raise PrivateTransportError("unavailable")
        result = payload.get("result", {})
        method = json.loads(response.request.content).get("method")
        if method == "initialize":
            types.InitializeResult.model_validate(result)
        elif method == "tools/call":
            types.CallToolResult.model_validate(result)
            if not result.get("isError", False) and "structuredContent" not in result:
                raise PrivateTransportError("invalid_response")
        if isinstance(result, dict) and "structuredContent" in result:
            ToolOutcome.model_validate(result["structuredContent"])
    except (ValueError, TypeError, ValidationError):
        raise PrivateTransportError("invalid_response") from None


def failure_reason(error):
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(error, PrivateTransportError):
        return error.reason
    for child in getattr(error, "exceptions", ()):
        value = failure_reason(child)
        if value != "unavailable":
            return value
    return "unavailable"


class CampusMCPClient:
    def __init__(self, campus_settings, mcp_settings, database, redis, *, transport_factory=None):
        self.campus_settings, self.settings = campus_settings, mcp_settings
        self.database, self.redis = database, redis
        self.transport_factory = transport_factory

    async def call(self, name, arguments, *, campus_token, run_id):
        with private_client_logs():
            return await self._call(name, arguments, campus_token=campus_token, run_id=run_id)

    async def _call(self, name, arguments, *, campus_token, run_id):
        try:
            if name not in TOOLS:
                return outcome("unknown", reason="unknown_tool")
            try:
                args = TOOLS[name].arguments.model_validate(arguments).model_dump(mode="json")
            except ValidationError:
                return outcome(name, reason="invalid_arguments")
            async with asyncio.timeout(60):
                async with self.database.session_factory() as db:
                    delegated = await issue_delegation(db, self.redis, self.campus_settings,
                        self.settings, campus_token, run_id=run_id, tools=[name])
                transport = self.transport_factory() if self.transport_factory else httpx.AsyncHTTPTransport(retries=0)
                async with httpx.AsyncClient(transport=BoundedTransport(transport),
                        headers={"Authorization": "Bearer " + delegated.token},
                        timeout=httpx.Timeout(58, connect=3), follow_redirects=False, trust_env=False,
                        event_hooks={"response": [guard_response]}) as http:
                    async with streamable_http_client(self.settings.url, http_client=http,
                                                      terminate_on_close=False) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            # Use the public typed RPC API and local output validation.
                            # Do not load remote descriptions/schemas into the model.
                            result = await session.send_request(types.ClientRequest(types.CallToolRequest(
                                params=types.CallToolRequestParams(name=name, arguments=args))),
                                types.CallToolResult, request_read_timeout_seconds=timedelta(seconds=57))
                if result.isError or result.structuredContent is None:
                    return outcome(name, run_id=run_id, reason="unavailable")
                value = ToolOutcome.model_validate(result.structuredContent)
                if (value.tool != name or value.run_id not in {None, run_id}
                        or (value.ok and value.run_id != run_id)
                        or len(json.dumps(value.model_dump(), ensure_ascii=False).encode()) > MAX_RESULT_BYTES):
                    return outcome(name, run_id=run_id, reason="invalid_response")
                return value.model_dump(mode="json")
        except BusinessException as error:
            reason = {401: "unauthenticated", 403: "forbidden"}.get(error.code, "unavailable")
        except ValidationError:
            reason = "invalid_response"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            reason = failure_reason(error)
        return outcome(name, reason=reason)
