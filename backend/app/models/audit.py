from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid
from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base, GUID, TenantAwareModel


class AuditLog(Base, TenantAwareModel):
    """
    Immutable audit log tracking all sensitive actions, tenant access,
    tool invocations, and agent state transitions.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} tenant={self.tenant_id} action={self.action}>"
