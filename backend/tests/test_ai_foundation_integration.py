"""Real disposable MySQL cross-process persistence and real Redis Lua."""

import asyncio
import os

import pytest


pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_AI_INTEGRATION") != "1",
    reason="Run compose.assistant-test.yaml for isolated M1 MySQL/Redis tests")


def test_mysql_checkpoint_is_readable_cross_process_and_cleanup_is_verified():
    from app.ai.checkpoint_probe import DATABASE_VARIABLE, probe
    result = probe(os.environ[DATABASE_VARIABLE])
    assert result == {"status": "passed", "backend": "mysql",
                      "cross_process": True, "cleanup_verified": True}


def test_real_redis_refills_with_correct_units(monkeypatch):
    from redis.asyncio import Redis
    from test_ai_redis import exercise_refill

    async def run():
        async with Redis.from_url(os.environ["CAMPUS_REDIS_URL"], decode_responses=True) as client:
            await exercise_refill(client, monkeypatch)
    asyncio.run(run())
