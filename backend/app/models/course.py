from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = {"comment": "课程信息"}

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="课程名称")
    code: Mapped[str | None] = mapped_column(
        String(50), unique=True, nullable=True, comment="课程代码"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="简介")
    status: Mapped[int] = mapped_column(default=1, comment="状态：0-停用，1-正常")
