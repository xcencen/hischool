from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.publication import PublicationColumns, PUBLICATION_STATES, UTC_DATETIME


class Activity(PublicationColumns, Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("code", name="uq_activities_code"),
        CheckConstraint(PUBLICATION_STATES, name="ck_activities_state"),
        CheckConstraint("revision >= 1", name="ck_activities_revision"),
        CheckConstraint("capacity > 0 AND enrolled_count >= 0 AND enrolled_count <= capacity", name="ck_activities_capacity"),
        CheckConstraint("end_time > start_time AND registration_deadline <= start_time", name="ck_activities_times"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    location: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    end_time: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    registration_deadline: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    enrolled_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)


class ActivityRegistration(Base):
    __tablename__ = "activity_registrations"
    __table_args__ = (
        UniqueConstraint("activity_id", "user_id", name="uq_activity_registrations_user"),
        CheckConstraint("status IN ('registered', 'cancelled')", name="ck_activity_registrations_status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True)
