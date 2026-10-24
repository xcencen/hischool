from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("code", name="uq_courses_code"),
        CheckConstraint("status IN (0, 1)", name="ck_courses_status"),
        {"comment": "校园课程", "mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="课程名称")
    code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="课程代码"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="简介")
    status: Mapped[int] = mapped_column(default=1, server_default=text("1"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
