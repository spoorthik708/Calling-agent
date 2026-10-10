"""Telephony Campaigns Migration

Revision ID: 0008_telephony_campaigns
Revises: 0007_telephony_call_sessions
Create Date: 2026-10-10 15:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.database.base import GUID

revision: str = "0008_telephony_campaigns"
down_revision: Union[str, None] = "0007_telephony_call_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(JSONB, "postgresql") if is_postgres else sa.JSON()

    # Create telephony_campaigns table
    op.create_table(
        "telephony_campaigns",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("from_phone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("target_phones", json_type, nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("custom_parameters", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telephony_campaigns_id"), "telephony_campaigns", ["id"], unique=False)
    op.create_index(op.f("ix_telephony_campaigns_tenant_id"), "telephony_campaigns", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_telephony_campaigns_agent_id"), "telephony_campaigns", ["agent_id"], unique=False)
    op.create_index(op.f("ix_telephony_campaigns_status"), "telephony_campaigns", ["status"], unique=False)
    op.create_index("ix_telephony_campaigns_tenant_status", "telephony_campaigns", ["tenant_id", "status"], unique=False)
    op.create_index("ix_telephony_campaigns_tenant_created", "telephony_campaigns", ["tenant_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telephony_campaigns_tenant_created", table_name="telephony_campaigns")
    op.drop_index("ix_telephony_campaigns_tenant_status", table_name="telephony_campaigns")
    op.drop_index(op.f("ix_telephony_campaigns_status"), table_name="telephony_campaigns")
    op.drop_index(op.f("ix_telephony_campaigns_agent_id"), table_name="telephony_campaigns")
    op.drop_index(op.f("ix_telephony_campaigns_tenant_id"), table_name="telephony_campaigns")
    op.drop_index(op.f("ix_telephony_campaigns_id"), table_name="telephony_campaigns")
    op.drop_table("telephony_campaigns")
