from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, GUID, TenantAwareModel, TimestampMixin


class ToolType(str, Enum):
    INTERNAL = "internal"
    HTTP_API = "http_api"


class ToolExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    VALIDATION_FAILED = "validation_failed"


class ToolDefinition(Base, TimestampMixin, TenantAwareModel):
    """
    Tenant-owned approved business capability/tool definition.
    Stores metadata, schemas, and non-secret configuration.
    Plaintext secrets are NEVER stored in configuration.
    """
    __tablename__ = "tool_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tool_tenant_name"),
        Index("ix_tools_tenant_active", "tenant_id", "is_active"),
        Index("ix_tools_tenant_type", "tenant_id", "tool_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tool_type: Mapped[str] = mapped_column(
        String(50),
        default=ToolType.INTERNAL.value,
        nullable=False,
    )
    version: Mapped[str] = mapped_column(
        String(20),
        default="1.0.0",
        nullable=False,
    )
    input_schema: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    output_schema: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    configuration: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    agent_associations: Mapped[List["AgentTool"]] = relationship(
        "AgentTool",
        back_populates="tool",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentTool(Base, TenantAwareModel):
    """
    Explicit authorization link: Agent <-> ToolDefinition.
    An agent can ONLY invoke tools explicitly assigned to it.
    """
    __tablename__ = "agent_tools"
    __table_args__ = (
        UniqueConstraint("agent_id", "tool_id", name="uq_agent_tool"),
        Index("ix_agent_tools_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_agent_tools_agent_tool", "agent_id", "tool_id"),
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
    tool_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("tool_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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

    # Relationships
    agent: Mapped["Agent"] = relationship(  # noqa: F821
        "Agent",
        back_populates="tool_associations",
    )
    tool: Mapped["ToolDefinition"] = relationship(
        "ToolDefinition",
        back_populates="agent_associations",
    )


class ToolExecution(Base, TenantAwareModel):
    """
    Immutable audit record of a tool execution.
    Retention-friendly storage with strictly sanitized input/output payloads.
    Secrets, passwords, and raw sensitive data are NEVER stored here.
    """
    __tablename__ = "tool_executions"
    __table_args__ = (
        Index("ix_tool_exec_tenant_created", "tenant_id", "created_at"),
        Index("ix_tool_exec_tenant_status", "tenant_id", "status"),
        Index("ix_tool_exec_tenant_tool", "tenant_id", "tool_name"),
        Index("ix_tool_exec_idempotency", "tenant_id", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tool_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("tool_definitions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    validated_input: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    sanitized_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    error_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
