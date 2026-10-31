"""Linux-only disposable worker for the real SIGKILL recovery acceptance test."""
import asyncio
from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.ai.pricing import PriceTable
from app.assistant import runs
from app.assistant.executor import RunExecutor
from app.assistant.settings import AssistantSettings
from app.assistant.worker import serve
from app.config import load_settings
from app.database import Database
from app.models.assistant import AssistantRun


async def main(expected_id, day, marker):
    assert os.name == "posix"
    campus = load_settings()
    assert make_url(campus.database_url).database == "my_campus_test"
    assert os.environ.get("CAMPUS_ASSISTANT_INTEGRATION") == "1"
    marker = Path(marker).resolve()
    assert str(marker).startswith("/tmp/")
    settings = AssistantSettings(enabled=True, allow_campus_data=True, lease_s=30, poll_interval_s=.05)
    database = Database(campus.database_url)
    cache = Redis.from_url(campus.redis_url, decode_responses=True,
        socket_connect_timeout=3, socket_timeout=3)
    runs.budget_day = lambda: date.fromisoformat(day)
    original_claim = runs.claim_next
    claimed = False

    async def claim_only_expected(database, redis, settings):
        nonlocal claimed
        if claimed:
            return None
        # This helper is confined to the serial isolated integration stack.
        # Refuse to run if any unrelated queued work is present.
        async with database.session_factory() as db:
            queued = list((await db.scalars(select(AssistantRun.public_id)
                .where(AssistantRun.status == "queued"))).all())
            assert queued == [expected_id], "Unexpected work in disposable test queue"
        row = await original_claim(database, redis, settings)
        assert row is not None and row.public_id == expected_id
        claimed = True
        return row
    runs.claim_next = claim_only_expected

    class BlockingProvider:
        def estimate(self, messages):
            return Decimal(".01")

        async def complete(self, messages):
            # RunExecutor invokes complete only AFTER committing the call intent.
            with marker.open("a", encoding="utf-8") as target:
                target.write("dispatch\n")
                target.flush()
                os.fsync(target.fileno())
            await asyncio.Event().wait()

        async def aclose(self):
            pass

    class NoTools:
        async def call(self, *args, **kwargs):
            raise AssertionError("Interruption fixture must never request a tool")

    class ExpectedExecutor(RunExecutor):
        async def execute(self, row):
            assert row.public_id == expected_id
            await super().execute(row)

    prices = PriceTable(Decimal(2), Decimal(8), Decimal(".2"), "kill-synthetic", "isolated-test")
    def factory():
        return ExpectedExecutor(database, cache, campus, settings, prices, BlockingProvider(), NoTools())

    try:
        await serve(database, cache, settings, factory)
    finally:
        await cache.aclose()
        await database.dispose()


if __name__ == "__main__":
    assert len(sys.argv) == 5 and sys.argv[1] == "--isolated"
    asyncio.run(main(*sys.argv[2:]))
