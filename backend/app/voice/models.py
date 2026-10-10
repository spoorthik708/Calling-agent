"""Voice Session Persistent Domain Model.

Tracks active real-time voice conversations across channels (web, browser, and future telephony).
Enforces:
1. Tenant-scoped persistence and indexing.
2. Full lifecycle state tracking.
3. Language and provider binding.
4. Ephemeral audio privacy (raw audio blobs are NEVER stored here).
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, GUID, TenantAwareModel, TimestampMixin
from app.voice.state import VoiceSessionStatus


class VoiceSession(Base, TimestampMixin, TenantAwareModel):
    """
    Persistent voice session entity representing an active or completed real-time voice call.
    Stores operational metadata and state machine position.
    """
    __tablename__ = "voice_sessions"
    __table_args__ = (
        Index("ix_voice_sessions_tenant_created", "tenant_id", "created_at"),
        Index("ix_voice_sessions_tenant_status", "tenant_id", "status"),
        Index("ix_voice_sessions_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_voice_sessions_tenant_conv", "tenant_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=VoiceSessionStatus.CREATED.value,
        index=True,
    )
    input_language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
    )
    output_language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
    )
    stt_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="mock",
    )
    tts_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="mock",
    )
    vad_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="energy",
    )
    voice_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    current_generation_id: Mapped[int] = mapped_column(
        default=1,
        nullable=False,
    )
    turn_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )
    interruption_count: Mapped[int] = mapped_column(
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
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    termination_reason: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    session_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(  # noqa: F821
        "Agent",
        foreign_keys=[agent_id],
    )
    conversation: Mapped[Optional["Conversation"]] = relationship(  # noqa: F821
        "Conversation",
        foreign_keys=[conversation_id],
    )
