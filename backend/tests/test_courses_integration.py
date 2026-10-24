"""Timetable business flows against the isolated real MySQL/Redis stack."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CAMPUS_INTEGRATION") != "1",
    reason="Course integration requires the dedicated MySQL/Redis Compose stack",
)

PASSWORD = "CourseIntegration-2026"
DAY = "2030-01-07"


@pytest.fixture(scope="module")
def client():
    from sqlalchemy.engine import make_url
    from app.bootstrap.config import BootstrapSettings
    from app.config import load_settings
    from app.main import create_app

    if make_url(load_settings().database_url).database != "my_campus_test":
        pytest.fail("Course tests refuse any database other than my_campus_test")
    subprocess.run([sys.executable, "-m", "app.initialize"],
                   cwd=Path(__file__).resolve().parents[1], check=True)
    with TestClient(create_app(BootstrapSettings(), mode="campus")) as http:
        yield http


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_applied_schema_matches_migrated_metadata(client):
    result = subprocess.run([sys.executable, "-m", "alembic", "check"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def admin_headers(client):
    response = client.post("/api/auth/login", json={
        "username": "demo_admin", "password": os.environ["CAMPUS_DEMO_ADMIN_PASSWORD"],
    })
    assert response.status_code == 200
    return bearer(response.json()["data"]["token"])


class CourseWorld:
    def __init__(self, http, admin):
        self.client = http
        self.admin = admin
        self.names = []
        self.codes = []
        self.users = {}
        self.headers = {}

    def user(self, role, key=None):
        identity = key or role
        if identity not in self.users:
            name = "course_" + uuid4().hex[:24]
            self.names.append(name)
            response = self.client.post("/api/admin/users", headers=self.admin, json={
                "username": name, "password": PASSWORD, "name": "课表测试用户",
                "role": role, "status": 1,
            })
            assert response.status_code == 200
            self.users[identity] = response.json()["data"]
        return self.users[identity]

    def auth(self, role, key=None):
        identity = key or role
        if identity not in self.headers:
            user = self.user(role, key)
            response = self.client.post("/api/auth/login", json={"username": user["username"], "password": PASSWORD})
            assert response.status_code == 200
            self.headers[identity] = bearer(response.json()["data"]["token"])
        return self.headers[identity]

    def course(self, teacher=None, **changes):
        teacher = teacher or self.user("teacher")
        code = "TEST-" + uuid4().hex[:20]
        self.codes.append(code)
        payload = {"code": code, "name": "课表集成课程", "teacher_id": teacher["id"],
                   "description": "真实数据库验证", "status": 1, **changes}
        response = self.client.post("/api/admin/courses", headers=self.admin, json=payload)
        assert response.status_code == 200
        return response.json()["data"]

    def schedule_payload(self, course, **changes):
        return {"course_id": course["id"], "class_date": DAY,
                "start_time": "08:00:00", "end_time": "09:30:00", "period": "1-2",
                "location": "测试教室-" + uuid4().hex[:12], **changes}

    def schedule(self, course, **changes):
        payload = self.schedule_payload(course, **changes)
        response = self.client.post("/api/admin/schedules", headers=self.admin, json=payload)
        assert response.status_code == 200
        return response.json()["data"]

    def enroll(self, course, *students):
        response = self.client.put(f"/api/admin/courses/{course['id']}/students", headers=self.admin,
                                   json={"student_ids": [student["id"] for student in students]})
        assert response.status_code == 200
        return response.json()["data"]


@pytest.fixture
def world(client, admin_headers):
    from sqlalchemy import delete, select
    from app.config import load_settings
    from app.database import Database
    from app.models.course import Course
    from app.models.enrollment import CourseEnrollment
    from app.models.schedule import Schedule
    from app.models.user import User

    value = CourseWorld(client, admin_headers)
    try:
        yield value
    finally:
        async def cleanup():
            database = Database(load_settings().database_url)
            try:
                async with database.session_factory() as session:
                    course_ids = list((await session.scalars(select(Course.id).where(Course.code.in_(value.codes)))).all())
                    if course_ids:
                        await session.execute(delete(Schedule).where(Schedule.course_id.in_(course_ids)))
                        await session.execute(delete(CourseEnrollment).where(CourseEnrollment.course_id.in_(course_ids)))
                        await session.execute(delete(Course).where(Course.id.in_(course_ids)))
                    if value.names:
                        await session.execute(delete(User).where(User.username.in_(value.names)))
                    await session.commit()
            finally:
                await database.dispose()
        asyncio.run(cleanup())


def test_student_and_teacher_timetables_are_scoped_to_the_caller(world):
    first = world.course()
    other_teacher = world.user("teacher", "other_teacher")
    second = world.course(other_teacher)
    first_class = world.schedule(first)
    second_class = world.schedule(second)
    first_student = world.user("student")
    second_student = world.user("student", "other_student")
    world.enroll(first, first_student)
    world.enroll(second, second_student)
    headers = world.auth("student")
    today = world.client.get("/api/schedules/today", headers=headers, params={"date": DAY})
    assert today.status_code == 200
    assert {row["id"] for row in today.json()["data"]} == {first_class["id"]}
    injected = world.client.get("/api/schedules/today", headers=headers,
                                params={"date": DAY, "user_id": second_student["id"]})
    assert injected.status_code in {200, 422}
    if injected.status_code == 200:
        assert {row["id"] for row in injected.json()["data"]} == {first_class["id"]}
    week = world.client.get("/api/schedules/week", headers=headers, params={"date": "2030-01-13"})
    assert week.status_code == 200
    assert week.json()["data"]["start_date"] == DAY
    assert week.json()["data"]["end_date"] == "2030-01-13"
    assert {row["id"] for row in week.json()["data"]["list"]} == {first_class["id"]}
    teacher = world.client.get("/api/schedules/week", headers=world.auth("teacher"), params={"date": DAY})
    assert teacher.status_code == 200
    assert {row["id"] for row in teacher.json()["data"]["list"]} == {first_class["id"]}
    assert second_class["id"] not in {row["id"] for row in teacher.json()["data"]["list"]}


def test_course_details_do_not_disclose_enrolled_students(world):
    course = world.course()
    student = world.user("student")
    world.enroll(course, student)
    response = world.client.get(f"/api/courses/{course['id']}", headers=world.auth("student"))
    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["teacher_id"] == course["teacher_id"]
    assert detail["code"] == course["code"]
    assert "student_ids" not in detail and "students" not in detail
    assert student["username"] not in response.text


@pytest.mark.parametrize("role", ["student", "teacher"])
def test_only_admin_can_manage_courses_enrollments_and_schedules(world, role):
    course = world.course()
    headers = world.auth(role)
    denied_code = "DENIED-" + uuid4().hex[:12]
    world.codes.append(denied_code)
    assert world.client.post("/api/admin/courses", headers=headers, json={
        "name": "拒绝越权", "code": denied_code, "teacher_id": course["teacher_id"],
    }).status_code == 403
    assert world.client.patch(f"/api/admin/courses/{course['id']}", headers=headers,
                              json={"name": "拒绝越权"}).status_code == 403
    assert world.client.put(f"/api/admin/courses/{course['id']}/students", headers=headers,
                            json={"student_ids": []}).status_code == 403
    assert world.client.post("/api/admin/schedules", headers=headers,
                             json=world.schedule_payload(course)).status_code == 403
    assert world.client.get("/api/admin/courses/options", headers=headers).status_code == 403


def test_admin_course_edit_duplicate_code_and_valid_teacher(world):
    course = world.course()
    changed = world.client.patch(f"/api/admin/courses/{course['id']}", headers=world.admin,
                                json={"name": "管理员编辑课程", "description": "更新后的简介"})
    assert changed.status_code == 200
    assert changed.json()["data"]["name"] == "管理员编辑课程"
    duplicate = world.client.post("/api/admin/courses", headers=world.admin, json={
        "name": "重复课程", "code": course["code"], "teacher_id": course["teacher_id"],
    })
    assert duplicate.status_code == 409
    invalid_code = "INVALID-" + uuid4().hex[:10]
    world.codes.append(invalid_code)
    invalid = world.client.post("/api/admin/courses", headers=world.admin, json={
        "name": "错误授课人", "code": invalid_code, "teacher_id": world.user("student")["id"],
    })
    assert invalid.status_code in {400, 422}
    listed = world.client.get("/api/admin/courses", headers=world.admin).json()["data"]
    assert sum(row["code"] == course["code"] for row in listed) == 1


def test_admin_replaces_student_enrollments_and_rejects_teacher_ids(world):
    course = world.course()
    first = world.user("student")
    second = world.user("student", "other_student")
    world.enroll(course, first)
    replaced = world.enroll(course, second)
    assert {row["id"] for row in replaced} == {second["id"]}
    rejected = world.client.put(f"/api/admin/courses/{course['id']}/students", headers=world.admin,
                               json={"student_ids": [course["teacher_id"]]})
    assert rejected.status_code in {400, 422}
    current = world.client.get(f"/api/admin/courses/{course['id']}/students", headers=world.admin)
    assert {row["id"] for row in current.json()["data"]} == {second["id"]}
    options = world.client.get("/api/admin/courses/options", headers=world.admin).json()["data"]
    assert course["teacher_id"] in {row["id"] for row in options["teachers"]}
    assert second["id"] in {row["id"] for row in options["students"]}


def test_teacher_overlap_is_rejected_and_adjacent_classes_are_allowed(world):
    first = world.course()
    second = world.course()
    original = world.schedule(first, location="教师冲突-"+uuid4().hex[:10])
    conflict = world.client.post("/api/admin/schedules", headers=world.admin,
        json=world.schedule_payload(second, start_time="09:00:00", end_time="10:00:00"))
    assert conflict.status_code == 409
    adjacent = world.schedule(second, start_time="09:30:00", end_time="10:30:00", period="3-4")
    rows = world.client.get("/api/admin/schedules", headers=world.admin,
                            params={"date": DAY}).json()["data"]
    assert {row["id"] for row in rows if row["course_id"] in {first["id"], second["id"]}} == {original["id"], adjacent["id"]}


def test_room_overlap_is_rejected_for_different_teachers(world):
    first = world.course()
    second = world.course(world.user("teacher", "other_teacher"))
    room = "共用教室-"+uuid4().hex[:10]
    original = world.schedule(first, location=room)
    conflict = world.client.post("/api/admin/schedules", headers=world.admin,
        json=world.schedule_payload(second, location=room, start_time="08:30:00", end_time="10:00:00"))
    assert conflict.status_code == 409
    rows = world.client.get("/api/admin/schedules", headers=world.admin,
                            params={"course_id": second["id"]}).json()["data"]
    assert rows == []
    assert original["location"] == room


def test_parallel_conflicting_schedules_only_commit_one_lesson(world):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    first, second = world.course(), world.course()
    payloads = [world.schedule_payload(course) for course in (first, second)]
    ready = Barrier(2)

    def send(payload):
        ready.wait(timeout=10)
        return world.client.post("/api/admin/schedules", headers=world.admin, json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, payloads))
    assert sorted(response.status_code for response in responses) == [200, 409]
    rows = world.client.get("/api/admin/schedules", headers=world.admin,
                            params={"date": DAY}).json()["data"]
    assert len([row for row in rows if row["course_id"] in {first["id"], second["id"]}]) == 1


def test_changing_teacher_revalidates_existing_lesson_conflicts(world):
    first = world.course()
    second = world.course(world.user("teacher", "other_teacher"))
    world.schedule(first)
    world.schedule(second)
    rejected = world.client.patch(f"/api/admin/courses/{second['id']}", headers=world.admin,
                                  json={"teacher_id": first["teacher_id"]})
    assert rejected.status_code == 409
    detail = world.client.get(f"/api/courses/{second['id']}", headers=world.auth("student"))
    assert detail.json()["data"]["teacher_id"] == second["teacher_id"]


def test_invalid_time_rejected_and_schedule_crud_preserves_course_delete_guard(world):
    course = world.course()
    invalid = world.client.post("/api/admin/schedules", headers=world.admin,
        json=world.schedule_payload(course, start_time="10:00:00", end_time="09:00:00"))
    assert invalid.status_code == 422
    schedule = world.schedule(course)
    changed = world.client.patch(f"/api/admin/schedules/{schedule['id']}", headers=world.admin,
                                 json={"location": "管理员修改教室"})
    assert changed.status_code == 200
    assert changed.json()["data"]["location"] == "管理员修改教室"
    invalid_patch = world.client.patch(f"/api/admin/schedules/{schedule['id']}", headers=world.admin,
                                       json={"start_time": "10:00:00"})
    assert invalid_patch.status_code == 422
    guarded = world.client.delete(f"/api/admin/courses/{course['id']}", headers=world.admin)
    assert guarded.status_code == 409
    assert world.client.delete(f"/api/admin/schedules/{schedule['id']}", headers=world.admin).status_code == 200
    assert world.client.delete(f"/api/admin/courses/{course['id']}", headers=world.admin).status_code == 200
    assert world.client.get(f"/api/courses/{course['id']}", headers=world.auth("student")).status_code == 404


def test_disabled_course_is_hidden_from_public_details_and_personal_timetable(world):
    course = world.course()
    student = world.user("student")
    world.enroll(course, student)
    schedule = world.schedule(course)
    assert world.client.patch(f"/api/admin/courses/{course['id']}", headers=world.admin,
                               json={"status": 0}).status_code == 200
    headers = world.auth("student")
    assert world.client.get(f"/api/courses/{course['id']}", headers=headers).status_code == 404
    courses = world.client.get("/api/courses", headers=headers).json()["data"]
    assert course["id"] not in {row["id"] for row in courses}
    timetable = world.client.get("/api/schedules/today", headers=headers, params={"date": DAY}).json()["data"]
    assert schedule["id"] not in {row["id"] for row in timetable}


def test_repeated_demo_seed_preserves_admin_course_and_room_changes(client):
    from sqlalchemy import select
    from app.config import load_settings
    from app.database import Database
    from app.demo_courses import ensure_demo_courses
    from app.models.course import Course
    from app.models.schedule import Schedule

    async def check():
        database = Database(load_settings().database_url)
        try:
            async with database.session_factory() as session:
                course = await session.scalar(select(Course).where(Course.code == "DEMO-CS101"))
                assert course is not None
                schedule = await session.scalar(select(Schedule).where(Schedule.course_id == course.id).order_by(Schedule.id))
                assert schedule is not None
                original_name, original_room = course.name, schedule.location
                reference = schedule.class_date
                course.name = "管理员已修改种子课名"
                schedule.location = "管理员已修改种子教室"
                await session.commit()
                try:
                    await ensure_demo_courses(session, today=reference)
                    await session.commit()
                    assert await session.scalar(select(Course.name).where(Course.id == course.id)) == "管理员已修改种子课名"
                    assert await session.scalar(select(Schedule.location).where(Schedule.id == schedule.id)) == "管理员已修改种子教室"
                finally:
                    course.name = original_name
                    schedule.location = original_room
                    await session.commit()
        finally:
            await database.dispose()

    asyncio.run(check())
