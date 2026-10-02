"""Phase 3: Production Knowledge and RAG Foundation

Revision ID: 0003_knowledge_and_rag
Revises: 0002_auth_and_rbac
Create Date: 2026-10-02 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from app.database.base import GUID

revision: str = "0003_knowledge_and_rag"
down_revision: Union[str, None] = "0002_auth_and_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Enable pgvector extension on PostgreSQL
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Create knowledge_bases table
    op.create_table(
        "knowledge_bases",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),
    )
    op.create_index(op.f("ix_knowledge_bases_id"), "knowledge_bases", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_bases_tenant_id"), "knowledge_bases", ["tenant_id"], unique=False)
    op.create_index(
        "ix_knowledge_bases_tenant_status",
        "knowledge_bases",
        ["tenant_id", "status"],
        unique=False,
    )

    # 3. Create documents table
    op.create_table(
        "documents",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("knowledge_base_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="upload"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("current_version_id", GUID(), nullable=True),
        sa.Column("created_by", GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_id"), "documents", ["id"], unique=False)
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_documents_knowledge_base_id"), "documents", ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)
    op.create_index("ix_documents_tenant_kb", "documents", ["tenant_id", "knowledge_base_id"], unique=False)
    op.create_index("ix_documents_tenant_status", "documents", ["tenant_id", "status"], unique=False)

    # 4. Create document_versions table
    op.create_table(
        "document_versions",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("document_id", GUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_reference", sa.String(length=500), nullable=True),
        sa.Column("extracted_text_hash", sa.String(length=64), nullable=True),
        sa.Column("processing_status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
    )
    op.create_index(op.f("ix_document_versions_id"), "document_versions", ["id"], unique=False)
    op.create_index(op.f("ix_document_versions_tenant_id"), "document_versions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False)
    op.create_index(
        "ix_document_versions_tenant_doc",
        "document_versions",
        ["tenant_id", "document_id"],
        unique=False,
    )

    # 5. Create document_chunks table
    op.create_table(
        "document_chunks",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("knowledge_base_id", GUID(), nullable=False),
        sa.Column("document_id", GUID(), nullable=False),
        sa.Column("document_version_id", GUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("chunk_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id", "chunk_index", name="uq_chunk_version_index"),
    )
    op.create_index(op.f("ix_document_chunks_id"), "document_chunks", ["id"], unique=False)
    op.create_index(op.f("ix_document_chunks_tenant_id"), "document_chunks", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_knowledge_base_id"), "document_chunks", ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_document_version_id"), "document_chunks", ["document_version_id"], unique=False)
    op.create_index("ix_document_chunks_tenant_kb", "document_chunks", ["tenant_id", "knowledge_base_id"], unique=False)
    op.create_index("ix_document_chunks_tenant_doc", "document_chunks", ["tenant_id", "document_id"], unique=False)

    # 6. Create embeddings table
    op.create_table(
        "embeddings",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("document_chunk_id", GUID(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("vector", Vector(1536), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_chunk_id", name="uq_embeddings_document_chunk_id"),
    )
    op.create_index(op.f("ix_embeddings_id"), "embeddings", ["id"], unique=False)
    op.create_index(op.f("ix_embeddings_tenant_id"), "embeddings", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_embeddings_document_chunk_id"), "embeddings", ["document_chunk_id"], unique=True)
    op.create_index("ix_embeddings_tenant_chunk", "embeddings", ["tenant_id", "document_chunk_id"], unique=False)

    if is_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_embeddings_vector_hnsw ON embeddings USING hnsw (vector vector_cosine_ops);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_hnsw;")

    op.drop_table("embeddings")
    op.drop_table("document_chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
