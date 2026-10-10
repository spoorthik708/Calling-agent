"""Contacts and Contact Lists Database Models.

Tracks tenant contacts, E.164 phone numbers, consent/opt-out status,
tags, custom metadata, and contact list memberships under multi-tenant isolation.
"""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantAwareModel


class Contact(Base, TenantAwareModel):
    """
    Contact model representing an individual phone contact within a tenant.
    Enforces normalized E.164 phone numbers, consent status (opted_in, opted_out, suppressed),
    and tenant-scoped uniqueness.
    """

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        default="",
        nullable=False,
    )
    phone_number: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    tags: Mapped[List[str]] = mapped_column(
        JSONB if hasattr(JSONB, "as_generic") else JSONB,
        default=list,
        nullable=False,
    )
    custom_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSONB if hasattr(JSONB, "as_generic") else JSONB,
        default=dict,
        nullable=False,
    )
    consent_status: Mapped[str] = mapped_column(
        String(32),
        default="opted_in",
        nullable=False,
        index=True,
    )
    opted_out_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_number", name="uq_contacts_tenant_phone"),
        Index("ix_contacts_tenant_phone", "tenant_id", "phone_number"),
        Index("ix_contacts_tenant_consent", "tenant_id", "consent_status"),
    )


class ContactList(Base, TenantAwareModel):
    """
    ContactList model representing named groups/segments of contacts for campaigns.
    """

    __tablename__ = "contact_lists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_contact_lists_tenant_created", "tenant_id", "created_at"),
    )


class ContactListMembership(Base):
    """
    Junction table linking Contacts to ContactLists.
    """

    __tablename__ = "contact_list_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("list_id", "contact_id", name="uq_contact_list_membership"),
    )
