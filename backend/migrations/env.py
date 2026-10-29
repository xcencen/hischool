"""Only the isolated campus schema may be migrated; no legacy .env is loaded."""

import asyncio
from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import validate_database_url
from app.database import Base
from app.models.user import User  # noqa: F401 -- explicit autogenerate metadata
from app.models.course import Course  # noqa: F401
from app.models.enrollment import CourseEnrollment  # noqa: F401
from app.models.schedule import Schedule  # noqa: F401
from app.models.notice import Notice, NoticeCategory  # noqa: F401
from app.models.activity import Activity, ActivityRegistration  # noqa: F401
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion, KnowledgePage, KnowledgeChunk, KnowledgeIndex, KnowledgeState  # noqa: F401
from app.models.assistant import Conversation, AssistantRun, AssistantMessage, AssistantUsage, AssistantBudget, AssistantAlert, AssistantControl  # noqa: F401


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def migration_url(*, offline: bool) -> str:
    raw = os.environ.get("CAMPUS_DATABASE_URL")
    if not raw:
        if not offline:
            raise ValueError("CAMPUS_DATABASE_URL is required for online migrations")
        raw = "mysql+asyncmy://offline@localhost/my_campus?charset=utf8mb4"
    return validate_database_url(raw)


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(offline=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(
        migration_url(offline=False),
        poolclass=pool.NullPool,
        connect_args={"charset": "utf8mb4", "init_command": "SET time_zone = '+00:00'"},
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
