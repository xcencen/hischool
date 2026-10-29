"""Add durable assistant conversations, runs and conservative budget accounting."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "0006_assistant"
down_revision = "0005_knowledge"
branch_labels = None
depends_on = None


def column(name, kind, *, nullable=False, default=None):
    return sa.Column(name, kind, nullable=nullable,
                     server_default=sa.text(default) if default is not None else None)


def foreign(table, field, target):
    return sa.ForeignKeyConstraint([field], [target + ".id"], name="fk_" + table + "_" + field + "_" + target)


def table(name, *items):
    op.create_table(name,
        sa.Column("id", sa.Integer(), autoincrement=name != "assistant_control", nullable=False, comment="主键ID"),
        sa.Column("create_time", DATETIME(fsp=6), nullable=False, comment="创建时间（UTC）"),
        sa.Column("update_time", DATETIME(fsp=6), nullable=False, comment="更新时间（UTC）"),
        sa.PrimaryKeyConstraint("id", name="pk_" + name), *items,
        mysql_engine="InnoDB", mysql_charset="utf8mb4")


def index(table_name, field):
    op.create_index("ix_" + table_name + "_" + field, table_name, [field])


def money(name, *, default=None):
    return column(name, sa.Numeric(18, 8), default=default)


def upgrade():
    table("assistant_conversations",
        column("public_id", sa.String(36)), column("owner_id", sa.Integer()), column("title", sa.String(100)),
        column("state", sa.String(20), default="'active'"), column("next_seq", sa.Integer(), default="1"),
        column("active_run_id", sa.String(36), nullable=True), column("expires_at", DATETIME(fsp=6)),
        sa.UniqueConstraint("public_id", name="uq_assistant_conversations_public_id"),
        sa.CheckConstraint("state IN ('active', 'archived', 'deleted', 'expired')", name="ck_assistant_conversations_state"),
        sa.CheckConstraint("next_seq >= 1", name="ck_assistant_conversations_sequence"),
        foreign("assistant_conversations", "owner_id", "users"))
    index("assistant_conversations", "owner_id")
    index("assistant_conversations", "expires_at")
    table("assistant_runs",
        column("public_id", sa.String(36)), column("conversation_id", sa.Integer()), column("owner_id", sa.Integer()),
        column("request_key", sa.String(64, collation="utf8mb4_bin")), column("request_hash", sa.String(64)),
        column("parent_id", sa.Integer(), nullable=True), column("status", sa.String(20), default="'queued'"),
        column("reason", sa.String(40), nullable=True), column("source_jti", sa.String(128), nullable=True),
        column("source_exp", sa.BigInteger(), nullable=True), column("auth_version", sa.Integer(), default="0"),
        column("available_at", DATETIME(fsp=6)), column("deadline_at", DATETIME(fsp=6)),
        column("started_at", DATETIME(fsp=6), nullable=True), column("finished_at", DATETIME(fsp=6), nullable=True),
        column("lease_token", sa.String(32), nullable=True), column("lease_until", DATETIME(fsp=6), nullable=True),
        column("cancel_requested", sa.Boolean(), default="0"), column("model_calls", sa.Integer(), default="0"),
        column("tool_calls", sa.Integer(), default="0"), money("cost_limit"), money("reserved", default="0"),
        money("spent", default="0"), column("budget_day", sa.Date()),
        sa.UniqueConstraint("public_id", name="uq_assistant_runs_public_id"),
        sa.UniqueConstraint("conversation_id", "request_key", name="uq_assistant_runs_request"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired')", name="ck_assistant_runs_status"),
        sa.CheckConstraint("auth_version >= 0 AND model_calls >= 0 AND tool_calls >= 0", name="ck_assistant_runs_counters"),
        sa.CheckConstraint("cost_limit >= 0 AND reserved >= 0 AND spent >= 0", name="ck_assistant_runs_money"),
        foreign("assistant_runs", "conversation_id", "assistant_conversations"),
        foreign("assistant_runs", "owner_id", "users"), foreign("assistant_runs", "parent_id", "assistant_runs"))
    for field in ("conversation_id", "owner_id", "status", "lease_until"):
        index("assistant_runs", field)
    table("assistant_messages",
        column("conversation_id", sa.Integer()), column("run_id", sa.Integer(), nullable=True),
        column("sequence", sa.Integer()), column("role", sa.String(20)), column("content", sa.Text(), nullable=True),
        column("citations", sa.JSON()),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_assistant_messages_sequence"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_assistant_messages_role"),
        sa.CheckConstraint("sequence >= 1", name="ck_assistant_messages_sequence"),
        foreign("assistant_messages", "conversation_id", "assistant_conversations"),
        foreign("assistant_messages", "run_id", "assistant_runs"))
    index("assistant_messages", "conversation_id")
    index("assistant_messages", "run_id")
    table("assistant_usage",
        column("run_id", sa.Integer()), column("call_key", sa.String(64, collation="utf8mb4_bin")),
        column("kind", sa.String(20)), column("state", sa.String(20), default="'reserved'"),
        money("reserved"), money("charged", default="0"),
        column("input_tokens", sa.Integer(), nullable=True), column("output_tokens", sa.Integer(), nullable=True),
        column("cache_read_tokens", sa.Integer(), nullable=True), column("price_version", sa.String(100), nullable=True),
        column("price_snapshot", sa.JSON()), column("latency_ms", sa.Integer(), default="0"),
        column("attempt", sa.Integer(), default="1"), column("resource", sa.String(100)),
        column("usage_unknown", sa.Boolean(), default="0"),
        sa.UniqueConstraint("run_id", "call_key", name="uq_assistant_usage_call"),
        sa.CheckConstraint("kind IN ('model', 'embedding', 'tool')", name="ck_assistant_usage_kind"),
        sa.CheckConstraint("state IN ('reserved', 'settled', 'unknown', 'released')", name="ck_assistant_usage_state"),
        sa.CheckConstraint("reserved >= 0 AND charged >= 0 AND latency_ms >= 0 AND attempt >= 1", name="ck_assistant_usage_values"),
        sa.CheckConstraint("(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0) AND (cache_read_tokens IS NULL OR cache_read_tokens >= 0)", name="ck_assistant_usage_tokens"),
        foreign("assistant_usage", "run_id", "assistant_runs"))
    index("assistant_usage", "run_id")
    table("assistant_budgets",
        column("day", sa.Date()), column("scope", sa.String(20)), column("scope_id", sa.Integer()),
        money("cap"), money("spent", default="0"), money("reserved", default="0"),
        sa.UniqueConstraint("day", "scope", "scope_id", name="uq_assistant_budgets_period"),
        sa.CheckConstraint("scope IN ('global', 'user')", name="ck_assistant_budgets_scope"),
        sa.CheckConstraint("(scope = 'global' AND scope_id = 0) OR (scope = 'user' AND scope_id > 0)", name="ck_assistant_budgets_owner"),
        sa.CheckConstraint("cap >= 0 AND spent >= 0 AND reserved >= 0", name="ck_assistant_budgets_money"))
    table("assistant_alerts",
        column("owner_id", sa.Integer(), nullable=True), column("day", sa.Date()), column("scope", sa.String(20)),
        column("scope_id", sa.Integer()), column("kind", sa.String(20)), column("acknowledged", sa.Boolean(), default="0"),
        money("amount"), money("cap"),
        sa.UniqueConstraint("day", "scope", "scope_id", "kind", name="uq_assistant_alerts_kind"),
        sa.CheckConstraint("scope IN ('global', 'user', 'run')", name="ck_assistant_alerts_scope"),
        sa.CheckConstraint("kind IN ('threshold', 'limit', 'overrun', 'unknown_usage')", name="ck_assistant_alerts_kind"),
        sa.CheckConstraint("amount >= 0 AND cap >= 0", name="ck_assistant_alerts_money"),
        foreign("assistant_alerts", "owner_id", "users"))
    index("assistant_alerts", "owner_id")
    table("assistant_control", sa.CheckConstraint("id = 1", name="ck_assistant_control_singleton"))
    # Infrastructure singleton, not demo or user content. Never recreates existing
    # business rows; code startup itself does not perform this initialization.
    op.execute(sa.text("INSERT INTO assistant_control (id, create_time, update_time) VALUES (1, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))"))


def downgrade():
    # Explicit operator action only. Normal application rollback retains records.
    for name in ("assistant_control", "assistant_alerts", "assistant_budgets", "assistant_usage",
                 "assistant_messages", "assistant_runs", "assistant_conversations"):
        op.drop_table(name)
