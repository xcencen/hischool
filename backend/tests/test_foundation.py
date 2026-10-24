"""Validate the new foundation without contacting MySQL, Redis, or the old DB."""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from types import SimpleNamespace

import bcrypt
import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.config import Settings, load_settings, validate_database_url
from app.database import Base, Database, utc_now
from app.models.user import User
from app.seed import ensure_demo_users


BACKEND_DIR = Path(__file__).resolve().parents[1]
DATABASE_URL = "mysql+asyncmy://campus:test-password@127.0.0.1:13306/my_campus?charset=utf8mb4"
DEMO_PASSWORDS = {
    "admin": "Demo-admin-test-2026",
    "teacher": "Demo-teacher-test-2026",
    "student": "Demo-student-test-2026",
}


def campus_environment() -> dict[str, str]:
    return {
        "CAMPUS_DATABASE_URL": DATABASE_URL,
        "CAMPUS_REDIS_URL": "redis://127.0.0.1:16379/0",
        "CAMPUS_JWT_SECRET": "test-secret-only-" * 3,
    }


@pytest.mark.parametrize("database", ["my_campus", "my_campus_test"])
def test_settings_allow_only_explicit_campus_databases(database: str) -> None:
    environment = campus_environment()
    environment["CAMPUS_DATABASE_URL"] = DATABASE_URL.replace("/my_campus?", f"/{database}?")
    environment["DATABASE_URL"] = "mysql+pymysql://legacy:unused@localhost/old_database"
    environment["JWT_SECRET_KEY"] = "unused-legacy-secret"
    settings = load_settings(environment)
    assert settings.database_url == environment["CAMPUS_DATABASE_URL"]
    assert settings.redis_url == environment["CAMPUS_REDIS_URL"]
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_hours == 24


def test_legacy_environment_cannot_select_database() -> None:
    with pytest.raises(ValueError):
        load_settings({"DATABASE_URL": DATABASE_URL, "JWT_SECRET_KEY": "legacy"})


def test_settings_repr_does_not_expose_credentials() -> None:
    environment = campus_environment()
    printable = repr(load_settings(environment))
    assert "test-password" not in printable
    assert environment["CAMPUS_JWT_SECRET"] not in printable


@pytest.mark.parametrize(
    "url",
    [
        "mysql+pymysql://campus:test-password@localhost/my_campus",
        "mysql://campus:test-password@localhost/my_campus",
        "postgresql+asyncpg://campus:test-password@localhost/my_campus",
        "sqlite+aiosqlite:///:memory:",
        "mysql+asyncmy://campus:test-password@localhost/old_database",
        "mysql+asyncmy://campus:test-password@localhost/my_campus_backup",
        "mysql+asyncmy://campus:test-password@localhost/",
        "mysql+asyncmy://campus:test-password@localhost/my_campus?db=old_database",
        "mysql+asyncmy://campus:test-password@localhost/my_campus?init_command=USE+old_database",
        "mysql+asyncmy://campus:test-password@localhost/my_campus?charset=latin1",
    ],
)
def test_database_configuration_rejects_sync_or_unapproved_targets(url: str) -> None:
    with pytest.raises(ValueError) as error:
        validate_database_url(url)
    assert "test-password" not in str(error.value)
    with pytest.raises(ValueError):
        Settings(database_url=url, redis_url="redis://localhost:16379/0", jwt_secret="a" * 48)


@pytest.mark.parametrize("secret", ["", "short", "a" * 31])
def test_campus_requires_nontrivial_jwt_secret(secret: str) -> None:
    environment = campus_environment()
    environment["CAMPUS_JWT_SECRET"] = secret
    with pytest.raises(ValueError):
        load_settings(environment)


@pytest.mark.parametrize("redis_url", ["http://localhost:16379", "redis:///0", "invalid"])
def test_campus_rejects_invalid_redis_urls(redis_url: str) -> None:
    environment = campus_environment()
    environment["CAMPUS_REDIS_URL"] = redis_url
    with pytest.raises(ValueError):
        load_settings(environment)


@pytest.mark.parametrize("hours", ["0", "169", "-1", "not-an-integer"])
def test_campus_bounds_token_expiration(hours: str) -> None:
    environment = campus_environment()
    environment["CAMPUS_JWT_EXPIRE_HOURS"] = hours
    with pytest.raises(ValueError):
        load_settings(environment)


def test_database_factory_and_session_are_lazy(monkeypatch) -> None:
    def forbid_connection(*args, **kwargs):
        raise AssertionError("Creating the database/session opened a network connection")

    async def check() -> None:
        # Windows creates the event loop's own socketpair before entering this
        # coroutine. Block connections only while exercising the DB factory.
        with monkeypatch.context() as network_guard:
            network_guard.setattr(socket, "create_connection", forbid_connection)
            network_guard.setattr(socket.socket, "connect", forbid_connection)
            network_guard.setattr(socket.socket, "connect_ex", forbid_connection)
            database = Database(DATABASE_URL)
            try:
                assert database.engine.dialect.name == "mysql"
                assert database.engine.dialect.driver == "asyncmy"
                async with database.session_factory() as session:
                    assert not session.in_transaction()
                    assert session.sync_session.expire_on_commit is False
            finally:
                await database.dispose()

    asyncio.run(check())


def test_enabled_metadata_preserves_user_microsecond_timestamps() -> None:
    from app.models.course import Course  # noqa: F401
    from app.models.enrollment import CourseEnrollment  # noqa: F401
    from app.models.schedule import Schedule  # noqa: F401

    assert set(Base.metadata.tables) == {"users", "courses", "course_enrollments", "schedules"}
    dialect = mysql.dialect()
    for field in ("create_time", "update_time"):
        timestamp = User.__table__.c[field].type.dialect_impl(dialect)
        assert isinstance(timestamp, mysql.DATETIME)
        assert timestamp.fsp == 6
    ddl = str(CreateTable(User.__table__).compile(dialect=dialect))
    for role in ("student", "teacher", "admin"):
        assert f"'{role}'" in ddl
    assert "uq_users_username" in ddl
    assert "ck_users_role" in ddl


def test_timestamp_default_uses_naive_utc() -> None:
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    actual = utc_now()
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert actual.tzinfo is None
    assert before <= actual <= after


class SeedSession:
    """Only the public async session operations needed by the seed service."""

    def __init__(self, usernames=()):
        self.usernames = list(usernames)
        self.statements = []
        self.flush_count = 0

    async def scalars(self, statement):
        return SimpleNamespace(all=lambda: list(self.usernames))

    async def execute(self, statement):
        self.statements.append(statement)

    async def flush(self):
        self.flush_count += 1


def test_seed_creates_three_hashed_role_accounts_without_committing() -> None:
    session = SeedSession()
    created = asyncio.run(ensure_demo_users(session, DEMO_PASSWORDS))
    assert set(created) == {"demo_student", "demo_teacher", "demo_admin"}
    assert session.statements
    parameters = [
        statement.compile(dialect=mysql.dialect()).params
        for statement in session.statements
    ]
    values = [value for item in parameters for value in item.values()]
    for password in DEMO_PASSWORDS.values():
        assert password not in values
    for username in created:
        assert username in values
    for item in parameters:
        assert bcrypt.checkpw(DEMO_PASSWORDS[item["role"]].encode(), item["password"].encode())


def test_seed_preserves_existing_accounts_and_handles_insert_races() -> None:
    existing = SeedSession(("demo_admin", "demo_teacher", "demo_student"))
    assert asyncio.run(ensure_demo_users(existing, DEMO_PASSWORDS)) == []
    # Existing password/role/name edits must not be sent back as UPDATE fields.
    missing = SeedSession()
    asyncio.run(ensure_demo_users(missing, DEMO_PASSWORDS))
    for statement in [*existing.statements, *missing.statements]:
        sql = str(statement.compile(dialect=mysql.dialect()))
        assert "ON DUPLICATE KEY UPDATE" in sql
        assignments = sql.split("ON DUPLICATE KEY UPDATE", 1)[1].lower()
        assert "password" not in assignments
        assert "role" not in assignments
        assert "name" not in assignments
        assert "status" not in assignments


@pytest.mark.parametrize("password", ["short", "a" * 73, "密" * 25])
def test_seed_rejects_invalid_passwords_before_writing(password: str) -> None:
    session = SeedSession()
    passwords = {**DEMO_PASSWORDS, "student": password}
    with pytest.raises(ValueError):
        asyncio.run(ensure_demo_users(session, passwords))
    assert session.statements == []


def offline_migration(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    child_environment = os.environ.copy()
    for key in tuple(child_environment):
        if key.startswith(("CAMPUS_", "DATABASE_", "JWT_")):
            child_environment.pop(key)
    child_environment.update(environment)
    child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR,
        env=child_environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_offline_migration_needs_no_credentials_or_service() -> None:
    result = offline_migration({"DATABASE_URL": "mysql+pymysql://legacy:unused@localhost/old_database"})
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == {
        "alembic_version", "users", "courses", "course_enrollments", "schedules"
    }
    assert "DATETIME(6)" in sql
    assert "utf8mb4" in sql
    assert "InnoDB" in sql
    assert "0001_users" in sql
    assert "DROP TABLE" not in sql
    assert "demo_" not in sql
    assert "old_database" not in sql


def test_offline_migration_rejects_old_database_before_generating_ddl() -> None:
    result = offline_migration({"CAMPUS_DATABASE_URL": "mysql+asyncmy://legacy:hidden-secret@localhost/old_database"})
    assert result.returncode != 0
    assert "CREATE TABLE" not in result.stdout
    assert "hidden-secret" not in result.stderr


def test_initializer_runs_migration_then_real_seed_module(monkeypatch) -> None:
    from app import config, initialize

    calls = []
    monkeypatch.setattr(config, "load_settings", lambda: calls.append("validated"))

    def run(command, *, cwd, check):
        assert Path(cwd) == BACKEND_DIR
        assert check is True
        calls.append(command)

    monkeypatch.setattr(initialize.subprocess, "run", run)
    initialize.main()
    assert calls[0] == "validated"
    assert calls[1][0:3] == [sys.executable, "-m", "alembic"]
    assert calls[1][-2:] == ["upgrade", "head"]
    assert calls[2] == [sys.executable, "-m", "app.seed"]


def test_initializer_does_not_seed_after_failed_migration(monkeypatch) -> None:
    from app import config, initialize

    calls = []
    monkeypatch.setattr(config, "load_settings", lambda: None)

    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(initialize.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        initialize.main()
    assert len(calls) == 1
