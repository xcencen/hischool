from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

LONG_TEXT = Text().with_variant(MEDIUMTEXT(), "mysql")
VERSION_STATES = "status IN ('parsed', 'queued', 'processing', 'embedded', 'indexed', 'failed')"


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("code", name="uq_knowledge_documents_code"),
        CheckConstraint("active IN (0, 1)", name="ck_knowledge_documents_active"),
        CheckConstraint("category IN ('faq', 'regulations', 'guide')", name="ck_knowledge_documents_category"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    active_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_knowledge_versions_number"),
        UniqueConstraint("document_id", "source_sha256", name="uq_knowledge_versions_source"),
        CheckConstraint(VERSION_STATES, name="ck_knowledge_versions_status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="parsed", nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)


class KnowledgePage(Base):
    __tablename__ = "knowledge_pages"
    __table_args__ = (
        UniqueConstraint("version_id", "page_number", name="uq_knowledge_pages_number"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    needs_ocr: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_knowledge_chunks_ordinal"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_knowledge_chunks_offsets"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"), nullable=False, index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("knowledge_pages.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class KnowledgeIndex(Base):
    __tablename__ = "knowledge_indexes"
    __table_args__ = (
        UniqueConstraint("version", name="uq_knowledge_indexes_version"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    file_key: Mapped[str] = mapped_column(String(50), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_count: Mapped[int] = mapped_column(Integer, nullable=False)
    version_ids: Mapped[list] = mapped_column(JSON, nullable=False)


class KnowledgeState(Base):
    __tablename__ = "knowledge_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_knowledge_state_singleton"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False,
                                    nullable=False, comment="主键ID", sort_order=-1)
    active_index_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_indexes.id"), nullable=True)
