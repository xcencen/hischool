"""Actual MySQL snapshots and Redis leases; no model or MCP requests."""

import asyncio
from datetime import timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url

from app.assistant import stream
from app.assistant.settings import AssistantSettings
from app.common.exceptions import BusinessException
from app.config import load_settings
from app.database import Database, utc_now
from app.models.assistant import AssistantMessage, AssistantRun, Conversation
from app.models.user import User


pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_ASSISTANT_INTEGRATION") != "1",
    reason="Requires the isolated M4 MySQL/Redis stack")


class Request:
    async def is_disconnected(self):
        return False


def decode(block):
    lines = block.decode().strip().splitlines()
    name = next((line[7:] for line in lines if line.startswith("event: ")), None)
    data = next((json.loads(line[6:]) for line in lines if line.startswith("data: ")), None)
    return name, data


class World:
    def __init__(self):
        self.campus, self.policy = load_settings(), AssistantSettings()
        assert make_url(self.campus.database_url).database == "my_campus_test"
        self.owners, self.payloads = [], []
        self.conversation_id = self.run_id = None

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
                for role in ("student", "admin"):
                    user = User(username="stream-"+uuid4().hex, name="Synthetic SSE user",
                        password="unused-synthetic-password", role=role, status=1, auth_version=0)
                    db.add(user)
                    await db.flush()
                    self.owners.append(user.id)
                    self.payloads.append({"sub":str(user.id), "auth_version":0,
                        "jti":uuid4().hex, "exp":int(time.time())+3600})
                now = utc_now()
                conversation = Conversation(public_id=str(uuid4()), owner_id=self.owners[0], title="Synthetic SSE",
                    state="active", next_seq=3, expires_at=now+timedelta(days=7))
                db.add(conversation)
                await db.flush()
                self.conversation_id = conversation.id
                run = AssistantRun(public_id=str(uuid4()), conversation_id=conversation.id, owner_id=self.owners[0],
                    request_key=uuid4().hex, request_hash="0"*64, status="succeeded", auth_version=0,
                    source_jti="private-original-login", source_exp=int(time.time())+3600,
                    lease_token="private-worker-lease", available_at=now, deadline_at=now+timedelta(minutes=3),
                    started_at=now, finished_at=now, model_calls=1, tool_calls=0,
                    cost_limit=Decimal(".10"), spent=Decimal(".001"), reserved=Decimal(0), budget_day=now.date())
                db.add(run)
                await db.flush()
                self.run_id, self.public_id = run.id, run.public_id
                db.add(AssistantMessage(conversation_id=conversation.id, run_id=run.id, sequence=1,
                    role="user", content="Synthetic question", citations=[]))
                db.add(AssistantMessage(conversation_id=conversation.id, run_id=run.id, sequence=2,
                    role="assistant", content="中"*130, citations=[]))
                await db.commit()
        self.run(action)

    def cleanup(self):
        async def action(database, cache):
            async with database.session_factory() as db:
                await db.execute(delete(AssistantMessage).where(AssistantMessage.run_id == self.run_id))
                await db.execute(delete(AssistantRun).where(AssistantRun.id == self.run_id))
                await db.execute(delete(Conversation).where(Conversation.id == self.conversation_id))
                await db.execute(delete(User).where(User.id.in_(self.owners)))
                await db.commit()
            for payload in self.payloads:
                await cache.delete("campus:revoked:"+payload["jti"])
        self.run(action)


@pytest.fixture(scope="module", autouse=True)
def initialize():
    assert make_url(load_settings().database_url).database == "my_campus_test"
    subprocess.run([sys.executable,"-B","-m","app.initialize"],
                   cwd=Path(__file__).resolve().parents[1],check=True)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(stream, "CHUNK_INTERVAL", 0)
    value = World()
    value.seed()
    try:
        yield value
    finally:
        value.cleanup()


def test_snapshot_enforces_owner_even_for_admin_and_exposes_only_public_fields(world):
    async def action(database, cache):
        run, message = await stream.snapshot(database, cache, world.policy, world.public_id,
            stream.Identity.from_payload(world.payloads[0]))
        assert run["status"] == "succeeded" and message["content"] == "中"*130
        assert run["conversation_id"] != world.conversation_id
        assert not {"source_jti","source_exp","lease_token","auth_version"}.intersection(run)
        assert "private-original" not in repr((run,message))
        with pytest.raises(BusinessException) as error:
            await stream.snapshot(database, cache, world.policy, world.public_id,
                stream.Identity.from_payload(world.payloads[1]))
        assert error.value.code == 404
    world.run(action)


def test_cursor_reconnect_reads_saved_reply_without_creating_another_run(world):
    async def action(database, cache):
        response = await stream.open_stream(Request(), database, cache, world.policy, world.public_id,
            world.payloads[0], after=2)
        blocks = [decode(block) async for block in response.body_iterator]
        await response.background()
        assert [name for name,_ in blocks] == ["status","delta","done"]
        assert blocks[1][1] == {"run_id":world.public_id,"sequence":3,"text":"中中"}
        assert blocks[-1][1]["message"]["content"] == "中"*130
        async with database.session_factory() as db:
            rows = (await db.scalars(select(AssistantRun.id).where(
                AssistantRun.conversation_id == world.conversation_id))).all()
            assert rows == [world.run_id]
        assert await cache.zcard(f"campus:assistant:streams:user:{world.owners[0]}") == 0
    world.run(action)


@pytest.mark.parametrize("revocation", ["redis", "auth_version"])
def test_each_segment_rechecks_real_redis_and_mysql_identity(world, revocation):
    async def action(database, cache):
        response = await stream.open_stream(Request(), database, cache, world.policy, world.public_id,
                                           world.payloads[0])
        iterator = response.body_iterator
        assert decode(await anext(iterator))[0] == "status"
        assert decode(await anext(iterator))[0] == "delta"
        if revocation == "redis":
            await cache.set("campus:revoked:"+world.payloads[0]["jti"],"1",ex=60)
        else:
            async with database.session_factory() as db:
                await db.execute(update(User).where(User.id == world.owners[0]).values(auth_version=1))
                await db.commit()
        assert decode(await anext(iterator)) == ("error",{"reason":"unauthenticated"})
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        await response.background()
        assert await cache.zcard(f"campus:assistant:streams:user:{world.owners[0]}") == 0
    world.run(action)


@pytest.mark.parametrize("change,reason", [("conversation","expired"),("message","expired"),("delete","not_found")])
def test_expiry_or_deletion_between_segments_prevents_remaining_body(world, change, reason):
    async def action(database, cache):
        response = await stream.open_stream(Request(), database, cache, world.policy, world.public_id,
                                           world.payloads[0])
        iterator = response.body_iterator
        await anext(iterator)
        assert decode(await anext(iterator))[0] == "delta"
        async with database.session_factory() as db:
            if change == "conversation":
                await db.execute(update(Conversation).where(Conversation.id == world.conversation_id)
                    .values(expires_at=utc_now()-timedelta(seconds=1)))
            elif change == "message":
                await db.execute(update(AssistantMessage).where(AssistantMessage.run_id == world.run_id,
                    AssistantMessage.role == "assistant").values(create_time=utc_now()-timedelta(days=8)))
            else:
                await db.execute(update(Conversation).where(Conversation.id == world.conversation_id).values(state="deleted"))
            await db.commit()
        assert decode(await anext(iterator)) == ("error",{"reason":reason})
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        await response.background()
    world.run(action)


def test_actual_redis_lease_enforces_user_capacity_and_releases_slots(world):
    async def action(database, cache):
        first = stream.ConnectionLease(cache, world.owners[0])
        second = stream.ConnectionLease(cache, world.owners[0])
        third = stream.ConnectionLease(cache, world.owners[0])
        try:
            await first.acquire()
            await second.acquire()
            with pytest.raises(BusinessException) as error:
                await third.acquire()
            assert error.value.code == 429
            await first.renew()
            await first.close()
            await third.acquire()
            # Expired ownership cannot recreate a slot even if capacity is free.
            await cache.zrem(first.keys[0],third.token)
            with pytest.raises(BusinessException) as expired:
                await third.renew()
            assert expired.value.code == 503
        finally:
            await first.close()
            await second.close()
            await third.close()
        assert await cache.zcard(first.keys[1]) == 0
    world.run(action)
