"""Create the campus users table, without inserting demonstration data.

Revision ID: 0001_users
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME


revision = "0001_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("username", sa.String(50), nullable=False, comment="账号"),
        sa.Column("password", sa.String(255), nullable=False, comment="密码哈希"),
        sa.Column("name", sa.String(50), nullable=False, comment="名称"),
        sa.Column(
            "role", sa.String(50), nullable=False,
            comment="角色：student-学生，teacher-教师，admin-管理员",
        ),
        sa.Column("email", sa.String(50), nullable=True, comment="邮箱"),
        sa.Column("phone", sa.String(50), nullable=True, comment="手机号"),
        sa.Column("avatar", sa.String(50), nullable=True, comment="头像"),
        sa.Column("status", sa.Integer(), server_default=sa.text("1"), nullable=False,
                  comment="状态：0-禁用，1-正常"),
        sa.Column("auth_version", sa.Integer(), server_default=sa.text("0"), nullable=False,
                  comment="凭证版本，权限或密码变更时递增"),
        sa.Column("create_time", DATETIME(fsp=6), nullable=False, comment="创建时间（UTC）"),
        sa.Column("update_time", DATETIME(fsp=6), nullable=False, comment="更新时间（UTC）"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint("role IN ('student', 'teacher', 'admin')", name="ck_users_role"),
        sa.CheckConstraint("status IN (0, 1)", name="ck_users_status"),
        sa.CheckConstraint("auth_version >= 0", name="ck_users_auth_version"),
        comment="用户信息表",
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    # Explicit operator action only: removes the table created by this revision.
    # Production recovery should restore a backup or apply a forward repair.
    op.drop_table("users")
