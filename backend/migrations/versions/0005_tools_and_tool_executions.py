"""Phase 5: Production AI Tool and Action Layer

Revision ID: 0005_tools_and_tool_executions
Revises: 0004_agent_and_conversations
Create Date: 2026-10-02 17:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.database.base import GUID

revision: str = "0005_tools_and_tool_executions"
down_revision: Union[str, None] = "0004_agent_and_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(JSONB, "postgresql") if is_postgres else sa.JSON()

    # 1. Create tool_definitions table
    op.create_table(
        "tool_definitions",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tool_type", sa.String(length=50), nullable=False, server_default="internal"),
        sa.Column("version", sa.String(length=20), nullable=False, server_default="1.0.0"),
        sa.Column("input_schema", json_type, nullable=False),
        sa.Column("output_schema", json_type, nullable=False),
        sa.Column("configuration", json_type, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tool_tenant_name"),
    )
    op.create_index(op.f("ix_tool_definitions_id"), "tool_definitions", ["id"], unique=False)
    op.create_index(op.f("ix_tool_definitions_tenant_id"), "tool_definitions", ["tenant_id"], unique=False)
    op.create_index("ix_tools_tenant_active", "tool_definitions", ["tenant_id", "is_active"], unique=False)
    op.create_index("ix_tools_tenant_type", "tool_definitions", ["tenant_id", "tool_type"], unique=False)

    # 2. Create agent_tools association table
    op.create_table(
        "agent_tools",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("tool_id", GUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["tool_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "tool_id", name="uq_agent_tool"),
    )
    op.create_index(op.f("ix_agent_tools_id"), "agent_tools", ["id"], unique=False)
    op.create_index(op.f("ix_agent_tools_tenant_id"), "agent_tools", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_agent_tools_agent_id"), "agent_tools", ["agent_id"], unique=False)
    op.create_index(op.f("ix_agent_tools_tool_id"), "agent_tools", ["tool_id"], unique=False)
    op.create_index("ix_agent_tools_tenant_agent", "agent_tools", ["tenant_id", "agent_id"], unique=False)
    op.create_index("ix_agent_tools_agent_tool", "agent_tools", ["agent_id", "tool_id"], unique=False)

    # 3. Create tool_executions table
    op.create_table(
        "tool_executions",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=True),
        sa.Column("conversation_id", GUID(), nullable=True),
        sa.Column("message_id", GUID(), nullable=True),
        sa.Column("tool_id", GUID(), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("tool_version", sa.String(length=20), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("validated_input", json_type, nullable=False),
        sa.Column("sanitized_output", json_type, nullable=True),
        sa.Column("error_category", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tool_id"], ["tool_definitions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_executions_id"), "tool_executions", ["id"], unique=False)
    op.create_index(op.f("ix_tool_executions_tenant_id"), "tool_executions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_agent_id"), "tool_executions", ["agent_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_conversation_id"), "tool_executions", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_message_id"), "tool_executions", ["message_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_tool_id"), "tool_executions", ["tool_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_correlation_id"), "tool_executions", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_idempotency_key"), "tool_executions", ["idempotency_key"], unique=False)
    op.create_index("ix_tool_exec_tenant_created", "tool_executions", ["tenant_id", "created_at"], unique=False)
    op.create_index("ix_tool_exec_tenant_status", "tool_executions", ["tenant_id", "status"], unique=False)
    op.create_index("ix_tool_exec_tenant_tool", "tool_executions", ["tenant_id", "tool_name"], unique=False)
    op.create_index("ix_tool_exec_idempotency", "tool_executions", ["tenant_id", "idempotency_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tool_exec_idempotency", table_name="tool_executions")
    op.drop_index("ix_tool_exec_tenant_tool", table_name="tool_executions")
    op.drop_index("ix_tool_exec_tenant_status", table_name="tool_executions")
    op.drop_index("ix_tool_exec_tenant_created", table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_idempotency_key"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_correlation_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_tool_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_message_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_conversation_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_agent_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_tenant_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_id"), table_name="tool_executions")
    op.drop_table("tool_executions")

    op.drop_index("ix_agent_tools_agent_tool", table_name="agent_tools")
    op.drop_index("ix_agent_tools_tenant_agent", table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_tool_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_agent_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_tenant_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_id"), table_name="agent_tools")
    op.drop_table("agent_tools")

    op.drop_index("ix_tools_tenant_type", table_name="tool_definitions")
    op.drop_index("ix_tools_tenant_active", table_name="tool_definitions")
    op.drop_index(op.f("ix_tool_definitions_tenant_id"), table_name="tool_definitions")
    op.drop_index(op.f("ix_tool_definitions_id"), table_name="tool_definitions")
    op.drop_table("tool_definitions")
