"""Contacts, Contact Lists, and CSV Imports Migration

Revision ID: 0009_contacts_and_csv_imports
Revises: 0008_telephony_campaigns
Create Date: 2026-10-10 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.database.base import GUID

revision: str = "0009_contacts_and_csv_imports"
down_revision: Union[str, None] = "0008_telephony_campaigns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(JSONB, "postgresql") if is_postgres else sa.JSON()

    # 1. Create contacts table
    op.create_table(
        "contacts",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("phone_number", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("tags", json_type, nullable=False),
        sa.Column("custom_metadata", json_type, nullable=False),
        sa.Column("consent_status", sa.String(length=32), nullable=False, server_default="opted_in"),
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "phone_number", name="uq_contacts_tenant_phone"),
    )
    op.create_index(op.f("ix_contacts_id"), "contacts", ["id"], unique=False)
    op.create_index(op.f("ix_contacts_tenant_id"), "contacts", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_contacts_phone_number"), "contacts", ["phone_number"], unique=False)
    op.create_index(op.f("ix_contacts_email"), "contacts", ["email"], unique=False)
    op.create_index(op.f("ix_contacts_consent_status"), "contacts", ["consent_status"], unique=False)
    op.create_index("ix_contacts_tenant_phone", "contacts", ["tenant_id", "phone_number"], unique=False)
    op.create_index("ix_contacts_tenant_consent", "contacts", ["tenant_id", "consent_status"], unique=False)

    # 2. Create contact_lists table
    op.create_table(
        "contact_lists",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_contact_lists_id"), "contact_lists", ["id"], unique=False)
    op.create_index(op.f("ix_contact_lists_tenant_id"), "contact_lists", ["tenant_id"], unique=False)
    op.create_index("ix_contact_lists_tenant_created", "contact_lists", ["tenant_id", "created_at"], unique=False)

    # 3. Create contact_list_memberships table
    op.create_table(
        "contact_list_memberships",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("list_id", GUID(), nullable=False),
        sa.Column("contact_id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["list_id"], ["contact_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("list_id", "contact_id", name="uq_contact_list_membership"),
    )
    op.create_index(op.f("ix_contact_list_memberships_id"), "contact_list_memberships", ["id"], unique=False)
    op.create_index(op.f("ix_contact_list_memberships_list_id"), "contact_list_memberships", ["list_id"], unique=False)
    op.create_index(op.f("ix_contact_list_memberships_contact_id"), "contact_list_memberships", ["contact_id"], unique=False)

    # 4. Add contact_list_id to telephony_campaigns
    op.add_column("telephony_campaigns", sa.Column("contact_list_id", GUID(), nullable=True))
    op.create_foreign_key("fk_telephony_campaigns_contact_list_id", "telephony_campaigns", "contact_lists", ["contact_list_id"], ["id"], ondelete="SET NULL")
    op.create_index(op.f("ix_telephony_campaigns_contact_list_id"), "telephony_campaigns", ["contact_list_id"], unique=False)


def downgrade() -> None:
    op.drop_constraint("fk_telephony_campaigns_contact_list_id", "telephony_campaigns", type_="foreignkey")
    op.drop_index(op.f("ix_telephony_campaigns_contact_list_id"), table_name="telephony_campaigns")
    op.drop_column("telephony_campaigns", "contact_list_id")

    op.drop_table("contact_list_memberships")
    op.drop_table("contact_lists")
    op.drop_table("contacts")
