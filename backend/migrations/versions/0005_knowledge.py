"""Create versioned knowledge, page citations, saved vectors and index pointer."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMTEXT

revision = "0005_knowledge"
down_revision = "0004_community"
branch_labels = None
depends_on = None


def common(table):
    return [
        sa.Column("id", sa.Integer(), autoincrement=table != "knowledge_state", nullable=False, comment="主键ID"),
        sa.Column("create_time", DATETIME(fsp=6), nullable=False, comment="创建时间（UTC）"),
        sa.Column("update_time", DATETIME(fsp=6), nullable=False, comment="更新时间（UTC）"),
        sa.PrimaryKeyConstraint("id", name="pk_" + table),
    ]


def column(name, kind, *, nullable=False, default=None):
    return sa.Column(name, kind, nullable=nullable, server_default=sa.text(default) if default is not None else None)


def foreign(table, field, target):
    return sa.ForeignKeyConstraint([field], [target+".id"], name="fk_"+table+"_"+field+"_"+target)


def table(name, *items):
    op.create_table(name, *common(name), *items, mysql_engine="InnoDB", mysql_charset="utf8mb4")


def upgrade():
    table("knowledge_documents",
        column("code", sa.String(50)), column("title", sa.String(150)), column("category", sa.String(20)),
        column("active", sa.Integer(), default="1"), column("latest_version", sa.Integer(), default="0"),
        column("active_version", sa.Integer(), nullable=True),
        sa.UniqueConstraint("code", name="uq_knowledge_documents_code"),
        sa.CheckConstraint("active IN (0, 1)", name="ck_knowledge_documents_active"),
        sa.CheckConstraint("category IN ('faq', 'regulations', 'guide')", name="ck_knowledge_documents_category"))
    table("knowledge_versions",
        column("document_id", sa.Integer()), column("version", sa.Integer()), column("title", sa.String(150)),
        column("source_sha256", sa.String(64)), column("source_key", sa.String(80)),
        column("original_name", sa.String(255)), column("source_type", sa.String(20)),
        column("page_count", sa.Integer()), column("chunk_count", sa.Integer()), column("warnings", sa.JSON()),
        column("status", sa.String(20)), column("job_id", sa.String(64), nullable=True),
        column("error", sa.String(255), nullable=True),
        sa.UniqueConstraint("document_id", "version", name="uq_knowledge_versions_number"),
        sa.UniqueConstraint("document_id", "source_sha256", name="uq_knowledge_versions_source"),
        sa.CheckConstraint("status IN ('parsed', 'queued', 'processing', 'embedded', 'indexed', 'failed')", name="ck_knowledge_versions_status"),
        foreign("knowledge_versions", "document_id", "knowledge_documents"))
    table("knowledge_pages",
        column("version_id", sa.Integer()), column("page_number", sa.Integer()),
        column("page_label", sa.String(40), nullable=True), column("content", MEDIUMTEXT()),
        column("needs_ocr", sa.Integer()),
        sa.UniqueConstraint("version_id", "page_number", name="uq_knowledge_pages_number"),
        foreign("knowledge_pages", "version_id", "knowledge_versions"))
    table("knowledge_chunks",
        column("version_id", sa.Integer()), column("page_id", sa.Integer()), column("ordinal", sa.Integer()),
        column("chapter", sa.String(500)), column("content", sa.Text()),
        column("start_offset", sa.Integer()), column("end_offset", sa.Integer()),
        column("vector", sa.LargeBinary(), nullable=True),
        column("embedding_model", sa.String(50), nullable=True),
        column("embedding_dimension", sa.Integer(), nullable=True),
        column("provider_hash", sa.String(64), nullable=True),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_knowledge_chunks_ordinal"),
        sa.CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_knowledge_chunks_offsets"),
        foreign("knowledge_chunks", "version_id", "knowledge_versions"),
        foreign("knowledge_chunks", "page_id", "knowledge_pages"))
    op.create_index("ix_knowledge_chunks_version_id", "knowledge_chunks", ["version_id"])
    table("knowledge_indexes",
        column("version", sa.String(32)), column("file_key", sa.String(50)), column("sha256", sa.String(64)),
        column("model", sa.String(50)), column("dimensions", sa.Integer()), column("provider_hash", sa.String(64)),
        column("vector_count", sa.Integer()), column("version_ids", sa.JSON()),
        sa.UniqueConstraint("version", name="uq_knowledge_indexes_version"))
    table("knowledge_state", column("active_index_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_knowledge_state_singleton"),
        foreign("knowledge_state", "active_index_id", "knowledge_indexes"))


def downgrade():
    # Operator action only. Code rollback retains knowledge data and source files.
    for name in ("knowledge_state", "knowledge_indexes", "knowledge_chunks", "knowledge_pages",
                 "knowledge_versions", "knowledge_documents"):
        op.drop_table(name)

