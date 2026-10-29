"""Actual MySQL locking, limits, deduplication and ambiguous-billing accounting."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url

from app.assistant import budget
from app.config import load_settings
from app.database import Database, utc_now
from app.models.assistant import (AssistantAlert, AssistantBudget, AssistantMessage,
    AssistantRun, AssistantUsage, Conversation)
from app.models.user import User


pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_ASSISTANT_INTEGRATION") != "1",
    reason="Requires the isolated M3 MySQL/Redis assistant profile")
D = Decimal


@pytest.fixture(scope="module", autouse=True)
def initialize():
    assert make_url(load_settings().database_url).database == "my_campus_test"
    subprocess.run([sys.executable, "-B", "-m", "app.initialize"],
        cwd=Path(__file__).resolve().parents[1], check=True)


class World:
    def __init__(self):
        self.url = load_settings().database_url
        assert make_url(self.url).database == "my_campus_test"
        self.day = date(2080, 1, 1) + timedelta(days=int(uuid4().hex[:8], 16) % 10000)
        self.user_ids, self.conversation_ids, self.run_ids = [], [], []

    def run(self, action):
        async def invoke():
            database = Database(self.url)
            try:
                return await action(database)
            finally:
                await database.dispose()
        return asyncio.run(invoke())

    async def create_run(self, db, *, cap="0.10", owner_id=None):
        if owner_id is None:
            user = User(username="budget-" + uuid4().hex, name="Budget synthetic", role="student",
                password="test-only-unused-hash", status=1, auth_version=0)
            db.add(user)
            await db.flush()
            owner_id = user.id
            self.user_ids.append(owner_id)
        conversation = Conversation(public_id=str(uuid4()), owner_id=owner_id, title="Budget test",
            state="active", next_seq=1, expires_at=utc_now() + timedelta(days=7))
        db.add(conversation)
        await db.flush()
        self.conversation_ids.append(conversation.id)
        run = AssistantRun(public_id=str(uuid4()), conversation_id=conversation.id,
            owner_id=owner_id, request_key=uuid4().hex, request_hash="0" * 64,
            status="queued", auth_version=0, available_at=utc_now(), deadline_at=utc_now() + timedelta(minutes=3),
            cost_limit=D(cap), reserved=D(0), spent=D(0), budget_day=self.day)
        db.add(run)
        await db.flush()
        self.run_ids.append(run.id)
        return run

    async def reserve(self, db, run, *, user="1", global_="5"):
        return await budget.reserve_run(db, run, user_daily_limit=D(user),
            global_daily_limit=D(global_), alert_ratio=D(".8"))

    async def call(self, db, run, *, key="model-1", upper=".03"):
        return await budget.start_call(db, run, call_key=key, kind="model",
            upper_bound=D(upper), resource="synthetic-model", price_snapshot={"version": "test-1", "input": "2"})


@pytest.fixture
def world():
    value = World()
    async def baseline(database):
        async with database.session_factory() as db:
            assert await db.scalar(select(AssistantBudget.id).where(AssistantBudget.day == value.day).limit(1)) is None
    value.run(baseline)
    try:
        yield value
    finally:
        async def cleanup(database):
            async with database.session_factory() as db:
                await db.execute(delete(AssistantAlert).where(AssistantAlert.day == value.day))
                await db.execute(delete(AssistantUsage).where(AssistantUsage.run_id.in_(value.run_ids)))
                await db.execute(delete(AssistantMessage).where(AssistantMessage.conversation_id.in_(value.conversation_ids)))
                await db.execute(update(AssistantRun).where(AssistantRun.id.in_(value.run_ids)).values(parent_id=None))
                await db.execute(delete(AssistantRun).where(AssistantRun.id.in_(value.run_ids)))
                await db.execute(delete(Conversation).where(Conversation.id.in_(value.conversation_ids)))
                await db.execute(delete(AssistantBudget).where(AssistantBudget.day == value.day))
                await db.execute(delete(User).where(User.id.in_(value.user_ids)))
                await db.commit()
        value.run(cleanup)


def test_reservation_settlement_and_release_are_atomic_and_idempotent(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            assert await world.reserve(db, run)
            assert await world.reserve(db, run)
            usage = await world.call(db, run)
            await budget.settle_call(db, run, usage, cost=D(".007"), input_tokens=100,
                output_tokens=20, cache_read_tokens=10, price_version="test-1", latency_ms=5)
            await budget.settle_call(db, run, usage, cost=D(".02"), input_tokens=500, output_tokens=100)
            assert run.spent == D(".007") and run.reserved == D(".093")
            await budget.release_run(db, run)
            await budget.release_run(db, run)
            rows = (await db.scalars(select(AssistantBudget).where(AssistantBudget.day == world.day))).all()
            assert len(rows) == 2 and all(row.spent == D(".007") and row.reserved == 0 for row in rows)
            assert run.reserved == 0 and usage.charged == D(".007")
            await db.commit()
    world.run(action)


def test_unknown_provider_usage_consumes_its_upper_bound_and_preserves_null_counts(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            assert await world.reserve(db, run)
            usage = await world.call(db, run)
            await budget.settle_call(db, run, usage, cost=None, unknown=True, input_tokens=100)
            assert usage.state == "unknown" and usage.charged == D(".03") and usage.usage_unknown
            assert usage.input_tokens is None and usage.output_tokens is None
            await budget.release_run(db, run)
            assert run.spent == D(".03") and run.reserved == 0
            assert await db.scalar(select(func.count()).select_from(AssistantAlert).where(
                AssistantAlert.scope == "run", AssistantAlert.scope_id == run.id,
                AssistantAlert.kind == "unknown_usage")) == 1
            await db.commit()
    world.run(action)


def test_crashed_dispatch_is_conservatively_settled_once_on_run_release(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            assert await world.reserve(db, run)
            first = await world.call(db, run, key="model-1", upper=".02")
            second = await world.call(db, run, key="model-2", upper=".04")
            await budget.release_run(db, run)
            await budget.release_run(db, run)
            assert first.state == second.state == "unknown"
            assert run.spent == D(".06") and run.reserved == 0
            await db.commit()
    world.run(action)


def test_call_subreservations_prevent_overspending_and_duplicate_dispatch(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            assert await world.reserve(db, run)
            await world.call(db, run, upper=".08")
            with pytest.raises(budget.BudgetExceeded):
                await world.call(db, run, key="model-2", upper=".03")
            with pytest.raises(RuntimeError, match="already exists"):
                await world.call(db, run, upper=".01")
            assert await db.scalar(select(func.count()).select_from(AssistantUsage).where(
                AssistantUsage.run_id == run.id)) == 1
            await budget.release_run(db, run)
            await db.commit()
    world.run(action)


def test_actual_provider_overrun_is_not_hidden_or_clamped(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            assert await world.reserve(db, run, user=".1", global_=".1")
            usage = await world.call(db, run)
            await budget.settle_call(db, run, usage, cost=D(".2"), input_tokens=100, output_tokens=200)
            assert usage.charged == run.spent == D(".2") and run.reserved == 0
            await budget.release_run(db, run)
            rows = (await db.scalars(select(AssistantBudget).where(AssistantBudget.day == world.day))).all()
            assert all(row.spent == D(".2") and row.reserved == 0 for row in rows)
            scopes = set((await db.execute(select(AssistantAlert.scope).where(
                AssistantAlert.day == world.day, AssistantAlert.kind == "overrun"))).scalars())
            assert scopes == {"global", "user", "run"}
            await db.commit()
    world.run(action)


def test_threshold_alert_is_deduplicated_and_does_not_clear_acknowledgment(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            assert await world.reserve(db, run, user=".125", global_=".125")
            user_alert = await db.scalar(select(AssistantAlert).where(AssistantAlert.day == world.day,
                AssistantAlert.scope == "user", AssistantAlert.kind == "threshold"))
            user_alert.acknowledged = True
            await db.flush()
            usage = await world.call(db, run)
            await budget.settle_call(db, run, usage, cost=D(".01"), input_tokens=100, output_tokens=20)
            await db.refresh(user_alert)
            assert user_alert.acknowledged
            assert await db.scalar(select(func.count()).select_from(AssistantAlert).where(
                AssistantAlert.day == world.day, AssistantAlert.kind == "threshold")) == 2
            await budget.release_run(db, run)
            await db.commit()
    world.run(action)


def test_custom_ninety_percent_threshold_is_not_replaced_by_eighty_percent_on_settlement(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            assert await budget.reserve_run(db, run, user_daily_limit=D(".125"),
                global_daily_limit=D(".125"), alert_ratio=D(".9"))
            assert await db.scalar(select(func.count()).select_from(AssistantAlert).where(
                AssistantAlert.day == world.day, AssistantAlert.kind == "threshold")) == 0
            usage = await world.call(db, run)
            await budget.settle_call(db, run, usage, cost=D(".01"), input_tokens=100, output_tokens=20)
            assert await db.scalar(select(func.count()).select_from(AssistantAlert).where(
                AssistantAlert.day == world.day, AssistantAlert.kind == "threshold")) == 0
            await budget.release_run(db, run)
            assert run.spent == D(".01") and run.reserved == 0
            await db.commit()
    world.run(action)


def test_daily_capacity_reduction_is_immediate_but_increase_waits_until_new_day(world):
    async def action(database):
        async with database.session_factory() as db:
            first = await world.create_run(db)
            assert await world.reserve(db, first, user=".2", global_=".2")
            second = await world.create_run(db, owner_id=first.owner_id)
            assert not await world.reserve(db, second, user=".05", global_=".05")
            await budget.release_run(db, first)
            third = await world.create_run(db, owner_id=first.owner_id)
            assert not await world.reserve(db, third, user=".2", global_=".2")
            assert all(row.cap == D(".05") for row in (await db.scalars(select(AssistantBudget).where(
                AssistantBudget.day == world.day))).all())
            await db.commit()
    world.run(action)


def test_snapshot_is_read_only_and_hides_global_consumption_by_default(world):
    async def action(database):
        async with database.session_factory() as db:
            run = await world.create_run(db)
            result = await budget.snapshot(db, run.owner_id, world.day,
                user_daily_limit=D(1), global_daily_limit=D(5))
            assert "global" not in result and result["user"]["available"] == "1.00000000"
            assert await db.scalar(select(func.count()).select_from(AssistantBudget).where(
                AssistantBudget.day == world.day)) == 0
            await db.commit()
    world.run(action)


def test_concurrent_admissions_cannot_both_take_the_last_global_capacity(world):
    async def action(database):
        async with database.session_factory() as db:
            first = await world.create_run(db, cap=".15")
            second = await world.create_run(db, cap=".15")
            ids = [first.id, second.id]
            await db.commit()
        async def admit(run_id):
            async with database.session_factory() as db:
                run = await db.scalar(select(AssistantRun).where(AssistantRun.id == run_id).with_for_update())
                accepted = await world.reserve(db, run, user=".2", global_=".2")
                await db.commit()
                return accepted
        result = await asyncio.gather(*(admit(run_id) for run_id in ids))
        assert sorted(result) == [False, True]
        async with database.session_factory() as db:
            row = await db.scalar(select(AssistantBudget).where(AssistantBudget.day == world.day,
                AssistantBudget.scope == "global"))
            assert row.reserved == D(".15") and row.spent == 0
    world.run(action)
