"""Authenticated stateless Streamable HTTP server for six bounded read tools."""

from contextlib import asynccontextmanager
import asyncio
import json

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware as MCPMiddleware
from fastmcp.tools.tool import Tool, ToolResult
from mcp import types
from pydantic import PrivateAttr, ValidationError
from starlette.responses import JSONResponse

from app.common.exceptions import BusinessException
from app.mcp.auth import decode_delegation
from app.mcp.catalog import TOOLS, ToolOutcome
from app.mcp.executor import ToolExecutor, outcome
from app.mcp.runtime import create_resources
from app.mcp.settings import load_mcp_settings


MAX_REQUEST_BYTES = 16384


class SignatureVerifier(TokenVerifier):
    def __init__(self, settings):
        super().__init__(required_scopes=["campus:read"])
        self.settings = settings

    async def verify_token(self, token):
        try:
            claims = decode_delegation(token, self.settings)
        except BusinessException:
            return None
        return AccessToken(token=token, client_id="my-campus-assistant", subject=claims.sub,
            scopes=["campus:read"], expires_at=claims.exp, resource=claims.resource,
            claims=claims.model_dump())


class ReadTool(Tool):
    _executor = PrivateAttr()

    def __init__(self, name, executor):
        spec = TOOLS[name]
        super().__init__(name=name, description=spec.description,
            parameters=spec.arguments.model_json_schema(), output_schema=ToolOutcome.model_json_schema(),
            annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                             idempotentHint=True, openWorldHint=False))
        self._executor = executor

    async def run(self, arguments):
        access = get_access_token()
        if access is None:
            value = outcome(self.name, reason="unauthenticated")
        else:
            value = await self._executor().execute(self.name, arguments, access.token)
        return ToolResult(structured_content=value)


class ToolBoundary(MCPMiddleware):
    async def on_call_tool(self, context, call_next):
        if context.message.name not in TOOLS:
            return ToolResult(structured_content=outcome("unknown", reason="unknown_tool"))
        return await call_next(context)

    async def on_list_tools(self, context, call_next):
        access = get_access_token()
        allowed = set((access.claims or {}).get("tools", [])) if access else set()
        return [tool for tool in await call_next(context) if tool.name in allowed]


def valid_rpc(payload):
    if (not isinstance(payload, dict) or set(payload) - {"id", "jsonrpc", "method", "params"}
            or payload.get("jsonrpc") != "2.0"):
        return False
    if "id" in payload and (type(payload["id"]) not in {str, int}
                            or len(str(payload["id"])) > 64):
        return False
    method = payload.get("method")
    if type(method) is not str or method not in {"initialize", "notifications/initialized", "notifications/cancelled", "ping",
                      "tools/list", "tools/call"}:
        return False
    if method == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict) or set(params) - {"name", "arguments"}:
            return False
    try:
        value = {"method": method, **({"params": payload["params"]} if "params" in payload else {})}
        if method.startswith("notifications/"):
            types.ClientNotification.model_validate(value)
        else:
            types.ClientRequest.model_validate(value)
        return True
    except (ValidationError, ValueError, TypeError):
        return False


class PrivateIngress:
    def __init__(self, inner, settings, state):
        self.inner, self.settings, self.state = inner, settings, state

    async def _error(self, scope, receive, send, code, reason):
        response = JSONResponse({"reason": reason}, status_code=code,
            headers={"Cache-Control": "no-store", "WWW-Authenticate": "Bearer"} if code == 401
            else {"Cache-Control": "no-store"})
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        headers = scope.get("headers", [])
        hosts = [v.decode("latin-1") for k, v in headers if k.lower() == b"host"]
        if (len(hosts) != 1 or hosts[0] not in self.settings.allowed_hosts
                or scope.get("query_string")
                or any(k.lower() == b"origin" for k, _ in headers)):
            return await self._error(scope, receive, send, 403, "private_endpoint")
        if scope["path"] in {"/health", "/ready"} and scope["method"] == "GET":
            ready = self.state.get("executor") is not None
            if scope["path"] == "/ready" and ready:
                try:
                    from sqlalchemy import text
                    async with asyncio.timeout(4):
                        resources = self.state["executor"].resources
                        async with resources.database.session_factory() as db:
                            await db.execute(text("SELECT 1"))
                        ready = bool(await resources.redis.ping())
                except Exception:
                    ready = False
            return await JSONResponse({"ready": ready}, status_code=200 if ready else 503)(scope, receive, send)
        if scope["path"] != "/mcp" or scope["method"] not in {"GET", "POST", "DELETE"}:
            return await self._error(scope, receive, send, 404, "not_found")
        auth = [v.decode("latin-1") for k, v in headers if k.lower() == b"authorization"]
        if len(auth) != 1 or not auth[0].lower().startswith("bearer "):
            return await self._error(scope, receive, send, 401, "unauthenticated")
        if self.state.get("executor") is None:
            return await self._error(scope, receive, send, 503, "unavailable")
        token = auth[0][7:]
        try:
            async with asyncio.timeout(5):
                await self.state["executor"].identity(token)
        except BusinessException as error:
            code = 401 if error.code == 401 else 503
            return await self._error(scope, receive, send, code, "unauthenticated" if code == 401 else "unavailable")
        except Exception:
            return await self._error(scope, receive, send, 503, "unavailable")
        if scope["method"] != "POST":
            return await self.inner(scope, receive, send)
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > MAX_REQUEST_BYTES:
                        return await self._error(scope, receive, send, 413, "request_too_large")
                    if not message.get("more_body", False):
                        break
            if not valid_rpc(json.loads(body)):
                return await self._error(scope, receive, send, 400, "invalid_request")
        except (ValueError, UnicodeError, TimeoutError, RecursionError):
            return await self._error(scope, receive, send, 400, "invalid_request")
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.inner(scope, replay, send)


def create_app(settings=None, *, resources_factory=None, limits=None):
    settings = settings or load_mcp_settings()
    state = {}

    @asynccontextmanager
    async def lifespan(server):
        resources = (resources_factory or create_resources)()
        state["executor"] = ToolExecutor(resources, settings, limits=limits)
        try:
            yield
        finally:
            state.clear()
            await resources.close()

    server = FastMCP("campus-read-tools", version="1.0", auth=SignatureVerifier(settings),
        lifespan=lifespan, middleware=[ToolBoundary()], mask_error_details=True,
        # Custom tools validate raw arguments with the shared strict Pydantic schema.
        strict_input_validation=False, tasks=False)
    # FastMCP 2.14.7 advertises tasks even with tasks=False. This pinned SDK
    # adapter advertises precisely the methods admitted by PrivateIngress.
    server._mcp_server.get_capabilities = lambda notification_options, experimental_capabilities: types.ServerCapabilities(
        tools=types.ToolsCapability(listChanged=False))
    for name in TOOLS:
        server.add_tool(ReadTool(name, lambda: state["executor"]))
    return PrivateIngress(server.http_app(path="/mcp", stateless_http=True, json_response=True), settings, state)
