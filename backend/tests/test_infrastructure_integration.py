"""Run only against the dedicated MySQL/Redis Compose test environment."""

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
    reason="Real MySQL/Redis integration requires compose.test.yaml",
)


@pytest.fixture(scope="module", autouse=True)
def migrate_test_database():
    if os.environ.get("CAMPUS_INTEGRATION") != "1":
        return
    from sqlalchemy.engine import make_url
    from app.config import load_settings

    settings = load_settings()
    if make_url(settings.database_url).database != "my_campus_test":
        pytest.fail("Integration tests refuse any database except my_campus_test")
    backend = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, check=True)


def test_real_mysql_seed_repeat_and_admin_changes():
    import bcrypt
    from sqlalchemy import select, text
    from app.config import load_settings
    from app.database import Database
    from app.models.user import User
    from app.seed import ensure_demo_users, load_demo_passwords

    async def check():
        database = Database(load_settings().database_url)
        try:
            async with database.session_factory() as session:
                assert await session.scalar(text("SELECT DATABASE()")) == "my_campus_test"
                async with session.begin_nested():
                    await ensure_demo_users(session, load_demo_passwords())
                await session.commit()
                users = list((await session.scalars(select(User).where(User.username.in_(
                    ["demo_student", "demo_teacher", "demo_admin"]
                )))).all())
                assert {user.role for user in users} == {"student", "teacher", "admin"}
                student = next(user for user in users if user.username == "demo_student")
                assert bcrypt.checkpw(load_demo_passwords()["student"].encode(), student.password.encode())
                original_name = student.name
                original_password = student.password
                original_role = student.role
                changed_password = bcrypt.hashpw(b"integration-changed-password", bcrypt.gensalt()).decode()
                student.name = "管理员修改保留"
                student.role = "teacher"
                student.password = changed_password
                await session.commit()
                try:
                    await ensure_demo_users(session, load_demo_passwords())
                    await session.commit()
                    await session.refresh(student)
                    assert student.name == "管理员修改保留"
                    assert student.password == changed_password
                    assert student.role == "teacher"
                    assert len(list((await session.scalars(select(User).where(User.username == "demo_student"))).all())) == 1
                finally:
                    student.name = original_name
                    student.password = original_password
                    student.role = original_role
                    await session.commit()
        finally:
            await database.dispose()

    asyncio.run(check())


def test_real_mysql_datetime_microseconds_and_role_constraint():
    from datetime import datetime
    from sqlalchemy import delete, select
    from sqlalchemy.exc import IntegrityError
    from app.config import load_settings
    from app.database import Database
    from app.models.user import User

    async def check():
        database = Database(load_settings().database_url)
        name = "test_" + uuid4().hex[:24]
        try:
            async with database.session_factory() as session:
                user = User(username=name, password="integration-only", name="测试", role="student", status=1,
                            create_time=datetime(2026, 1, 1, 0, 0, 0, 123456))
                session.add(user)
                await session.commit()
                await session.refresh(user)
                assert user.create_time.microsecond == 123456
                user.role = "unexpected"
                with pytest.raises(IntegrityError):
                    await session.commit()
                await session.rollback()
                assert await session.scalar(select(User.role).where(User.username == name)) == "student"
                await session.execute(delete(User).where(User.username == name))
                await session.commit()
        finally:
            await database.dispose()

    asyncio.run(check())


def test_real_redis_rq_job_roundtrip():
    from redis import Redis
    from rq import Queue, SimpleWorker
    from app.config import load_settings
    from app.jobs import worker_probe

    connection = Redis.from_url(load_settings().redis_url)
    queue = Queue("infrastructure-test-" + uuid4().hex, connection=connection)
    job = None
    try:
        assert connection.ping()
        job = queue.enqueue(worker_probe, "my-campus", result_ttl=60, failure_ttl=60)
        SimpleWorker([queue], connection=connection).work(burst=True, with_scheduler=False)
        job.refresh()
        assert job.is_finished
        assert job.return_value() == "my-campus"
    finally:
        if job is not None:
            job.delete()
        queue.delete()
        connection.close()


def test_real_campus_http_readiness():
    from app.bootstrap.config import BootstrapSettings
    from app.main import create_app

    with TestClient(create_app(BootstrapSettings(), mode="campus")) as client:
        response = client.get("/api/ready")
        assert response.status_code == 200
        assert response.json()["data"] == {"mysql": True, "redis": True}
        assert client.get("/api/health").status_code == 200
