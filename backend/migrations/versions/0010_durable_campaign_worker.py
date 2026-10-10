"""Durable Campaign Worker Migration

Revision ID: 0010_durable_campaign_worker
Revises: 0009_contacts_and_csv_imports
Create Date: 2026-10-10 16:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from app.database.base import GUID

revision: str = "0010_durable_campaign_worker"
down_revision: Union[str, None] = "0009_contacts_and_csv_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add skipped_count to telephony_campaigns
    op.add_column("telephony_campaigns", sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"))

    # 2. Create telephony_campaign_targets table
    op.create_table(
        "telephony_campaign_targets",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("campaign_id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("phone_number", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("provider_call_id", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["telephony_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "phone_number", name="uq_campaign_target_phone"),
    )
    op.create_index(op.f("ix_telephony_campaign_targets_id"), "telephony_campaign_targets", ["id"], unique=False)
    op.create_index(op.f("ix_telephony_campaign_targets_campaign_id"), "telephony_campaign_targets", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_telephony_campaign_targets_tenant_id"), "telephony_campaign_targets", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_telephony_campaign_targets_phone_number"), "telephony_campaign_targets", ["phone_number"], unique=False)
    op.create_index(op.f("ix_telephony_campaign_targets_status"), "telephony_campaign_targets", ["status"], unique=False)
    op.create_index(op.f("ix_telephony_campaign_targets_provider_call_id"), "telephony_campaign_targets", ["provider_call_id"], unique=False)
    op.create_index("ix_campaign_targets_tenant_status", "telephony_campaign_targets", ["tenant_id", "status"], unique=False)
    op.create_index("ix_campaign_targets_next_retry", "telephony_campaign_targets", ["status", "next_retry_at"], unique=False)


def downgrade() -> None:
    op.drop_table("telephony_campaign_targets")
    op.drop_column("telephony_campaigns", "skipped_count")
