from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.publication import PublicationColumns, PUBLICATION_STATES


class NoticeCategory(Base):
    __tablename__ = "notice_categories"
    __table_args__ = (
        UniqueConstraint("code", name="uq_notice_categories_code"),
        UniqueConstraint("name", name="uq_notice_categories_name"),
        CheckConstraint("status IN (0, 1)", name="ck_notice_categories_status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[int] = mapped_column(default=1, server_default=text("1"), nullable=False)


class Notice(PublicationColumns, Base):
    __tablename__ = "notices"
    __table_args__ = (
        UniqueConstraint("code", name="uq_notices_code"),
        CheckConstraint(PUBLICATION_STATES, name="ck_notices_state"),
        CheckConstraint("revision >= 1", name="ck_notices_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("notice_categories.id"), nullable=False, index=True)
