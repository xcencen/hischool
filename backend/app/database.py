"""Async database primitives without a global engine or import-time connection."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import DateTime, MetaData
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import validate_database_url


def utc_now() -> datetime:
    """MySQL DATETIME values are naive UTC; presentation converts to Shanghai."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="主键ID", sort_order=-1
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        default=utc_now,
        nullable=False,
        comment="创建时间（UTC）",
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="更新时间（UTC）",
    )


class Database:
    """Construct at application startup; connections are opened only on demand."""

    def __init__(self, database_url: str) -> None:
        validate_database_url(database_url)
        self.engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"charset": "utf8mb4", "init_command": "SET time_zone = '+00:00'"},
        )
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.session_factory() as session:
        yield session
