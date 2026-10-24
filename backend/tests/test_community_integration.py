"""Community workflows only against the isolated MySQL/Redis test stack."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_INTEGRATION") != "1", reason="Requires isolated MySQL/Redis")
PASSWORD = "Community-test-2026"


@pytest.fixture(scope="module")
def client():
    from sqlalchemy.engine import make_url
    from app.bootstrap.config import BootstrapSettings
    from app.config import load_settings
    from app.main import create_app
    assert make_url(load_settings().database_url).database == "my_campus_test"
    subprocess.run([sys.executable, "-m", "app.initialize"], cwd=Path(__file__).resolve().parents[1], check=True)
    with TestClient(create_app(BootstrapSettings(), mode="campus")) as http:
        yield http


@pytest.fixture(scope="module")
def admin(client):
    result = client.post("/api/auth/login", json={"username": "demo_admin", "password": os.environ["CAMPUS_DEMO_ADMIN_PASSWORD"]})
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json()["data"]["token"]}


class World:
    def __init__(self, client, admin):
        self.client, self.admin = client, admin
        self.names, self.codes, self.category_ids = [], [], []
        self.people = {}

    def person(self, role, suffix=""):
        key = role + suffix
        if key not in self.people:
            name = "community_" + uuid4().hex[:24]
            self.names.append(name)
            result = self.client.post("/api/admin/users", headers=self.admin,
                json=dict(username=name, password=PASSWORD, name="社区测试用户", role=role, status=1))
            assert result.status_code == 200, result.text
            value = result.json()["data"]
            login = self.client.post("/api/auth/login", json=dict(username=name, password=PASSWORD))
            assert login.status_code == 200
            self.people[key] = (value, {"Authorization": "Bearer " + login.json()["data"]["token"]})
        return self.people[key]

    def category(self):
        result = self.client.post("/api/admin/notice-categories", headers=self.admin,
            json=dict(code="CAT-"+uuid4().hex[:20], name="分类"+uuid4().hex[:12]))
        assert result.status_code == 200
        value = result.json()["data"]
        self.category_ids.append(value["id"])
        return value

    def content(self, kind, *, headers=None, owned=False, **changes):
        code = "COMM-"+uuid4().hex[:20]
        self.codes.append(code)
        data = dict(code=code, title="社区测试内容", content="测试正文", state="published" if not owned else "pending")
        if kind == "notices":
            data["category_id"] = self.category()["id"]
        else:
            data.update(location="测试活动室", start_time="2030-01-07T14:00:00+08:00",
                        end_time="2030-01-07T16:00:00+08:00",
                        registration_deadline="2030-01-06T14:00:00+08:00", capacity=2)
        data.update(changes)
        result = self.client.post(f"/api/{'owned' if owned else 'admin'}/{kind}", headers=headers or self.admin, json=data)
        assert result.status_code == 200, result.text
        return result.json()["data"]


@pytest.fixture
def world(client, admin):
    value = World(client, admin)
    yield value
    from sqlalchemy import delete, select
    from app.config import load_settings
    from app.database import Database
    from app.models.activity import Activity, ActivityRegistration
    from app.models.notice import Notice, NoticeCategory
    from app.models.user import User
    async def clean():
        db = Database(load_settings().database_url)
        try:
            async with db.session_factory() as session:
                ids = list((await session.scalars(select(Activity.id).where(Activity.code.in_(value.codes)))).all())
                await session.execute(delete(ActivityRegistration).where(ActivityRegistration.activity_id.in_(ids)))
                await session.execute(delete(Activity).where(Activity.code.in_(value.codes)))
                await session.execute(delete(Notice).where(Notice.code.in_(value.codes)))
                await session.execute(delete(NoticeCategory).where(NoticeCategory.id.in_(value.category_ids)))
                await session.execute(delete(User).where(User.username.in_(value.names)))
                await session.commit()
        finally:
            await db.dispose()
    asyncio.run(clean())


@pytest.mark.parametrize("kind", ["notices", "activities"])
def test_teacher_review_and_edits_require_reapproval_and_old_revision_is_rejected(world, kind):
    _, teacher = world.person("teacher")
    _, student = world.person("student")
    value = world.content(kind, headers=teacher, owned=True)
    path = f"/api/{kind}/{value['id']}"
    assert world.client.get(path, headers=student).status_code == 404
    approved = world.client.post(f"/api/admin/{kind}/{value['id']}/review", headers=world.admin,
        json=dict(expected_revision=value["revision"], action="publish"))
    assert approved.status_code == 200
    public = world.client.get(path, headers=student)
    assert public.status_code == 200
    assert "review_note" not in public.json()["data"]
    assert "owner_id" not in public.json()["data"]
    old_revision = approved.json()["data"]["revision"]
    edited = world.client.patch(f"/api/owned/{kind}/{value['id']}", headers=teacher, json=dict(title="修改后需重审"))
    assert edited.status_code == 200
    assert edited.json()["data"]["state"] == "pending"
    assert world.client.get(path, headers=student).status_code == 404
    stale = world.client.post(f"/api/admin/{kind}/{value['id']}/review", headers=world.admin,
        json=dict(expected_revision=old_revision, action="publish"))
    assert stale.status_code == 409
    rejected = world.client.post(f"/api/admin/{kind}/{value['id']}/review", headers=world.admin,
        json=dict(expected_revision=edited.json()["data"]["revision"], action="reject", note="请补充说明"))
    assert rejected.status_code == 200 and rejected.json()["data"]["state"] == "rejected"
    assert world.client.get(f"/api/owned/{kind}", headers=teacher).json()["data"]["list"][0]["review_note"] == "请补充说明"


@pytest.mark.parametrize("kind", ["notices", "activities"])
def test_staff_ownership_and_student_management_denials(world, kind):
    _, first = world.person("teacher")
    _, second = world.person("teacher", "second")
    _, student = world.person("student")
    value = world.content(kind, headers=first, owned=True)
    path = f"/api/owned/{kind}/{value['id']}"
    assert world.client.patch(path, headers=second, json=dict(title="禁止")).status_code == 403
    assert world.client.delete(path, headers=second).status_code == 403
    assert world.client.get(path, headers=second).status_code == 404
    assert world.client.get(f"/api/owned/{kind}", headers=second).json()["data"]["list"] == []
    assert world.client.get(f"/api/admin/{kind}", headers=first).status_code == 403
    assert world.client.get(f"/api/owned/{kind}", headers=student).status_code == 403
    denied = world.client.patch(path, headers=first, json=dict(state="published"))
    assert denied.status_code == 403
    assert world.client.patch(path, headers=student, json=dict(title="禁止")).status_code == 403


def test_notice_search_category_lifecycle_and_unpublished_filter(world):
    _, student = world.person("student")
    published = world.content("notices", title="可检索通知")
    draft = world.content("notices", state="draft", title="不得公开的草稿")
    result = world.client.get("/api/notices", headers=student, params=dict(q="可检索", category_id=published["category_id"]))
    assert result.status_code == 200
    assert [row["id"] for row in result.json()["data"]["list"]] == [published["id"]]
    assert world.client.get(f"/api/notices/{draft['id']}", headers=student).status_code == 404
    category_id = published["category_id"]
    assert world.client.delete(f"/api/admin/notice-categories/{category_id}", headers=world.admin).status_code == 409
    assert world.client.patch(f"/api/admin/notice-categories/{category_id}", headers=world.admin, json=dict(status=0)).status_code == 200
    assert world.client.get(f"/api/notices/{published['id']}", headers=student).status_code == 404
    assert category_id not in {row["id"] for row in world.client.get("/api/notice-categories", headers=student).json()["data"]}
    empty = world.category()
    assert world.client.delete(f"/api/admin/notice-categories/{empty['id']}", headers=world.admin).status_code == 200


def register(world, item_id, headers):
    return world.client.post(f"/api/activities/{item_id}/registrations", headers=headers)


def cancel(world, item_id, headers):
    return world.client.post(f"/api/activities/{item_id}/registrations/cancel", headers=headers)


def test_signup_cancel_retry_and_reregister_preserve_one_record_and_own_history(world):
    activity = world.content("activities")
    _, first = world.person("student")
    _, second = world.person("student", "second")
    one = register(world, activity["id"], first)
    assert one.status_code == 200
    repeated = register(world, activity["id"], first)
    assert repeated.status_code == 200 and repeated.json()["data"]["id"] == one.json()["data"]["id"]
    assert world.client.get(f"/api/activities/{activity['id']}", headers=first).json()["data"]["enrolled_count"] == 1
    assert world.client.get("/api/user/me/registrations", headers=second).json()["data"]["total"] == 0
    assert cancel(world, activity["id"], second).status_code == 404
    for _ in range(2):
        assert cancel(world, activity["id"], first).status_code == 200
    assert world.client.get(f"/api/activities/{activity['id']}", headers=first).json()["data"]["enrolled_count"] == 0
    record = world.client.get("/api/user/me/registrations", headers=first).json()["data"]["list"][0]
    assert record["status"] == "cancelled" and record["cancelled_at"].endswith("Z")
    again = register(world, activity["id"], first)
    assert again.status_code == 200 and again.json()["data"]["id"] == one.json()["data"]["id"]
    assert again.json()["data"]["cancelled_at"] is None
    assert world.client.delete(f"/api/admin/activities/{activity['id']}", headers=world.admin).status_code == 409


def test_parallel_last_seat_and_duplicate_signup_never_overbook(world):
    activity = world.content("activities", capacity=1)
    people = [world.person("student", str(index))[1] for index in range(2)]
    ready = Barrier(2)
    def send(headers):
        ready.wait(timeout=10)
        return register(world, activity["id"], headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, people))
    assert sorted(result.status_code for result in results) == [200, 409]
    winner = people[next(index for index, result in enumerate(results) if result.status_code == 200)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicates = list(pool.map(lambda _: register(world, activity["id"], winner), range(2)))
    assert all(result.status_code == 200 for result in duplicates)
    assert len({result.json()["data"]["id"] for result in duplicates}) == 1
    detail = world.client.get(f"/api/activities/{activity['id']}", headers=winner).json()["data"]
    assert detail["enrolled_count"] == 1 and detail["can_register"] is False


def test_deadline_start_boundary_and_capacity_updates(world, monkeypatch):
    from app.services import activity_service
    activity = world.content("activities", capacity=2)
    _, first = world.person("student")
    _, second = world.person("student", "second")
    assert register(world, activity["id"], first).status_code == 200
    assert register(world, activity["id"], second).status_code == 200
    response = world.client.patch(f"/api/admin/activities/{activity['id']}", headers=world.admin, json=dict(capacity=1))
    assert response.status_code == 409
    assert world.client.patch(f"/api/admin/activities/{activity['id']}", headers=world.admin, json=dict(end_time="2030-01-07T05:00:00Z")).status_code == 422
    monkeypatch.setattr(activity_service, "utc_now", lambda: datetime(2030, 1, 7, 6))
    assert cancel(world, activity["id"], first).status_code == 409
    # A successful registration retry remains idempotent beyond the deadline.
    assert register(world, activity["id"], first).status_code == 200
    assert cancel(world, activity["id"], world.person("student", "third")[1]).status_code == 404


def test_unpublished_activity_cannot_signup_but_owner_can_cancel_and_drafts_are_hidden(world):
    _, student = world.person("student")
    activity = world.content("activities")
    assert register(world, activity["id"], student).status_code == 200
    assert world.client.patch(f"/api/admin/activities/{activity['id']}", headers=world.admin, json=dict(state="draft", title="私有草稿标题")).status_code == 200
    _, other = world.person("student", "other")
    assert register(world, activity["id"], other).status_code == 404
    own = world.client.get("/api/user/me/registrations", headers=student).json()["data"]["list"][0]
    assert own["activity_title"] == "活动暂未发布" and own["can_cancel"]
    assert cancel(world, activity["id"], student).status_code == 200


def test_new_signup_at_exact_deadline_is_rejected(world, monkeypatch):
    from app.services import activity_service
    activity = world.content("activities")
    _, student = world.person("student")
    monkeypatch.setattr(activity_service, "utc_now", lambda: datetime(2030, 1, 6, 6))
    assert register(world, activity["id"], student).status_code == 409


def test_revoked_teacher_identity_cannot_save_content(world):
    from sqlalchemy import select
    from app.common.exceptions import BusinessException
    from app.config import load_settings
    from app.database import Database
    from app.models.user import User
    from app.schemas.community import NoticeUpdate
    from app.services import notice_service

    teacher, headers = world.person("teacher")
    item = world.content("notices", headers=headers, owned=True)
    async def check():
        database = Database(load_settings().database_url)
        try:
            async with database.session_factory() as session:
                actor = await session.scalar(select(User).where(User.id == teacher["id"]))
                # Another real transaction revokes the identity after its initial read.
                async with database.session_factory() as other:
                    current = await other.get(User, teacher["id"])
                    current.role = "student"
                    current.auth_version += 1
                    await other.commit()
                with pytest.raises(BusinessException) as error:
                    await notice_service.update(session, item["id"], NoticeUpdate(title="禁止写入"), actor, own_only=True)
                assert error.value.code == 401
                await session.rollback()
        finally:
            await database.dispose()
    asyncio.run(check())
    actual = world.client.get(f"/api/admin/notices/{item['id']}", headers=world.admin).json()["data"]
    assert actual["title"] == item["title"]


def test_seed_preserves_admin_changes_and_counts(client):
    from sqlalchemy import select
    from app.config import load_settings
    from app.database import Database
    from app.demo_community import ensure_demo_community
    from app.models.activity import Activity
    from app.models.notice import Notice
    async def check():
        db = Database(load_settings().database_url)
        try:
            async with db.session_factory() as session:
                activity = await session.scalar(select(Activity).where(Activity.code == "DEMO-READING"))
                notice = await session.scalar(select(Notice).where(Notice.code == "DEMO-WELCOME"))
                old_title, old_capacity, old_notice = activity.title, activity.capacity, notice.title
                activity.title, activity.capacity, notice.title = "保留活动", 41, "保留通知"
                await session.commit()
                try:
                    await ensure_demo_community(session)
                    await session.commit()
                    await session.refresh(activity)
                    await session.refresh(notice)
                    assert (activity.title, activity.capacity, notice.title) == ("保留活动", 41, "保留通知")
                finally:
                    activity.title, activity.capacity, notice.title = old_title, old_capacity, old_notice
                    await session.commit()
        finally:
            await db.dispose()
    asyncio.run(check())
