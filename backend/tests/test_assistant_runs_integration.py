"""Durable MySQL/Redis admission, fencing and injected LangGraph execution."""

import asyncio
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url

pytest.importorskip("langgraph", reason="Requires the optional assistant profile")
pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_ASSISTANT_INTEGRATION") != "1",
    reason="Requires the isolated M3 MySQL/Redis assistant profile")

from app.ai.pricing import PriceTable
from app.assistant import budget, conversations, runs
from app.assistant.executor import RunExecutor
from app.assistant.providers import ModelReply, ProviderFailure, ToolRequest
from app.assistant.settings import AssistantSettings
from app.common.exceptions import BusinessException
from app.config import load_settings
from app.database import Database, utc_now
from app.mcp.executor import outcome
from app.models.assistant import (AssistantAlert, AssistantBudget, AssistantMessage,
    AssistantRun, AssistantUsage, Conversation)
from app.models.user import User
from app.utils.jwt import create_access_token, decode_access_token


D = Decimal
PRICES = PriceTable(D(2), D(8), D(".2"), "m3-synthetic-test", "isolated-test")
USAGE = {"input_tokens": 100, "output_tokens": 20, "input_token_details": {"cache_read": 0}}


class MockProvider:
    def __init__(self, replies=None, *, upper=".01"):
        self.replies = list(replies or [ModelReply("Synthetic answer", usage=USAGE)])
        self.messages, self.calls, self.closed = [], 0, False
        self.upper = D(upper)

    def estimate(self, messages):
        return self.upper

    async def complete(self, messages):
        self.messages.append(deepcopy(messages))
        self.calls += 1
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self):
        self.closed = True


class BlockingProvider(MockProvider):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.cancelled = False

    async def complete(self, messages):
        self.calls += 1
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class MemoryTools:
    def __init__(self):
        self.calls = []
        self.active = self.maximum = 0

    async def call(self, name, arguments, *, campus_token, run_id):
        self.calls.append((name, arguments, run_id))
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(.02)
            if name == "campus_get_my_schedules":
                return outcome(name, run_id=run_id, data={"start_date": "2030-01-07", "end_date": "2030-01-07",
                    "timezone": "Asia/Shanghai", "items": [], "truncated": False})
            return outcome(name, run_id=run_id, data={"items": [], "total": 0, "page": 1, "page_size": 5})
        finally:
            self.active -= 1


@pytest.fixture(scope="module", autouse=True)
def initialize():
    assert make_url(load_settings().database_url).database == "my_campus_test"
    subprocess.run([sys.executable, "-B", "-m", "app.initialize"],
        cwd=Path(__file__).resolve().parents[1], check=True)


class World:
    def __init__(self):
        self.campus = load_settings()
        assert make_url(self.campus.database_url).database == "my_campus_test"
        self.settings = AssistantSettings(enabled=True, allow_campus_data=True, lease_s=15,
            retry_delay_s=.01, embedding_price_per_1m=D(".5"), embedding_price_version="test-embedding")
        self.day = date(2200, 1, 1) + timedelta(days=int(uuid4().hex[:8], 16) % 10000)
        self.current_day = self.day
        self.actors, self.payloads = {}, {}

    def run(self, action):
        async def invoke():
            database = Database(self.campus.database_url)
            cache = Redis.from_url(self.campus.redis_url, decode_responses=True,
                                   socket_connect_timeout=3, socket_timeout=3)
            try:
                return await action(database, cache)
            finally:
                await cache.aclose()
                await database.dispose()
        return asyncio.run(invoke())

    def seed(self):
        async def action(database, cache):
            async with database.session_factory() as db:
                assert await db.scalar(select(AssistantBudget.id).where(AssistantBudget.day == self.day).limit(1)) is None
                for name in ("a", "b", "c"):
                    actor = User(username="run-" + uuid4().hex, name="Synthetic run test", role="student",
                        password="test-only-unused-hash", status=1, auth_version=0)
                    db.add(actor)
                    await db.flush()
                    self.actors[name] = actor
                    self.payloads[name] = decode_access_token(create_access_token(actor.id, 0, self.campus), self.campus)
                await db.commit()
        self.run(action)

    async def conversation(self, database, name="a"):
        async with database.session_factory() as db:
            return await conversations.create_conversation(db, self.actors[name], self.settings, title="Synthetic run")

    async def submit(self, database, cache, conversation, *, name="a", content="Synthetic question", key=None):
        async with database.session_factory() as db:
            return await runs.create_run(db, cache, self.actors[name], self.payloads[name],
                conversation.public_id, content, key or uuid4().hex, self.settings)

    async def inspect(self, database, public_id):
        async with database.session_factory() as db:
            row = await db.scalar(select(AssistantRun).where(AssistantRun.public_id == public_id))
            usages = list((await db.scalars(select(AssistantUsage).where(AssistantUsage.run_id == row.id)
                .order_by(AssistantUsage.id))).all())
            messages = list((await db.scalars(select(AssistantMessage).where(AssistantMessage.run_id == row.id)
                .order_by(AssistantMessage.sequence))).all())
            return row, usages, messages

    def executor(self, database, cache, provider, tools=None):
        return RunExecutor(database, cache, self.campus, self.settings, PRICES, provider, tools or MemoryTools())

    def cleanup(self):
        async def action(database, cache):
            ids = [actor.id for actor in self.actors.values()]
            async with database.session_factory() as db:
                run_ids = list((await db.scalars(select(AssistantRun.id).where(AssistantRun.owner_id.in_(ids)))).all())
                await db.execute(delete(AssistantAlert).where(AssistantAlert.day == self.day))
                await db.execute(delete(AssistantUsage).where(AssistantUsage.run_id.in_(run_ids)))
                await db.execute(delete(AssistantMessage).where(AssistantMessage.run_id.in_(run_ids)))
                await db.execute(update(AssistantRun).where(AssistantRun.id.in_(run_ids)).values(parent_id=None))
                await db.execute(delete(AssistantRun).where(AssistantRun.id.in_(run_ids)))
                await db.execute(delete(Conversation).where(Conversation.owner_id.in_(ids)))
                await db.execute(delete(AssistantBudget).where(AssistantBudget.day == self.day))
                await db.execute(delete(User).where(User.id.in_(ids)))
                await db.commit()
            for name, actor in self.actors.items():
                await cache.delete("campus:ratelimit:assistant:submit:" + str(actor.id),
                    "campus:ratelimit:assistant:submit:" + str(actor.id) + ":ts",
                    "campus:revoked:" + self.payloads[name]["jti"])
        self.run(action)


@pytest.fixture
def world(monkeypatch):
    value = World()
    monkeypatch.setattr(runs, "budget_day", lambda: value.current_day)
    value.seed()
    try:
        yield value
    finally:
        value.cleanup()


def test_run_admission_is_idempotent_conflicts_are_rejected_and_retry_links_parent(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        first = await world.submit(database, cache, conversation, key="stable-key")
        second = await world.submit(database, cache, conversation, key="stable-key")
        assert first.public_id == second.public_id
        with pytest.raises(BusinessException) as error:
            await world.submit(database, cache, conversation, key="stable-key", content="Different question")
        assert error.value.code == 409
        with pytest.raises(BusinessException) as error:
            await world.submit(database, cache, conversation, key="other-key")
        assert error.value.code == 409
        async with database.session_factory() as db:
            await runs.cancel_run(db, cache, world.actors["a"], first.public_id, world.settings)
        async with database.session_factory() as db:
            retried = await runs.retry_run(db, cache, world.actors["a"], world.payloads["a"],
                first.public_id, "retry-key", world.settings)
            assert retried.parent_id == first.id and retried.public_id != first.public_id
        async with database.session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(AssistantRun).where(
                AssistantRun.conversation_id == conversation.id)) == 2
    world.run(action)


def test_concurrent_submissions_allow_only_one_active_run_per_conversation(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        async def submit():
            try:
                return await world.submit(database, cache, conversation)
            except BusinessException as error:
                return error.code
        values = await asyncio.gather(submit(), submit())
        assert sum(isinstance(value, AssistantRun) for value in values) == 1
        assert values.count(409) == 1
    world.run(action)


def test_multiple_workers_enforce_per_user_and_global_execution_capacity(world):
    async def action(database, cache):
        for name in ("a", "a", "b", "c"):
            conversation = await world.conversation(database, name)
            await world.submit(database, cache, conversation, name=name)
        values = await asyncio.gather(*(runs.claim_next(database, cache, world.settings) for _ in range(3)))
        claimed = [row for row in values if row is not None]
        assert len(claimed) == 2 and len({row.owner_id for row in claimed}) == 2
        first = next(row for row in claimed if row.owner_id == world.actors["a"].id)
        await runs.finish(database, first.public_id, first.lease_token, status="cancelled", reason="cancelled")
        next_run = await runs.claim_next(database, cache, world.settings)
        assert next_run is not None and next_run.owner_id == world.actors["a"].id
    world.run(action)


def test_cancel_queued_run_releases_both_daily_reservations_without_dispatch(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        row = await world.submit(database, cache, conversation)
        async with database.session_factory() as db:
            cancelled = await runs.cancel_run(db, cache, world.actors["a"], row.public_id, world.settings)
        assert cancelled.status == "cancelled" and cancelled.reserved == 0 and cancelled.spent == 0
        assert cancelled.source_jti is None and cancelled.source_exp is None
        assert await runs.claim_next(database, cache, world.settings) is None
        async with database.session_factory() as db:
            assert all(item.reserved == 0 and item.spent == 0 for item in (await db.scalars(
                select(AssistantBudget).where(AssistantBudget.day == world.day))).all())
            assert (await db.get(Conversation, conversation.id)).active_run_id is None
    world.run(action)


def test_expired_or_previous_day_queue_is_not_dispatched(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        row = await world.submit(database, cache, conversation)
        world.current_day += timedelta(days=1)
        assert await runs.claim_next(database, cache, world.settings) is None
        final, usage, _ = await world.inspect(database, row.public_id)
        assert final.status == "expired" and final.reason == "queue_expired" and final.reserved == 0
        assert not usage
    world.run(action)


def test_lost_worker_intent_is_settled_once_and_stale_worker_cannot_replay(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        row = await runs.claim_next(database, cache, world.settings)
        async with database.session_factory() as db:
            locked, _ = await runs._locked(db, row.public_id)
            await budget.start_call(db, locked, call_key="crashed-model", kind="model", upper_bound=D(".03"),
                resource="synthetic", price_snapshot={"version": "test"})
            locked.lease_until = utc_now() - timedelta(seconds=1)
            await db.commit()
        assert await runs.recover_abandoned(database) == 1
        assert await runs.recover_abandoned(database) == 0
        provider = MockProvider()
        await world.executor(database, cache, provider).execute(row)
        final, usages, messages = await world.inspect(database, queued.public_id)
        assert final.status == "failed" and final.reason == "interrupted"
        assert final.spent == D(".03") and final.reserved == 0
        assert len(usages) == 1 and usages[0].state == "unknown" and usages[0].charged == D(".03")
        assert provider.calls == 0 and not any(message.role == "assistant" for message in messages)
    world.run(action)


def test_executor_persists_successful_turns_and_runs_read_tools_concurrently(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation, content="First synthetic question")
        tools = MemoryTools()
        first_provider = MockProvider([
            ModelReply("", [ToolRequest("call_one", "campus_get_my_schedules", {}),
                            ToolRequest("call_two", "campus_list_notices", {})], USAGE),
            ModelReply("First synthetic answer", usage=USAGE)])
        row = await runs.claim_next(database, cache, world.settings)
        await world.executor(database, cache, first_provider, tools).execute(row)
        final, usage, messages = await world.inspect(database, queued.public_id)
        assert final.status == "succeeded" and final.model_calls == 2 and final.tool_calls == 2
        assert final.spent == D(".00072") and final.reserved == 0
        assert tools.maximum == 2 and len(tools.calls) == 2 and first_provider.closed
        assert len(messages) == 2 and messages[-1].content == "First synthetic answer"
        assert len(usage) == 4 and sum(item.charged for item in usage) == final.spent
        await world.submit(database, cache, conversation, content="Second synthetic question")
        second_provider = MockProvider([ModelReply("Second synthetic answer", usage=USAGE)])
        row = await runs.claim_next(database, cache, world.settings)
        await world.executor(database, cache, second_provider).execute(row)
        observed = second_provider.messages[0]
        assert observed[0]["role"] == "system"
        assert observed[1:] == [{"role": "user", "content": "First synthetic question"},
            {"role": "assistant", "content": "First synthetic answer"},
            {"role": "user", "content": "Second synthetic question"}]
    world.run(action)


def test_definitive_rate_limit_retries_with_new_intent_but_no_double_charge(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        provider = MockProvider([ProviderFailure("rate_limited", retryable=True, uncertain=False),
            ModelReply("Recovered synthetic answer", usage=USAGE)])
        row = await runs.claim_next(database, cache, world.settings)
        await world.executor(database, cache, provider).execute(row)
        final, usage, _ = await world.inspect(database, queued.public_id)
        assert final.status == "succeeded" and provider.calls == 2 and final.model_calls == 2
        assert [item.attempt for item in usage] == [1, 2]
        assert [item.charged for item in usage] == [D(0), D(".00036")]
        assert final.spent == D(".00036") and final.reserved == 0
    world.run(action)


def test_uncertain_timeout_is_not_retried_and_consumes_its_reserved_bound(world, caplog):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        provider = MockProvider([ProviderFailure("timeout", retryable=False, uncertain=True)], upper=".025")
        row = await runs.claim_next(database, cache, world.settings)
        await world.executor(database, cache, provider).execute(row)
        final, usage, messages = await world.inspect(database, queued.public_id)
        assert final.status == "failed" and final.reason == "timeout" and provider.calls == 1
        assert final.spent == D(".025") and final.reserved == 0
        assert usage[0].state == "unknown" and usage[0].input_tokens is None
        assert len(messages) == 1 and messages[0].role == "user"
    world.run(action)


@pytest.mark.parametrize("reason", ["cancel", "logout", "permission"])
def test_inflight_cancellation_or_identity_revocation_cancels_provider_and_hides_answer(world, reason):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        provider = BlockingProvider()
        row = await runs.claim_next(database, cache, world.settings)
        pending = asyncio.create_task(world.executor(database, cache, provider).execute(row))
        await asyncio.wait_for(provider.entered.wait(), timeout=3)
        if reason == "cancel":
            async with database.session_factory() as db:
                await runs.cancel_run(db, cache, world.actors["a"], row.public_id, world.settings)
        elif reason == "logout":
            await cache.set("campus:revoked:" + world.payloads["a"]["jti"], "1", ex=60)
        else:
            async with database.session_factory() as db:
                await db.execute(update(User).where(User.id == world.actors["a"].id).values(auth_version=1))
                await db.commit()
        await asyncio.wait_for(pending, timeout=8)
        final, usage, messages = await world.inspect(database, queued.public_id)
        assert provider.cancelled and provider.closed
        assert final.status == ("cancelled" if reason == "cancel" else "failed")
        assert final.reason == ("cancelled" if reason == "cancel" else "unauthenticated")
        assert final.spent == D(".01") and final.reserved == 0 and usage[0].state == "unknown"
        assert all(message.role != "assistant" for message in messages)
    world.run(action)
