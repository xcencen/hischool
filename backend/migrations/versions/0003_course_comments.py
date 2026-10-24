"""Align column comments with ORM metadata, preserving all course data.

0002 was already applied during verification, so it remains immutable.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_course_comments"
down_revision = "0002_courses"
branch_labels = None
depends_on = None

COLUMNS = (
    ("courses", "id", sa.Integer(), False, "主键ID"),
    ("course_enrollments", "id", sa.Integer(), False, "主键ID"),
    ("schedules", "id", sa.Integer(), False, "主键ID"),
    ("courses", "name", sa.String(100), False, "课程名称"),
    ("courses", "code", sa.String(50), False, "课程代码"),
    ("courses", "description", sa.Text(), True, "简介"),
    ("schedules", "period", sa.String(50), False, "节次"),
    ("schedules", "course_id", sa.Integer(), False, "课程 ID"),
    ("schedules", "location", sa.String(100), False, "地点"),
)


def apply_comments(remove=False):
    for table, column, sql_type, nullable, comment in COLUMNS:
        options = {"autoincrement": True} if column == "id" else {}
        op.alter_column(table, column, existing_type=sql_type, existing_nullable=nullable,
                        comment=None if remove else comment, **options)


def upgrade():
    apply_comments()


def downgrade():
    apply_comments(remove=True)
