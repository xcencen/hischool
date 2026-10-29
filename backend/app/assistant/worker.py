"""Optional standalone worker; no startup DDL or implicit environment-file reads."""

import asyncio
import logging
import signal
import time

from redis.asyncio import Redis

from app.ai.pricing import load_price_table
from app.ai.settings import load_llm_settings
from app.assistant import conversations, runs
from app.assistant.executor import RunExecutor
from app.assistant.providers import ChatProvider, check_private_runtime
from app.assistant.settings import load_assistant_settings
from app.config import load_settings
from app.database import Database
from app.mcp.client import CampusMCPClient
from app.mcp.settings import load_mcp_settings


logger = logging.getLogger(__name__)


async def serve(database, redis, settings, executor_factory, *, stop=None):
    """Claim durably, bound local tasks, recover expired leases and redact text."""
    stop = stop or asyncio.Event()
    tasks, maintained = set(), 0
    try:
        while not stop.is_set():
            for task in tasks:
                if task.done() and not task.cancelled() and task.exception() is not None:
                    logger.warning("assistant_task status=failed")
            tasks = {task for task in tasks if not task.done()}
            if time.monotonic() - maintained >= 5:
                await runs.recover_abandoned(database)
                async with asyncio.timeout(10):
                    async with database.session_factory() as db:
                        await conversations.purge_expired(db, settings)
                maintained = time.monotonic()
            if settings.enabled and settings.allow_campus_data and len(tasks) < settings.global_concurrency:
                row = await runs.claim_next(database, redis, settings)
                if row is not None:
                    tasks.add(asyncio.create_task(executor_factory().execute(row)))
                    continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval_s)
            except TimeoutError:
                pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    settings, campus = load_assistant_settings(), load_settings()
    llm = prices = mcp = None
    if settings.enabled and settings.allow_campus_data:
        llm, prices, mcp = load_llm_settings(), load_price_table(), load_mcp_settings()
        check_private_runtime()
        if not llm.configured or prices is None:
            raise ValueError("Assistant model and explicit price configuration are required")
    database = Database(campus.database_url)
    redis = Redis.from_url(campus.redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(name, stop.set)
        except NotImplementedError:
            pass

    def factory():
        return RunExecutor(database, redis, campus, settings, prices,
            ChatProvider(llm, prices, context_max_bytes=settings.context_max_bytes),
            CampusMCPClient(campus, mcp, database, redis))

    try:
        await serve(database, redis, settings, factory, stop=stop)
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    # Do not configure dependency loggers or include exception representations.
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logging.getLogger("app.assistant").addHandler(handler)
    logging.getLogger("app.assistant").setLevel(logging.INFO)
    try:
        asyncio.run(main())
    except (Exception, KeyboardInterrupt):
        logger.error("assistant_worker status=stopped")
        raise SystemExit(1) from None
