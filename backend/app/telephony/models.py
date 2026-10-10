"""Telephony Database Models for Phase 7.

Persistent state tracking for inbound and outbound calls, provider references,
lifecycle status transitions, call duration, recordings, and multi-tenant isolation.
"""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
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
