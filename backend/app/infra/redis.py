"""Async Redis helpers for the campus agent runtime.

A single, lazily-created async client is built from ``CAMPUS_REDIS_URL``. Every
helper raises a clear :class:`RedisUnavailable` error when Redis cannot be reached
— there is no silent degradation, because a missing lock/limit would silently
break the agent's concurrency guarantees.
"""
from __future__ import annotations

import os
import math
import time
import uuid

from redis.exceptions import RedisError


class RedisUnavailable(RuntimeError):
    """Raised when Redis cannot be reached or a command fails unexpectedly."""


_CLIENT = None


def get_redis():
    """Return the process-wide async Redis client, creating it on first use."""
    global _CLIENT
    if _CLIENT is None:
        url = os.environ.get("CAMPUS_REDIS_URL")
        if not url:
            raise RedisUnavailable("CAMPUS_REDIS_URL is not set; cannot reach Redis")
        from redis.asyncio import Redis

        _CLIENT = Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3
        )
    return _CLIENT


def reset_redis_client() -> None:
    """Drop the cached client (used by tests)."""
    global _CLIENT
    _CLIENT = None


# --- run mutex lock (SET NX EX + Lua CAS release) --------------------------
_ACQUIRE_LUA = """
if redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  return 1
end
return 0
"""

_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


async def acquire_run_lock(run_id: str, ttl_s: int = 180) -> str | None:
    """Acquire an exclusive run lock. Returns a token on success, None if held."""
    client = get_redis()
    token = uuid.uuid4().hex
    key = f"campus:run_lock:{run_id}"
    try:
        ok = await client.eval(_ACQUIRE_LUA, 1, key, token, str(ttl_s))
    except RedisError:
        raise RedisUnavailable("Redis lock acquire failed") from None
    return token if ok else None


async def release_run_lock(run_id: str, token: str) -> bool:
    """Release the run lock only if our token still owns it (Lua CAS)."""
    client = get_redis()
    key = f"campus:run_lock:{run_id}"
    try:
        removed = await client.eval(_RELEASE_LUA, 1, key, token)
    except RedisError:
        raise RedisUnavailable("Redis lock release failed") from None
    return bool(removed)


# --- token bucket rate limit ---------------------------------------------
_TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local tokens = tonumber(redis.call('get', KEYS[1]) or capacity)
local prev = tonumber(redis.call('get', KEYS[1]..':ts') or now)
local delta = math.max(0, now - prev) / 1000
now = math.max(now, prev)
tokens = math.min(capacity, tokens + delta * rate)
if tokens >= cost then
  tokens = tokens - cost
  redis.call('set', KEYS[1], tokens, 'EX', ttl)
  redis.call('set', KEYS[1]..':ts', now, 'EX', ttl)
  return 1
end
redis.call('set', KEYS[1], tokens, 'EX', ttl)
redis.call('set', KEYS[1]..':ts', now, 'EX', ttl)
return 0
"""


async def rate_limit(
    key: str, *, capacity: int, refill_per_s: float, cost: int = 1, ttl_s: int = 60, client=None
) -> bool:
    """Token-bucket limiter. Returns True if the request is allowed."""
    if (type(capacity) is not int or capacity <= 0
            or type(cost) is not int or not 0 < cost <= capacity
            or type(ttl_s) is not int or ttl_s <= 0
            or isinstance(refill_per_s, bool)
            or not isinstance(refill_per_s, (int, float))
            or not math.isfinite(refill_per_s) or refill_per_s <= 0):
        raise ValueError("Invalid token-bucket configuration")
    # Expiry must not recreate a full bucket before it would naturally refill.
    ttl_s = max(ttl_s, math.ceil(capacity / refill_per_s) + 1)
    client = client if client is not None else get_redis()
    rkey = f"campus:ratelimit:{key}"
    now_ms = int(time.time() * 1000)
    try:
        allowed = await client.eval(
            _TOKEN_BUCKET_LUA, 1, rkey,
            str(capacity), str(refill_per_s), str(now_ms), str(cost), str(ttl_s),
        )
    except RedisError:
        raise RedisUnavailable("Redis rate-limit failed") from None
    return bool(allowed)


# --- cancel signal + run status -------------------------------------------
_STATUS_PREFIX = "campus:run_status:"
_CANCEL_PREFIX = "campus:run_cancel:"


async def set_run_status(run_id: str, status: str) -> None:
    client = get_redis()
    try:
        await client.set(_STATUS_PREFIX + run_id, status, ex=3600)
    except RedisError:
        raise RedisUnavailable("Redis set status failed") from None


async def get_run_status(run_id: str) -> str | None:
    client = get_redis()
    try:
        return await client.get(_STATUS_PREFIX + run_id)
    except RedisError:
        raise RedisUnavailable("Redis get status failed") from None


async def signal_cancel(run_id: str) -> None:
    client = get_redis()
    try:
        await client.set(_CANCEL_PREFIX + run_id, "1", ex=3600)
    except RedisError:
        raise RedisUnavailable("Redis cancel failed") from None


async def is_cancelled(run_id: str) -> bool:
    client = get_redis()
    try:
        return bool(await client.get(_CANCEL_PREFIX + run_id))
    except RedisError:
        raise RedisUnavailable("Redis cancel-check failed") from None


async def clear_cancel(run_id: str) -> None:
    client = get_redis()
    try:
        await client.delete(_CANCEL_PREFIX + run_id)
    except RedisError:
        raise RedisUnavailable("Redis clear-cancel failed") from None
