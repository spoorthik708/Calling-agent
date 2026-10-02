from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
import uuid
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, GUID, TenantAwareModel, TimestampMixin


class AgentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class Agent(Base, TimestampMixin, TenantAwareModel):
    """
    Tenant-owned AI Conversational Agent.
    Configures system prompts, language, LLM parameters, grounding, and fallback behavior.
    """
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agent_tenant_name"),
        Index("ix_agents_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=AgentStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    default_language: Mapped[str] = mapped_column(
        String(10),
        default="en",
        nullable=False,
    )
    llm_provider: Mapped[str] = mapped_column(
        String(100),
        default="mock",
        nullable=False,
    )
    llm_model: Mapped[str] = mapped_column(
        String(100),
        default="gpt-4o-mini",
        nullable=False,
    )
    temperature: Mapped[float] = mapped_column(
        Float,
        default=0.2,
        nullable=False,
    )
    max_output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=1024,
        nullable=False,
    )
    fallback_message: Mapped[str] = mapped_column(
        Text,
        default="I'm sorry, I don't have enough verified information to answer that accurately.",
        nullable=False,
    )
    escalation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    knowledge_base_associations: Mapped[List["AgentKnowledgeBase"]] = relationship(
        "AgentKnowledgeBase",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentKnowledgeBase(Base, TenantAwareModel):
    """
    Explicit authorization link between an Agent and a KnowledgeBase.
    An agent may only retrieve information from explicitly attached knowledge bases.
    """
    __tablename__ = "agent_knowledge_bases"
    __table_args__ = (
        UniqueConstraint("agent_id", "knowledge_base_id", name="uq_agent_knowledge_base"),
        Index("ix_agent_kb_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_agent_kb_agent_kb", "agent_id", "knowledge_base_id"),
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
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(
        "Agent",
        back_populates="knowledge_base_associations",
    )
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase",
    )
