"""Phase 4: Production AI Agent and Conversation Runtime

Revision ID: 0004_agent_and_conversations
Revises: 0003_knowledge_and_rag
Create Date: 2026-10-02 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.database.base import GUID

revision: str = "0004_agent_and_conversations"
down_revision: Union[str, None] = "0003_knowledge_and_rag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(JSONB, "postgresql") if is_postgres else sa.JSON()

    # 1. Create agents table
    op.create_table(
        "agents",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("default_language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("llm_provider", sa.String(length=100), nullable=False, server_default="mock"),
        sa.Column("llm_model", sa.String(length=100), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("fallback_message", sa.Text(), nullable=False),
        sa.Column("escalation_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_agent_tenant_name"),
    )
    op.create_index(op.f("ix_agents_id"), "agents", ["id"], unique=False)
    op.create_index(op.f("ix_agents_tenant_id"), "agents", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_agents_status"), "agents", ["status"], unique=False)
    op.create_index("ix_agents_tenant_status", "agents", ["tenant_id", "status"], unique=False)

    # 2. Create agent_knowledge_bases association table
    op.create_table(
        "agent_knowledge_bases",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("knowledge_base_id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "knowledge_base_id", name="uq_agent_knowledge_base"),
    )
    op.create_index(op.f("ix_agent_knowledge_bases_id"), "agent_knowledge_bases", ["id"], unique=False)
    op.create_index(op.f("ix_agent_knowledge_bases_tenant_id"), "agent_knowledge_bases", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_agent_knowledge_bases_agent_id"), "agent_knowledge_bases", ["agent_id"], unique=False)
    op.create_index(op.f("ix_agent_knowledge_bases_knowledge_base_id"), "agent_knowledge_bases", ["knowledge_base_id"], unique=False)
    op.create_index("ix_agent_kb_tenant_agent", "agent_knowledge_bases", ["tenant_id", "agent_id"], unique=False)
    op.create_index("ix_agent_kb_agent_kb", "agent_knowledge_bases", ["agent_id", "knowledge_base_id"], unique=False)

    # 3. Create conversations table
    op.create_table(
        "conversations",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=False, server_default="text"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conversation_metadata", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_id"), "conversations", ["id"], unique=False)
    op.create_index(op.f("ix_conversations_tenant_id"), "conversations", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_conversations_agent_id"), "conversations", ["agent_id"], unique=False)
    op.create_index(op.f("ix_conversations_status"), "conversations", ["status"], unique=False)
    op.create_index(op.f("ix_conversations_external_user_id"), "conversations", ["external_user_id"], unique=False)
    op.create_index("ix_conversations_tenant_agent", "conversations", ["tenant_id", "agent_id"], unique=False)
    op.create_index("ix_conversations_tenant_status", "conversations", ["tenant_id", "status"], unique=False)
    op.create_index("ix_conversations_tenant_last_msg", "conversations", ["tenant_id", "last_message_at"], unique=False)

    # 4. Create messages table
    op.create_table(
        "messages",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("llm_provider", sa.String(length=100), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("citations", json_type, nullable=True),
        sa.Column("message_metadata", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "sequence_number", name="uq_message_conversation_sequence"),
    )
    op.create_index(op.f("ix_messages_id"), "messages", ["id"], unique=False)
    op.create_index(op.f("ix_messages_tenant_id"), "messages", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_messages_created_at"), "messages", ["created_at"], unique=False)
    op.create_index("ix_messages_tenant_conversation", "messages", ["tenant_id", "conversation_id"], unique=False)
    op.create_index("ix_messages_conversation_seq", "messages", ["conversation_id", "sequence_number"], unique=False)

    # 5. Create idempotency_records table
    op.create_table(
        "idempotency_records",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", "endpoint", name="uq_tenant_idempotency_endpoint"),
    )
    op.create_index(op.f("ix_idempotency_records_id"), "idempotency_records", ["id"], unique=False)
    op.create_index(op.f("ix_idempotency_records_tenant_id"), "idempotency_records", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_idempotency_records_idempotency_key"), "idempotency_records", ["idempotency_key"], unique=False)
    op.create_index("ix_idempotency_tenant_key", "idempotency_records", ["tenant_id", "idempotency_key"], unique=False)
    op.create_index("ix_idempotency_expires_at", "idempotency_records", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("agent_knowledge_bases")
    op.drop_table("agents")
