"""Add campus notices, moderated activities and durable registrations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "0004_community"
down_revision = "0003_course_comments"
branch_labels = None
depends_on = None


def base_columns(table):
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("create_time", DATETIME(fsp=6), nullable=False, comment="创建时间（UTC）"),
        sa.Column("update_time", DATETIME(fsp=6), nullable=False, comment="更新时间（UTC）"),
        sa.PrimaryKeyConstraint("id", name="pk_" + table),
    ]


def publication_columns(table):
    return [
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.Column("published_at", DATETIME(fsp=6), nullable=True),
        sa.UniqueConstraint("code", name="uq_" + table + "_code"),
        sa.CheckConstraint("state IN ('draft', 'pending', 'published', 'rejected')", name="ck_" + table + "_state"),
        sa.CheckConstraint("revision >= 1", name="ck_" + table + "_revision"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_" + table + "_owner_id_users"),
    ]


def upgrade():
    op.create_table("notice_categories", *base_columns("notice_categories"),
        sa.Column("code", sa.String(50), nullable=False), sa.Column("name", sa.String(50), nullable=False),
        sa.Column("status", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.UniqueConstraint("code", name="uq_notice_categories_code"),
        sa.UniqueConstraint("name", name="uq_notice_categories_name"),
        sa.CheckConstraint("status IN (0, 1)", name="ck_notice_categories_status"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_table("notices", *base_columns("notices"), *publication_columns("notices"),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["notice_categories.id"], name="fk_notices_category_id_notice_categories"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_notices_owner_id", "notices", ["owner_id"])
    op.create_index("ix_notices_category_id", "notices", ["category_id"])
    op.create_table("activities", *base_columns("activities"), *publication_columns("activities"),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("start_time", DATETIME(fsp=6), nullable=False),
        sa.Column("end_time", DATETIME(fsp=6), nullable=False),
        sa.Column("registration_deadline", DATETIME(fsp=6), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("enrolled_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("capacity > 0 AND enrolled_count >= 0 AND enrolled_count <= capacity", name="ck_activities_capacity"),
        sa.CheckConstraint("end_time > start_time AND registration_deadline <= start_time", name="ck_activities_times"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_activities_owner_id", "activities", ["owner_id"])
    op.create_table("activity_registrations", *base_columns("activity_registrations"),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("registered_at", DATETIME(fsp=6), nullable=False),
        sa.Column("cancelled_at", DATETIME(fsp=6), nullable=True),
        sa.UniqueConstraint("activity_id", "user_id", name="uq_activity_registrations_user"),
        sa.CheckConstraint("status IN ('registered', 'cancelled')", name="ck_activity_registrations_status"),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], name="fk_activity_registrations_activity_id_activities"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_activity_registrations_user_id_users"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_activity_registrations_user_id", "activity_registrations", ["user_id"])


def downgrade():
    # Explicit destructive operator action only; normal code rollback retains data.
    for table in ("activity_registrations", "activities", "notices", "notice_categories"):
        op.drop_table(table)
