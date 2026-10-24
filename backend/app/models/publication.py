"""Common columns for moderated campus content; no import-time I/O."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

UTC_DATETIME = DateTime().with_variant(DATETIME(fsp=6), "mysql")
PUBLICATION_STATES = "state IN ('draft', 'pending', 'published', 'rejected')"


class PublicationColumns:
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    revision: Mapped[int] = mapped_column(default=1, server_default=text("1"), nullable=False)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTC_DATETIME, nullable=True)
