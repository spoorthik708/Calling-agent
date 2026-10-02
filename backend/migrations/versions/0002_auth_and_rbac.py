"""Phase 2: Authentication, RBAC, and refresh tokens

Revision ID: 0002_auth_and_rbac
Revises: 0001_initial_foundation
Create Date: 2026-10-02 12:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from app.database.base import GUID

revision: str = "0002_auth_and_rbac"
down_revision: Union[str, None] = "0001_initial_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update tenants table
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(length=50), nullable=False, server_default="active")
        )

    # 2. Update users table
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("first_name", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("last_name", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(length=50), nullable=False, server_default="active"))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint("uq_user_tenant_email", ["tenant_id", "email"])

    # 3. Create refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("family_id", GUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_by_token_id", GUID(), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_tokens_id"), "refresh_tokens", ["id"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_tenant_id"), "refresh_tokens", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_user_tenant_email", type_="unique")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("status")
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("status")
