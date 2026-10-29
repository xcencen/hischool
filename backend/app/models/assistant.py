"""Durable assistant state and Decimal budget ledgers; no startup schema writes."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
                        Integer, JSON, Numeric, String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


UTC_DATETIME = DateTime().with_variant(DATETIME(fsp=6), "mysql")
MONEY = Numeric(18, 8)
TABLE_OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


class Conversation(Base):
    __tablename__ = "assistant_conversations"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_assistant_conversations_public_id"),
        CheckConstraint("state IN ('active', 'archived', 'deleted', 'expired')", name="ck_assistant_conversations_state"),
        CheckConstraint("next_seq >= 1", name="ck_assistant_conversations_sequence"),
        TABLE_OPTIONS,
    )
    public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="active", server_default=text("'active'"), nullable=False)
    next_seq: Mapped[int] = mapped_column(default=1, server_default=text("1"), nullable=False)
    # The active pointer is checked under the control/conversation lock. Avoid a
    # circular conversation -> run -> conversation DDL dependency.
    active_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False, index=True)


class AssistantRun(Base):
    __tablename__ = "assistant_runs"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_assistant_runs_public_id"),
        UniqueConstraint("conversation_id", "request_key", name="uq_assistant_runs_request"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired')", name="ck_assistant_runs_status"),
        CheckConstraint("auth_version >= 0 AND model_calls >= 0 AND tool_calls >= 0", name="ck_assistant_runs_counters"),
        CheckConstraint("cost_limit >= 0 AND reserved >= 0 AND spent >= 0", name="ck_assistant_runs_money"),
        TABLE_OPTIONS,
    )
    public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("assistant_conversations.id"), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("assistant_runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default=text("'queued'"), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_jti: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_exp: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    auth_version: Mapped[int] = mapped_column(default=0, server_default=text("0"), nullable=False)
    available_at: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"), nullable=False)
    model_calls: Mapped[int] = mapped_column(default=0, server_default=text("0"), nullable=False)
    tool_calls: Mapped[int] = mapped_column(default=0, server_default=text("0"), nullable=False)
    cost_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reserved: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0), server_default=text("0"), nullable=False)
    spent: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0), server_default=text("0"), nullable=False)
    budget_day: Mapped[date] = mapped_column(Date, nullable=False)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_assistant_messages_sequence"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_assistant_messages_role"),
        CheckConstraint("sequence >= 1", name="ck_assistant_messages_sequence"),
        TABLE_OPTIONS,
    )
    conversation_id: Mapped[int] = mapped_column(ForeignKey("assistant_conversations.id"), nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("assistant_runs.id"), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class AssistantUsage(Base):
    __tablename__ = "assistant_usage"
    __table_args__ = (
        UniqueConstraint("run_id", "call_key", name="uq_assistant_usage_call"),
        CheckConstraint("kind IN ('model', 'embedding', 'tool')", name="ck_assistant_usage_kind"),
        CheckConstraint("state IN ('reserved', 'settled', 'unknown', 'released')", name="ck_assistant_usage_state"),
        CheckConstraint("reserved >= 0 AND charged >= 0 AND latency_ms >= 0 AND attempt >= 1", name="ck_assistant_usage_values"),
        CheckConstraint("(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0) AND (cache_read_tokens IS NULL OR cache_read_tokens >= 0)", name="ck_assistant_usage_tokens"),
        TABLE_OPTIONS,
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("assistant_runs.id"), nullable=False, index=True)
    call_key: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="reserved", server_default=text("'reserved'"), nullable=False)
    reserved: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    charged: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0), server_default=text("0"), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    latency_ms: Mapped[int] = mapped_column(default=0, server_default=text("0"), nullable=False)
    attempt: Mapped[int] = mapped_column(default=1, server_default=text("1"), nullable=False)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    usage_unknown: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"), nullable=False)


class AssistantBudget(Base):
    __tablename__ = "assistant_budgets"
    __table_args__ = (
        UniqueConstraint("day", "scope", "scope_id", name="uq_assistant_budgets_period"),
        CheckConstraint("scope IN ('global', 'user')", name="ck_assistant_budgets_scope"),
        CheckConstraint("(scope = 'global' AND scope_id = 0) OR (scope = 'user' AND scope_id > 0)", name="ck_assistant_budgets_owner"),
        CheckConstraint("cap >= 0 AND spent >= 0 AND reserved >= 0", name="ck_assistant_budgets_money"),
        TABLE_OPTIONS,
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cap: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    spent: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0), server_default=text("0"), nullable=False)
    reserved: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0), server_default=text("0"), nullable=False)


class AssistantAlert(Base):
    __tablename__ = "assistant_alerts"
    __table_args__ = (
        UniqueConstraint("day", "scope", "scope_id", "kind", name="uq_assistant_alerts_kind"),
        CheckConstraint("scope IN ('global', 'user', 'run')", name="ck_assistant_alerts_scope"),
        CheckConstraint("kind IN ('threshold', 'limit', 'overrun', 'unknown_usage')", name="ck_assistant_alerts_kind"),
        CheckConstraint("amount >= 0 AND cap >= 0", name="ck_assistant_alerts_money"),
        TABLE_OPTIONS,
    )
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cap: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class AssistantControl(Base):
    __tablename__ = "assistant_control"
    __table_args__ = (CheckConstraint("id = 1", name="ck_assistant_control_singleton"), TABLE_OPTIONS)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False,
                                    nullable=False, comment="主键ID", sort_order=-1)
