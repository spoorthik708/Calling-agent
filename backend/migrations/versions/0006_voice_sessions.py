"""Phase 6: Production Real-Time Voice Intelligence Layer

Revision ID: 0006_voice_sessions
Revises: 0005_tools_and_tool_executions
Create Date: 2026-10-02 19:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.database.base import GUID

revision: str = "0006_voice_sessions"
down_revision: Union[str, None] = "0005_tools_and_tool_executions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(JSONB, "postgresql") if is_postgres else sa.JSON()

    # 1. Create voice_sessions table
    op.create_table(
        "voice_sessions",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="created"),
        sa.Column("input_language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("output_language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("stt_provider", sa.String(length=50), nullable=False),
        sa.Column("tts_provider", sa.String(length=50), nullable=False),
        sa.Column("vad_provider", sa.String(length=50), nullable=False),
        sa.Column("voice_id", sa.String(length=100), nullable=True),
        sa.Column("current_generation_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interruption_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("termination_reason", sa.String(length=100), nullable=True),
        sa.Column("session_metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_voice_sessions_id"), "voice_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_voice_sessions_tenant_id"), "voice_sessions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_voice_sessions_agent_id"), "voice_sessions", ["agent_id"], unique=False)
    op.create_index(op.f("ix_voice_sessions_conversation_id"), "voice_sessions", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_voice_sessions_status"), "voice_sessions", ["status"], unique=False)
    op.create_index("ix_voice_sessions_tenant_status", "voice_sessions", ["tenant_id", "status"], unique=False)
    op.create_index("ix_voice_sessions_tenant_created", "voice_sessions", ["tenant_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_voice_sessions_tenant_created", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_tenant_status", table_name="voice_sessions")
    op.drop_index(op.f("ix_voice_sessions_status"), table_name="voice_sessions")
    op.drop_index(op.f("ix_voice_sessions_conversation_id"), table_name="voice_sessions")
    op.drop_index(op.f("ix_voice_sessions_agent_id"), table_name="voice_sessions")
    op.drop_index(op.f("ix_voice_sessions_tenant_id"), table_name="voice_sessions")
    op.drop_index(op.f("ix_voice_sessions_id"), table_name="voice_sessions")
    op.drop_table("voice_sessions")
