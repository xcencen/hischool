"""Owner isolation and retention against real isolated MySQL/Redis services."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_INTEGRATION") != "1",
    reason="Assistant sessions require the isolated MySQL/Redis Compose stack")

from app.assistant import conversations
from app.assistant.settings import AssistantSettings
from app.bootstrap.config import BootstrapSettings
from app.config import load_settings
from app.database import Database, utc_now
from app.main import create_app
from app.models.assistant import (AssistantAlert, AssistantBudget, AssistantMessage, AssistantRun,
                                 AssistantUsage, Conversation)
from app.models.user import User
from app.utils.jwt import create_access_token


class World:
    def __init__(self):
        self.campus, self.policy = load_settings(), AssistantSettings()
        assert make_url(self.campus.database_url).database == "my_campus_test"
        self.actors, self.headers = {}, {}

    def run(self, action):
        async def invoke():
            database = Database(self.campus.database_url)
            try:
                async with database.session_factory() as db:
                    return await action(db)
            finally:
                await database.dispose()
        return asyncio.run(invoke())

    def seed(self):
        async def action(db):
            for name, role in (("a", "student"), ("b", "admin")):
                row = User(username="session-" + uuid4().hex, name="Synthetic " + name,
                    password="not-a-real-password", role=role, status=1, auth_version=0)
                db.add(row)
                await db.flush()
                self.actors[name] = SimpleNamespace(id=row.id, role=role, status=1, auth_version=0)
                self.headers[name] = {"Authorization": "Bearer " + create_access_token(row.id, 0, self.campus)}
            await db.commit()
        self.run(action)

    def seed_turn(self, public_id, *, status="succeeded", content="question", answer="answer", age_days=0,
                  active=False, private_source=False):
        async def action(db):
            row = await db.scalar(select(Conversation).where(Conversation.public_id == public_id))
            now = utc_now()
            run = AssistantRun(public_id=str(uuid4()), conversation_id=row.id, owner_id=row.owner_id,
                request_key=uuid4().hex, request_hash="f" * 64, status=status, auth_version=0,
                available_at=now, deadline_at=now+timedelta(minutes=3), started_at=now,
                finished_at=now if status in {"succeeded", "failed"} else None,
                model_calls=1, tool_calls=0, cost_limit=Decimal("0.10"), reserved=Decimal("0"),
                spent=Decimal("0.001"), budget_day=now.date(), cancel_requested=False,
                source_jti="private-original-session" if private_source else None,
                lease_token="private-runtime-lease" if private_source else None)
            db.add(run)
            await db.flush()
            for role, text in (("user", content), ("assistant", answer)):
                if text is None:
                    continue
                db.add(AssistantMessage(conversation_id=row.id, run_id=run.id, sequence=row.next_seq,
                    role=role, content=text, citations=[], create_time=now-timedelta(days=age_days),
                    update_time=now-timedelta(days=age_days)))
                row.next_seq += 1
            if active:
                row.active_run_id = run.public_id
            await db.commit()
            return run.public_id
        return self.run(action)

    def cleanup(self):
        async def action(db):
            owners = [actor.id for actor in self.actors.values()]
            convs = list((await db.scalars(select(Conversation.id).where(Conversation.owner_id.in_(owners)))).all())
            run_ids = list((await db.scalars(select(AssistantRun.id).where(
                AssistantRun.conversation_id.in_(convs)).order_by(AssistantRun.id.desc()))).all())
            await db.execute(delete(AssistantMessage).where(AssistantMessage.conversation_id.in_(convs)))
            await db.execute(delete(AssistantUsage).where(AssistantUsage.run_id.in_(run_ids)))
            for run_id in run_ids:
                await db.execute(delete(AssistantRun).where(AssistantRun.id == run_id))
            await db.execute(delete(Conversation).where(Conversation.id.in_(convs)))
            await db.execute(delete(AssistantAlert).where(AssistantAlert.owner_id.in_(owners)))
            await db.execute(delete(AssistantBudget).where(AssistantBudget.scope == "user",
                                                         AssistantBudget.scope_id.in_(owners)))
            await db.execute(delete(User).where(User.id.in_(owners)))
            await db.commit()
        self.run(action)


@pytest.fixture(scope="module")
def client():
    assert make_url(load_settings().database_url).database == "my_campus_test"
    subprocess.run([sys.executable, "-B", "-m", "app.initialize"],
                   cwd=Path(__file__).resolve().parents[1], check=True)
    with TestClient(create_app(BootstrapSettings(), mode="campus")) as client:
        yield client


@pytest.fixture
def world(client):
    value = World()
    value.seed()
    try:
        yield value
    finally:
        value.cleanup()


def create(client, world, *, actor="a", title="Synthetic conversation"):
    response = client.post("/api/assistant/conversations", json={"title": title}, headers=world.headers[actor])
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def test_owner_scoped_crud_disabled_execution_and_soft_delete_scrubs_text(client, world):
    identifier = create(client, world)
    path = "/api/assistant/conversations/" + identifier
    assert client.get(path, headers=world.headers["b"]).status_code == 404
    assert client.patch(path, json={"title": "cross-owner"}, headers=world.headers["b"]).status_code == 404
    assert client.get("/api/assistant/conversations", headers=world.headers["b"]).json()["data"]["total"] == 0
    result = client.patch(path, json={"title": "Renamed", "state": "archived"}, headers=world.headers["a"])
    assert result.status_code == 200 and result.json()["data"]["state"] == "archived"
    result = client.post(path + "/runs", json={"content": "Synthetic prompt", "request_key": "one"},
                         headers=world.headers["a"])
    assert result.status_code == 503
    assert client.patch(path, json={"state": "active"}, headers=world.headers["a"]).status_code == 200
    world.seed_turn(identifier, content="private-body", answer="private-answer")
    assert client.delete(path, headers=world.headers["a"]).status_code == 200
    assert client.get(path, headers=world.headers["a"]).status_code == 404
    assert client.delete(path, headers=world.headers["a"]).status_code == 200
    async def check(db):
        row = await db.scalar(select(Conversation).where(Conversation.public_id == identifier))
        assert row.title == "已删除会话" and row.state == "deleted"
        rows = (await db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id == row.id))).all()
        assert all(item.content is None and not item.citations for item in rows)
        assert await db.scalar(select(AssistantRun.id).where(AssistantRun.conversation_id == row.id)) is not None
    world.run(check)


def test_successful_complete_context_and_message_retention_are_enforced(client, world):
    identifier = create(client, world)
    world.seed_turn(identifier, content="old-private-question", answer="old-private-answer", age_days=8)
    world.seed_turn(identifier, status="failed", content="failed-private-input", answer=None)
    world.seed_turn(identifier, content="orphan-private-input", answer=None)
    world.seed_turn(identifier, content="first " + "中" * 1000, answer="answer-one")
    world.seed_turn(identifier, content="latest question", answer="latest answer")
    async def check(db):
        row = await conversations.get_conversation(db, world.actors["a"], identifier)
        context = await conversations.context_messages(db, row, replace(world.policy, context_max_bytes=4096))
        assert [item["content"] for item in context] == ["first " + "中" * 1000, "answer-one",
                                                       "latest question", "latest answer"]
        assert all("private" not in item["content"] for item in context)
        result = await conversations.purge_expired(db, world.policy)
        assert result["redacted_messages"] >= 2
    world.run(check)
    response = client.get("/api/assistant/conversations/" + identifier + "/messages", headers=world.headers["a"])
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store"
    rows = response.json()["data"]["list"]
    assert rows[0]["redacted"] and rows[0]["content"] is None
    assert rows[1]["redacted"] and rows[1]["citations"] == []
    assert any(item["content"] == "failed-private-input" for item in rows)


def test_running_conversation_rejects_mutation_and_run_dto_is_private(client, world):
    identifier = create(client, world)
    run_id = world.seed_turn(identifier, status="running", active=True, answer=None, private_source=True)
    path = "/api/assistant/conversations/" + identifier
    assert client.patch(path, json={"title": "rename"}, headers=world.headers["a"]).status_code == 409
    assert client.delete(path, headers=world.headers["a"]).status_code == 409
    response = client.get("/api/assistant/runs/" + run_id, headers=world.headers["a"])
    assert response.status_code == 200
    assert response.json()["data"]["conversation_id"] == identifier
    assert "private-" not in response.text
    assert not {"lease_token", "source_jti", "source_exp", "auth_version"} & response.json()["data"].keys()
    assert client.get("/api/assistant/runs/" + run_id, headers=world.headers["b"]).status_code == 404


def test_expired_conversation_hides_title_and_recent_body_before_purge(client, world):
    identifier = create(client, world, title="private-expired-title")
    world.seed_turn(identifier, content="private-new-body", answer="private-answer")
    async def expire(db):
        row = await db.scalar(select(Conversation).where(Conversation.public_id == identifier))
        row.expires_at = utc_now() - timedelta(seconds=1)
        await db.commit()
    world.run(expire)
    path = "/api/assistant/conversations/" + identifier
    response = client.get(path, headers=world.headers["a"])
    assert response.status_code == 200 and response.json()["data"]["state"] == "expired"
    assert "private" not in response.text
    assert client.patch(path, json={"state": "active"}, headers=world.headers["a"]).status_code == 410
    messages = client.get(path + "/messages", headers=world.headers["a"]).json()["data"]["list"]
    assert all(item["redacted"] and item["content"] is None for item in messages)
    async def purge(db):
        await conversations.purge_expired(db, world.policy)
        row = await db.scalar(select(Conversation).where(Conversation.public_id == identifier))
        assert row.title == "已过期会话"
        texts = (await db.scalars(select(AssistantMessage.content).where(AssistantMessage.conversation_id == row.id))).all()
        assert texts and all(value is None for value in texts)
    world.run(purge)
