from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base, GUID, TenantAwareModel, TimestampMixin


class ConversationChannel(str, Enum):
    TEXT = "text"
    API = "api"
    VOICE = "voice"


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Conversation(Base, TimestampMixin, TenantAwareModel):
    """
    Persistent multi-turn conversation session bounded by tenant and agent.
    """
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_conversations_tenant_status", "tenant_id", "status"),
        Index("ix_conversations_tenant_last_msg", "tenant_id", "last_message_at"),
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
    external_user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    channel: Mapped[str] = mapped_column(
        String(50),
        default=ConversationChannel.TEXT.value,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=ConversationStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(
        String(10),
        default="en",
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    conversation_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(
        "Agent",
        back_populates="conversations",
    )
    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.sequence_number",
    )


class Message(Base, TenantAwareModel):
    """
    Individual turn message within a conversation.
    Enforces monotonically increasing sequence_number per conversation.
    """
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence_number", name="uq_message_conversation_sequence"),
        Index("ix_messages_tenant_conversation", "tenant_id", "conversation_id"),
        Index("ix_messages_conversation_seq", "conversation_id", "sequence_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    llm_provider: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    llm_model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    prompt_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    completion_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    latency_ms: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    citations: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    message_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )


class IdempotencyRecord(Base, TenantAwareModel):
    """
    Stores idempotency keys to guarantee safe retry semantics for conversation turns.
    Scoped strictly by tenant_id + idempotency_key + endpoint.
    """
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", "endpoint", name="uq_tenant_idempotency_endpoint"),
        Index("ix_idempotency_tenant_key", "tenant_id", "idempotency_key"),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    response_status_code: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    response_body: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
