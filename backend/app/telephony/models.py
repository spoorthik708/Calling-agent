"""Telephony Database Models for Phase 7.

Persistent state tracking for inbound and outbound calls, provider references,
lifecycle status transitions, call duration, recordings, and multi-tenant isolation.
"""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TenantAwareModel
from app.telephony.interfaces import CallDirection, CallState


class CallSession(Base, TenantAwareModel):
    """
    CallSession model representing a PSTN/SIP phone call session.
    Tracks provider call IDs, direction, phone numbers, state machine,
    recording metadata, and links to VoiceSession & Conversation.
    """

    __tablename__ = "call_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    voice_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_call_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    telephony_provider: Mapped[str] = mapped_column(
        String(64),
        default="twilio",
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(
        String(32),
        default=CallDirection.INBOUND.value,
        nullable=False,
    )
    from_phone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    to_phone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=CallState.QUEUED.value,
        nullable=False,
        index=True,
    )
    recording_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    call_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSONB if hasattr(JSONB, "as_generic") else JSONB,
        default=dict,
        nullable=False,
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
        Index("ix_call_sessions_tenant_status", "tenant_id", "status"),
        Index("ix_call_sessions_tenant_created", "tenant_id", "created_at"),
    )


class Campaign(Base, TenantAwareModel):
    """
    Campaign model representing automated outbound calling campaigns.
    Tracks target phone contact lists, agent assignments, schedule, progress,
    and completion status.
    """

    __tablename__ = "telephony_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_list_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    from_phone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="draft",
        nullable=False,
        index=True,
    )
    target_phones: Mapped[Dict[str, Any]] = mapped_column(
        JSONB if hasattr(JSONB, "as_generic") else JSONB,
        default=list,
        nullable=False,
    )
    completed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    custom_parameters: Mapped[Dict[str, Any]] = mapped_column(
        JSONB if hasattr(JSONB, "as_generic") else JSONB,
        default=dict,
        nullable=False,
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
        Index("ix_telephony_campaigns_tenant_status", "tenant_id", "status"),
        Index("ix_telephony_campaigns_tenant_created", "tenant_id", "created_at"),
    )


class CampaignTarget(Base, TenantAwareModel):
    """
    CampaignTarget model representing an individual target phone record within a campaign.
    Tracks persistent execution state machine (queued, in_progress, completed, failed,
    skipped_opt_out, cancelled), attempt counts, exponential backoff timestamps,
    and provider call identifiers across application restarts and worker crashes.
    """

    __tablename__ = "telephony_campaign_targets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telephony_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="queued",
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    provider_call_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
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
        UniqueConstraint("campaign_id", "phone_number", name="uq_campaign_target_phone"),
        Index("ix_campaign_targets_tenant_status", "tenant_id", "status"),
        Index("ix_campaign_targets_next_retry", "status", "next_retry_at"),
    )
