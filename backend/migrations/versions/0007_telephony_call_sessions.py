"""Phase 7: Telephony Routing, Call Dispatcher & Call Sessions

Revision ID: 0007_telephony_call_sessions
Revises: 0006_voice_sessions
Create Date: 2026-10-10 14:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.database.base import GUID

revision: str = "0007_telephony_call_sessions"
down_revision: Union[str, None] = "0006_voice_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(JSONB, "postgresql") if is_postgres else sa.JSON()

    # Create call_sessions table
    op.create_table(
        "call_sessions",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=True),
        sa.Column("voice_session_id", GUID(), nullable=True),
        sa.Column("provider_call_id", sa.String(length=255), nullable=False),
        sa.Column("telephony_provider", sa.String(length=64), nullable=False, server_default="twilio"),
        sa.Column("direction", sa.String(length=32), nullable=False, server_default="inbound"),
        sa.Column("from_phone", sa.String(length=64), nullable=False),
        sa.Column("to_phone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("recording_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["voice_session_id"], ["voice_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_call_id"),
    )
    op.create_index(op.f("ix_call_sessions_id"), "call_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_call_sessions_tenant_id"), "call_sessions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_call_sessions_agent_id"), "call_sessions", ["agent_id"], unique=False)
    op.create_index(op.f("ix_call_sessions_conversation_id"), "call_sessions", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_call_sessions_voice_session_id"), "call_sessions", ["voice_session_id"], unique=False)
    op.create_index(op.f("ix_call_sessions_provider_call_id"), "call_sessions", ["provider_call_id"], unique=True)
    op.create_index(op.f("ix_call_sessions_from_phone"), "call_sessions", ["from_phone"], unique=False)
    op.create_index(op.f("ix_call_sessions_to_phone"), "call_sessions", ["to_phone"], unique=False)
    op.create_index(op.f("ix_call_sessions_status"), "call_sessions", ["status"], unique=False)
    op.create_index("ix_call_sessions_tenant_status", "call_sessions", ["tenant_id", "status"], unique=False)
    op.create_index("ix_call_sessions_tenant_created", "call_sessions", ["tenant_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_call_sessions_tenant_created", table_name="call_sessions")
    op.drop_index("ix_call_sessions_tenant_status", table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_status"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_to_phone"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_from_phone"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_provider_call_id"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_voice_session_id"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_conversation_id"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_agent_id"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_tenant_id"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_id"), table_name="call_sessions")
    op.drop_table("call_sessions")
