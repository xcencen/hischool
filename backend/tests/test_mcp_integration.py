"""Real HTTP MCP, MySQL, Redis and FAISS; embeddings use a local test double."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time as clock
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url

pytest.importorskip("fastmcp", reason="Requires optional assistant profile")
pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_MCP_INTEGRATION") != "1",
    reason="MCP integration requires the isolated MySQL/Redis Compose stack")

from app.config import load_settings
from app.database import Database
from app.knowledge.settings import KnowledgeSettings
from app.mcp.auth import issue_delegation
from app.mcp.catalog import TOOLS
from app.mcp.client import CampusMCPClient
from app.mcp.executor import ToolLimits
from app.mcp.runtime import MCPResources
from app.mcp.server import create_app
from app.mcp.settings import MCPSettings
from app.models.activity import Activity, ActivityRegistration
from app.models.course import Course
from app.models.enrollment import CourseEnrollment
from app.models.knowledge import (KnowledgeChunk, KnowledgeDocument, KnowledgeIndex,
    KnowledgePage, KnowledgeState, KnowledgeVersion)
from app.models.notice import Notice, NoticeCategory
from app.models.schedule import Schedule
from app.models.user import User
from app.services import knowledge_service
from app.utils.jwt import create_access_token, decode_access_token


class Embedder:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.pause = self.fail = self.cancelled = False

    async def embed_texts(self, texts):
        self.entered.set()
        try:
            while self.pause and not self.release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.fail:
            raise RuntimeError("private-embedding-error")
        return [[1.0] + [0.0] * 1023 for _ in texts]


class World:
    def __init__(self, folder):
        self.campus = load_settings()
        assert make_url(self.campus.database_url).database == "my_campus_test"
        self.tag = "MCP-" + uuid4().hex[:16]
        self.embedder = Embedder()
        self.knowledge = KnowledgeSettings(api_key="isolated-test-only",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            source_dir=folder / "sources", index_dir=folder / "indexes")
        self.indexes, self.document_ids = [], []
        self.previous_index_id = None
        self.tokens = {}

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
                self.users = {}
                for name, role in (("a", "student"), ("b", "student"),
                                   ("ta", "teacher"), ("tb", "teacher"), ("admin", "admin")):
                    row = User(username=self.tag + name, name="private-person-" + name,
                        password="private-password-hash", email="private@example.test",
                        phone="private-phone", role=role, status=1, auth_version=0)
                    db.add(row)
                    await db.flush()
                    self.users[name] = row.id
                    self.tokens[name] = create_access_token(row.id, 0, self.campus)
                self.courses = []
                for name in ("a", "b"):
                    row = Course(name=self.tag + name, code=self.tag + name, teacher_id=self.users["t" + name], status=1)
                    db.add(row)
                    await db.flush()
                    self.courses.append(row.id)
                    db.add(CourseEnrollment(course_id=row.id, user_id=self.users[name]))
                    db.add(Schedule(course_id=row.id, class_date=date(2030, 1, 7), start_time=time(8),
                        end_time=time(9), period="1", location="test-" + name))
                categories = [NoticeCategory(code=self.tag + str(i), name=self.tag + str(i), status=1-i)
                              for i in range(2)]
                db.add_all(categories)
                await db.flush()
                self.category_ids = [row.id for row in categories]
                self.notices = []
                for i, state in enumerate(("published", "draft", "published")):
                    row = Notice(code=self.tag + str(i), title=self.tag + str(i), content="Public notice " + "x" * 4200,
                        category_id=categories[i // 2].id, owner_id=self.users["ta"], state=state,
                        revision=1, review_note="private-review", published_at=datetime(2029, 1, 1))
                    db.add(row)
                    await db.flush()
                    self.notices.append(row.id)
                self.activities = []
                for i, state in enumerate(("published", "draft")):
                    row = Activity(code=self.tag + str(i), title=self.tag + str(i), content="Public activity",
                        owner_id=self.users["ta"], state=state, revision=1, review_note="private-review",
                        published_at=datetime(2029, 1, 1), location="test", start_time=datetime(2035, 1, 2),
                        end_time=datetime(2035, 1, 3), registration_deadline=datetime(2035, 1, 1),
                        capacity=2, enrolled_count=1 if i == 0 else 0)
                    db.add(row)
                    await db.flush()
                    self.activities.append(row.id)
                db.add(ActivityRegistration(activity_id=self.activities[0], user_id=self.users["a"],
                    status="registered", registered_at=datetime(2029, 1, 1)))
                self.previous_index_id = (await db.get(KnowledgeState, 1)).active_index_id
                assert await db.scalar(select(KnowledgeDocument.id).limit(1)) is None, "Refuse unrelated knowledge data"
                await db.commit()
        self.run(action)

    def add_knowledge(self, folder):
        path = folder / "handbook.md"
        path.write_text("# 第一章 奖学金\nScholarship applicants submit complete materials.", encoding="utf-8")
        async def action(database, cache):
            async with database.session_factory() as db:
                version = await knowledge_service.import_document(db, self.knowledge, path,
                    code=self.tag, title="MCP citation handbook", category="regulations")
                self.document_ids.append(version.document_id)
                self.version = version
            self.indexes.append(await knowledge_service.embed_version(
                database, self.knowledge, version.id, embedder=self.embedder))
        self.run(action)
        self.embedder.entered.clear()

    def call(self, tool, args=None, *, user="a"):
        async def action(database, cache):
            return await CampusMCPClient(self.campus, self.private, database, cache).call(
                tool, args or {}, campus_token=self.tokens[user], run_id=str(uuid4()))
        return self.run(action)

    def delegate(self, *, user="a", tools=None):
        async def action(database, cache):
            async with database.session_factory() as db:
                return await issue_delegation(db, cache, self.campus, self.private, self.tokens[user],
                    run_id=str(uuid4()), tools=tools or list(TOOLS))
        return self.run(action)

    def change_user(self, name="a", **values):
        async def action(database, cache):
            async with database.session_factory() as db:
                await db.execute(update(User).where(User.id == self.users[name]).values(**values))
                await db.commit()
        self.run(action)

    def revoke(self, name="a"):
        async def action(database, cache):
            claims = decode_access_token(self.tokens[name], self.campus)
            await cache.set("campus:revoked:" + claims["jti"], "1", ex=300)
        self.run(action)

    def cleanup(self):
        async def action(database, cache):
            async with database.session_factory() as db:
                state = await db.get(KnowledgeState, 1)
                current = await db.get(KnowledgeIndex, state.active_index_id) if state.active_index_id else None
                assert current is None or current.version in self.indexes
                state.active_index_id = self.previous_index_id
                await db.flush()
                versions = select(KnowledgeVersion.id).where(KnowledgeVersion.document_id.in_(self.document_ids))
                for model, condition in (
                    (KnowledgeIndex, KnowledgeIndex.version.in_(self.indexes)),
                    (KnowledgeChunk, KnowledgeChunk.version_id.in_(versions)),
                    (KnowledgePage, KnowledgePage.version_id.in_(versions)),
                    (KnowledgeVersion, KnowledgeVersion.document_id.in_(self.document_ids)),
                    (KnowledgeDocument, KnowledgeDocument.id.in_(self.document_ids)),
                    (ActivityRegistration, ActivityRegistration.activity_id.in_(self.activities)),
                    (Activity, Activity.id.in_(self.activities)), (Notice, Notice.id.in_(self.notices)),
                    (NoticeCategory, NoticeCategory.id.in_(self.category_ids)),
                    (Schedule, Schedule.course_id.in_(self.courses)),
                    (CourseEnrollment, CourseEnrollment.course_id.in_(self.courses)),
                    (Course, Course.id.in_(self.courses)), (User, User.id.in_(list(self.users.values())))):
                    await db.execute(delete(model).where(condition))
                await db.commit()
            for token in self.tokens.values():
                await cache.delete("campus:revoked:" + decode_access_token(token, self.campus)["jti"])
            keys = ["global", "knowledge:global"]
            keys.extend(f"{kind}{user_id}" for user_id in self.users.values()
                        for kind in ("user:", "knowledge:user:"))
            for key in keys:
                await cache.delete("campus:ratelimit:mcp:" + key, "campus:ratelimit:mcp:" + key + ":ts")
        self.run(action)


@pytest.fixture(scope="module", autouse=True)
def initialize():
    assert make_url(load_settings().database_url).database == "my_campus_test"
    subprocess.run([sys.executable, "-B", "-m", "app.initialize"],
                   cwd=Path(__file__).resolve().parents[1], check=True)


@pytest.fixture
def world(tmp_path, request):
    import uvicorn
    value = World(tmp_path)
    value.seed()
    value.add_knowledge(tmp_path)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    value.private = MCPSettings(signing_secret="m2-isolated-delegation-signing-secret-only-2026",
        url=f"http://127.0.0.1:{sock.getsockname()[1]}/mcp",
        knowledge_timeout_s=1 if request.node.name.startswith("test_tool_timeout") else 55)

    def resources():
        return MCPResources(Database(value.campus.database_url), Redis.from_url(value.campus.redis_url,
            decode_responses=True, socket_connect_timeout=3, socket_timeout=3), value.knowledge, value.embedder)

    app = create_app(value.private, resources_factory=resources,
        limits=ToolLimits(user=1) if request.node.name.startswith("test_real_redis_rate_limit") else None)
    value.app = app
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, ws="none"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = clock.monotonic() + 10
        while not server.started and thread.is_alive() and clock.monotonic() < deadline:
            clock.sleep(0.01)
        assert server.started, "Private MCP server did not start"
        with httpx.Client(timeout=5, trust_env=False) as http:
            assert http.get(value.private.url.replace("/mcp", "/ready")).status_code == 200
        yield value
    finally:
        value.embedder.release.set()
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), "Private MCP server did not stop"
        sock.close()
        value.cleanup()


def test_real_http_role_scoped_schedules_and_concurrent_clients(world):
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(world.call, "campus_get_my_schedules", {"date": "2030-01-07"}, user="a")
        second = pool.submit(world.call, "campus_get_my_schedules", {"date": "2030-01-07"}, user="b")
        a, b = first.result(timeout=15), second.result(timeout=15)
    assert a["ok"] and b["ok"], (a, b)
    assert [item["course_id"] for item in a["data"]["items"]] == [world.courses[0]]
    assert [item["course_id"] for item in b["data"]["items"]] == [world.courses[1]]
    teacher = world.call("campus_get_my_schedules", {"date": "2030-01-07"}, user="ta")
    assert [item["course_id"] for item in teacher["data"]["items"]] == [world.courses[0]]
    assert world.call("campus_get_my_schedules", user="admin")["data"]["items"] == []
    assert a["citations"][0]["url"] == "/app/schedule"
    assert "private-" not in json.dumps([a, b, teacher])


def test_published_only_projection_and_own_registration_even_for_admin(world):
    for user in ("a", "admin"):
        notices = world.call("campus_list_notices", {"keyword": world.tag}, user=user)
        assert notices["ok"] and [row["id"] for row in notices["data"]["items"]] == [world.notices[0]]
        assert notices["data"]["items"][0]["truncated"]
        assert len(notices["data"]["items"][0]["content"]) == 600
        for notice_id in world.notices[1:]:
            result = world.call("campus_get_notice", {"notice_id": notice_id}, user=user)
            assert result["reason"] == "not_found" and result["data"] is None
        detail = world.call("campus_get_notice", {"notice_id": world.notices[0]}, user=user)
        assert len(detail["data"]["content"]) == 4000 and detail["data"]["truncated"]
        activities = world.call("campus_list_activities", {"keyword": world.tag}, user=user)
        assert [row["id"] for row in activities["data"]["items"]] == [world.activities[0]]
        assert "can_register" not in activities["data"]["items"][0]
        assert world.call("campus_get_activity", {"activity_id": world.activities[1]}, user=user)["reason"] == "not_found"
        assert "private-" not in json.dumps([notices, detail, activities])
    a = world.call("campus_get_activity", {"activity_id": world.activities[0]})
    b = world.call("campus_get_activity", {"activity_id": world.activities[0]}, user="b")
    assert a["data"]["registration_status"] == "registered" and not a["data"]["can_register"]
    assert b["data"]["registration_status"] is None and b["data"]["can_register"]
    assert "user_id" not in json.dumps([a, b])


def test_real_faiss_citations_match_persisted_original(world):
    result = world.call("campus_search_knowledge", {"query": "Scholarship", "top_k": 1})
    assert result["ok"] and not result["data"]["insufficient"], result
    hit, citation = result["data"]["results"][0], result["citations"][0]
    async def check(database, cache):
        async with database.session_factory() as db:
            chunk = await db.get(KnowledgeChunk, hit["chunk_id"])
            page = await db.get(KnowledgePage, chunk.page_id)
            assert chunk.content == hit["content"] and page.page_number == hit["page_number"]
            assert page.content[chunk.start_offset:chunk.end_offset] == hit["content"]
    world.run(check)
    assert citation["version"] == world.version.version
    assert citation["url"] == f"/api/knowledge/documents/{world.version.document_id}/source?version=1#page=1"
    assert citation["chapter"] == hit["chapter"] and citation["chunk_id"] == hit["chunk_id"]


@pytest.mark.parametrize("change", ["logout", "disabled", "role", "password"])
def test_revalidation_rejects_previously_issued_delegation(world, change):
    delegated = world.delegate()
    if change == "logout":
        world.revoke()
    elif change == "disabled":
        world.change_user(status=0)
    else:
        world.change_user(auth_version=1, **({"role": "teacher"} if change == "role" else {"password": "new-hash"}))
    with httpx.Client(timeout=5, trust_env=False) as http:
        response = http.post(world.private.url, headers={"Authorization": "Bearer " + delegated.token},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401 and "private-" not in response.text
    assert world.call("campus_get_my_schedules")["reason"] == "unauthenticated"


def test_protocol_scope_strict_arguments_and_no_write_tools(world):
    token = world.delegate(tools=["campus_get_my_schedules"])
    headers = {"Authorization": "Bearer " + token.token, "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-11-25"}
    with httpx.Client(timeout=5, trust_env=False) as http:
        listing = http.post(world.private.url, headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
        assert [row["name"] for row in listing] == ["campus_get_my_schedules"]
        for name, args, reason in (("campus_get_my_schedules", {"user_id": world.users["b"]}, "invalid_arguments"),
                ("campus_get_notice", {"notice_id": world.notices[0]}, "forbidden"),
                ("campus_register_activity", {}, "unknown_tool")):
            result = http.post(world.private.url, headers=headers, json={"jsonrpc": "2.0", "id": 2,
                "method": "tools/call", "params": {"name": name, "arguments": args}}).json()["result"]["structuredContent"]
            assert result["reason"] == reason and result["data"] is None
        response = http.post(world.private.url, headers={**headers, "Authorization": "Bearer " + world.tokens["a"]},
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        assert response.status_code == 401


def test_revocation_during_embedding_discards_retrieved_data(world):
    world.embedder.pause = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(world.call, "campus_search_knowledge", {"query": "Scholarship"})
        assert world.embedder.entered.wait(timeout=8)
        world.revoke()
        world.embedder.release.set()
        result = pending.result(timeout=15)
    assert result["reason"] == "unauthenticated" and result["data"] is None and not result["citations"]


def test_real_redis_rate_limit_returns_safe_retryable_result(world):
    assert world.call("campus_get_my_schedules")["ok"]
    result = world.call("campus_get_my_schedules")
    assert result["reason"] == "rate_limited" and result["retryable"] and result["data"] is None


def test_tool_timeout_cancels_embedding_and_next_call_can_recover(world):
    world.embedder.pause = True
    result = world.call("campus_search_knowledge", {"query": "Scholarship"})
    assert result["reason"] == "timeout" and result["data"] is None, result
    assert world.embedder.cancelled
    world.embedder.release.set()
    assert world.call("campus_search_knowledge", {"query": "Scholarship"})["ok"]


def test_embedding_failure_is_sanitized_and_other_tools_remain_available(world, caplog):
    world.embedder.fail = True
    result = world.call("campus_search_knowledge", {"query": "Scholarship"})
    assert result["reason"] == "unavailable" and result["data"] is None
    assert "private-embedding-error" not in json.dumps(result) + caplog.text
    assert world.call("campus_list_notices", {"keyword": world.tag})["ok"]


def test_missing_knowledge_configuration_does_not_break_other_tools(world):
    world.app.state["executor"].resources.knowledge_settings = None
    result = world.call("campus_search_knowledge", {"query": "Scholarship"})
    assert result["reason"] == "unavailable" and result["data"] is None
    assert world.call("campus_get_my_schedules")["ok"]
