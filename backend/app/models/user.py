from sqlalchemy import CheckConstraint, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("role IN ('student', 'teacher', 'admin')", name="ck_users_role"),
        CheckConstraint("status IN (0, 1)", name="ck_users_status"),
        CheckConstraint("auth_version >= 0", name="ck_users_auth_version"),
        {"comment": "用户信息表", "mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    username: Mapped[str] = mapped_column(
        String(50), comment="账号", nullable=False
    )
    password: Mapped[str] = mapped_column(String(255), comment="密码哈希", nullable=False)
    name: Mapped[str] = mapped_column(String(50), comment="名称", nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), comment="角色：student-学生，teacher-教师，admin-管理员", nullable=False
    )
    email: Mapped[str | None] = mapped_column(String(50), comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(50), comment="手机号")
    avatar: Mapped[str | None] = mapped_column(String(50), comment="头像")
    status: Mapped[int] = mapped_column(
        default=1, server_default=text("1"), comment="状态：0-禁用，1-正常"
    )
    auth_version: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), comment="凭证版本，权限或密码变更时递增"
    )
