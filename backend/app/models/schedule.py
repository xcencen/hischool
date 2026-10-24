from datetime import date, time

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("course_id", "class_date", "start_time", name="uq_schedules_lesson"),
        CheckConstraint("end_time > start_time", name="ck_schedules_interval"),
        {"comment": "课程课时（北京时间）", "mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    class_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    period: Mapped[str] = mapped_column(String(50), comment="节次", nullable=False)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"), comment="课程 ID", nullable=False, index=True
    )
    location: Mapped[str] = mapped_column(String(100), comment="地点", nullable=False)
