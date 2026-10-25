"""Execute the token-bucket Lua against the optional profile's Redis emulator."""

import asyncio

import pytest

from app.infra import redis as helpers


@pytest.mark.parametrize("values", [
    {"capacity": 0, "refill_per_s": 1}, {"capacity": True, "refill_per_s": 1},
    {"capacity": 2, "refill_per_s": 0}, {"capacity": 2, "refill_per_s": float("nan")},
    {"capacity": 2, "refill_per_s": 1, "cost": 3},
    {"capacity": 2, "refill_per_s": 1, "ttl_s": 0},
])
def test_invalid_bucket_never_contacts_redis(monkeypatch, values):
    monkeypatch.setattr(helpers, "get_redis", lambda: pytest.fail("Unexpected Redis access"))
    with pytest.raises(ValueError):
        asyncio.run(helpers.rate_limit("synthetic", **values))


def exercise_refill(client, monkeypatch):
    async def run():
        monkeypatch.setattr(helpers, "get_redis", lambda: client)
        clock = [1000.0]
        monkeypatch.setattr(helpers.time, "time", lambda: clock[0])
        assert await helpers.rate_limit("m1-refill", capacity=1, refill_per_s=1)
        clock[0] += 0.01
        assert not await helpers.rate_limit("m1-refill", capacity=1, refill_per_s=1)
        clock[0] += 1.0
        assert await helpers.rate_limit("m1-refill", capacity=1, refill_per_s=1)
        clock[0] -= 0.5
        assert not await helpers.rate_limit("m1-refill", capacity=1, refill_per_s=1)
        clock[0] += 0.5
        assert not await helpers.rate_limit("m1-refill", capacity=1, refill_per_s=1)
        assert await helpers.rate_limit("m1-expiry", capacity=10, refill_per_s=0.1, ttl_s=1)
        assert await client.ttl("campus:ratelimit:m1-expiry") >= 99
        await client.delete("campus:ratelimit:m1-refill", "campus:ratelimit:m1-refill:ts",
                            "campus:ratelimit:m1-expiry", "campus:ratelimit:m1-expiry:ts")
    return run()


def test_lua_refills_in_seconds_not_milliseconds(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis", reason="Optional M1 profile")

    async def run():
        async with fakeredis.FakeAsyncRedis(decode_responses=True) as client:
            await exercise_refill(client, monkeypatch)
    asyncio.run(run())
