"""Add course-level lessons and student enrollments, without seeding data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "0002_courses"
down_revision = "0001_users"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("create_time", DATETIME(fsp=6), nullable=False, comment="创建时间（UTC）"),
        sa.Column("update_time", DATETIME(fsp=6), nullable=False, comment="更新时间（UTC）"),
    ]


def upgrade():
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("code", name="uq_courses_code"),
        sa.CheckConstraint("status IN (0, 1)", name="ck_courses_status"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], name="fk_courses_teacher_id_users"),
        comment="校园课程", mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_courses_teacher_id", "courses", ["teacher_id"])
    op.create_table(
        "course_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("course_id", "user_id", name="uq_course_enrollments_student"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name="fk_course_enrollments_course_id_courses"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_course_enrollments_user_id_users"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_course_enrollments_user_id", "course_enrollments", ["user_id"])
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("class_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("period", sa.String(50), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("course_id", "class_date", "start_time", name="uq_schedules_lesson"),
        sa.CheckConstraint("end_time > start_time", name="ck_schedules_interval"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name="fk_schedules_course_id_courses"),
        comment="课程课时（北京时间）", mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_schedules_class_date", "schedules", ["class_date"])
    op.create_index("ix_schedules_course_id", "schedules", ["course_id"])


def downgrade():
    # Explicit destructive operator action only; ordinary code rollback retains data.
    op.drop_table("schedules")
    op.drop_table("course_enrollments")
    op.drop_table("courses")
