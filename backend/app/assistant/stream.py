"""Owner-scoped SSE over durable M3 results, without replaying inference.

Run status is observed live. Answer segments are emitted only after the graph
has validated its answer and committed a successful run. Redis holds expiring
connection identifiers, never messages, tokens or user input.
"""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta
import json
import time
from uuid import uuid4

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.assistant.runs import TERMINAL
from app.assistant.schemas import run_response, timestamp
from app.common.exceptions import BusinessException
from app.database import utc_now
from app.mcp.catalog import Citation
from app.models.assistant import AssistantMessage, AssistantRun, Conversation
from app.services.identity_service import active_identity


CHUNK_CHARACTERS = 64
MAX_CURSOR = 250
POLL_SECONDS = 1
CHUNK_INTERVAL = 0.025
LEASE_SECONDS = 15
USER_CONNECTIONS = 2
GLOBAL_CONNECTIONS = 32
GLOBAL_KEY = "campus:assistant:streams:global"

# Server time and both scopes are checked atomically. A crashed server leaves
# at most fifteen seconds of capacity occupied; a delayed owner cannot revive
# an expired connection after its slot has been reassigned.
_ACQUIRE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
for i = 1, 2 do redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now) end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) or redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) then return 0 end
for i = 1, 2 do
  redis.call('ZADD', KEYS[i], now + tonumber(ARGV[4]), ARGV[1])
  redis.call('EXPIRE', KEYS[i], 30)
end
return 1
"""
_RENEW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
for i = 1, 2 do
  local expiry = redis.call('ZSCORE', KEYS[i], ARGV[1])
  if not expiry or tonumber(expiry) <= now then return 0 end
end
for i = 1, 2 do
  redis.call('ZADD', KEYS[i], now + tonumber(ARGV[2]), ARGV[1])
  redis.call('EXPIRE', KEYS[i], 30)
end
return 1
"""
_RELEASE = """
for i = 1, 2 do redis.call('ZREM', KEYS[i], ARGV[1]) end
return 1
"""


@dataclass(frozen=True)
class Identity:
    user_id: int
    auth_version: int
    jti: str = field(repr=False)
    expires_at: int

    @classmethod
    def from_payload(cls, payload):
        try:
            subject, version, jti, expiry = (payload[key] for key in ("sub", "auth_version", "jti", "exp"))
            if (not isinstance(subject, str) or not subject.isascii() or not subject.isdigit()
                    or int(subject) < 1 or type(version) is not int or version < 0
                    or not isinstance(jti, str) or not 1 <= len(jti) <= 128
                    or type(expiry) is not int):
                raise ValueError()
            return cls(int(subject), version, jti, expiry)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise BusinessException("登录已失效，请重新登录", code=401) from None


class ConnectionLease:
    def __init__(self, redis, user_id):
        self.redis, self.token = redis, uuid4().hex
        self.keys = (GLOBAL_KEY, f"campus:assistant:streams:user:{user_id}")

    async def _eval(self, script, *arguments):
        try:
            async with asyncio.timeout(3):
                return await self.redis.eval(script, 2, *self.keys, self.token, *arguments)
        except (RedisError, TimeoutError):
            raise BusinessException("流式连接暂不可用，请稍后重连", code=503) from None

    async def acquire(self):
        if not await self._eval(_ACQUIRE, GLOBAL_CONNECTIONS, USER_CONNECTIONS, LEASE_SECONDS * 1000):
            raise BusinessException("流式连接过多，请关闭其他页面后重试", code=429)

    async def renew(self):
        if not await self._eval(_RENEW, LEASE_SECONDS * 1000):
            raise BusinessException("流式连接已过期，请重新连接", code=503)

    async def close(self):
        # Release is idempotent and best effort; Redis expiry covers cancellation
        # during a failed connection or process shutdown.
        with suppress(BusinessException):
            await self._eval(_RELEASE)


async def snapshot(database, redis, settings, run_public_id, identity):
    """A fresh, bounded transaction for each observation and answer segment."""
    try:
        async with asyncio.timeout(5):
            async with database.session_factory() as db:
                await active_identity(db, redis, user_id=identity.user_id,
                    auth_version=identity.auth_version, session_jti=identity.jti,
                    expires_at=identity.expires_at, current_read=True)
                run = await db.scalar(select(AssistantRun).where(AssistantRun.public_id == run_public_id,
                    AssistantRun.owner_id == identity.user_id))
                if run is None:
                    raise BusinessException("运行不存在", code=404)
                # Match M3's conversation -> run lock order. A joined locking
                # SELECT can lock the run first and deadlock a final commit.
                conversation = await db.scalar(select(Conversation).where(Conversation.id == run.conversation_id,
                    Conversation.owner_id == identity.user_id, Conversation.state != "deleted")
                    .with_for_update(read=True))
                if conversation is None:
                    raise BusinessException("运行不存在", code=404)
                run = await db.scalar(select(AssistantRun).where(AssistantRun.id == run.id,
                    AssistantRun.owner_id == identity.user_id).with_for_update(read=True)
                    .execution_options(populate_existing=True))
                now = utc_now()
                if conversation.state == "expired" or conversation.expires_at <= now:
                    raise BusinessException("会话正文已过期", code=410)
                value = run_response(run)
                value["conversation_id"] = conversation.public_id
                message = None
                if run.status == "succeeded":
                    row = await db.scalar(select(AssistantMessage).where(AssistantMessage.run_id == run.id,
                        AssistantMessage.conversation_id == conversation.id, AssistantMessage.role == "assistant")
                        .with_for_update(read=True))
                    if row is None:
                        raise BusinessException("回复暂不可用", code=503)
                    if (row.content is None or row.create_time < now - timedelta(days=settings.retention_days)):
                        raise BusinessException("会话正文已过期", code=410)
                    if not isinstance(row.content, str) or not 1 <= len(row.content) <= CHUNK_CHARACTERS * MAX_CURSOR:
                        raise BusinessException("回复暂不可用", code=503)
                    citations = [Citation.model_validate(item).model_dump(mode="json") for item in row.citations]
                    if len(citations) > 99:
                        raise BusinessException("回复暂不可用", code=503)
                    message = dict(id=row.id, sequence=row.sequence, run_id=run.public_id, role="assistant",
                        content=row.content, citations=citations, redacted=False, created_at=timestamp(row.create_time))
                # Release all shared row locks and the pooled connection before
                # yielding bytes or waiting for the client/network.
                await db.commit()
                return value, message
    except BusinessException:
        raise
    except (TimeoutError, SQLAlchemyError, RedisError, ValueError, TypeError):
        raise BusinessException("流式读取暂不可用，请稍后重连", code=503) from None


def event(name, data, *, identifier=None):
    # JSON encoding prevents input newlines from creating extra SSE fields.
    lines = ([f"id: {identifier}"] if identifier is not None else []) + [f"event: {name}",
        "data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), "", ""]
    return "\n".join(lines).encode("utf-8")


def _error_reason(error):
    if isinstance(error, BusinessException):
        return {401: "unauthenticated", 404: "not_found", 410: "expired", 429: "rate_limited"}.get(error.code, "unavailable")
    return "unavailable"


async def events(request, load, lease, *, after, max_duration):
    started, heartbeat = time.monotonic(), time.monotonic()
    previous = None
    try:
        while True:
            if await request.is_disconnected():
                return
            if time.monotonic() - started >= max_duration:
                yield event("error", {"reason": "unavailable"})
                return
            await lease.renew()
            run, message = await load()
            if run != previous:
                yield event("status", {"run": run})
                previous = run
            if run["status"] in TERMINAL:
                if message is not None:
                    content = message["content"]
                    chunks = [content[index:index + CHUNK_CHARACTERS] for index in range(0, len(content), CHUNK_CHARACTERS)]
                    if after > len(chunks):
                        raise BusinessException("流式游标无效", code=422)
                    for index in range(after, len(chunks)):
                        if await request.is_disconnected():
                            return
                        if time.monotonic() - started >= max_duration:
                            raise BusinessException("流式连接已结束，请重新连接", code=503)
                        await lease.renew()
                        current, verified = await load()
                        if (current["status"] != "succeeded" or verified is None
                                or verified["id"] != message["id"] or verified["content"] != content):
                            raise BusinessException("回复暂不可用", code=503)
                        yield event("delta", {"run_id": run["id"], "sequence": index + 1,
                            "text": chunks[index]}, identifier=index + 1)
                        await asyncio.sleep(CHUNK_INTERVAL)
                    await lease.renew()
                    run, message = await load()
                yield event("done", {"run": run, "message": message})
                return
            if time.monotonic() - heartbeat >= 10:
                yield b": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(POLL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        yield event("error", {"reason": _error_reason(error)})
    finally:
        await lease.close()


async def open_stream(request, database, redis, settings, run_public_id, token_payload, *, after=0):
    """Validate before HTTP 200; subsequent failures are safe SSE error events."""
    if type(after) is not int or not 0 <= after <= MAX_CURSOR:
        raise BusinessException("流式游标无效", code=422)
    identity = Identity.from_payload(token_payload)

    async def load():
        return await snapshot(database, redis, settings, run_public_id, identity)

    run, message = await load()
    if after and (message is None or after > (len(message["content"]) + CHUNK_CHARACTERS - 1) // CHUNK_CHARACTERS):
        raise BusinessException("流式游标无效", code=422)
    lease = ConnectionLease(redis, identity.user_id)
    await lease.acquire()
    return StreamingResponse(events(request, load, lease, after=after,
        max_duration=min(1260, settings.queue_timeout_s + settings.run_timeout_s + 60)),
        media_type="text/event-stream", headers={"Cache-Control": "private, no-store, no-transform",
            "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(lease.close))
