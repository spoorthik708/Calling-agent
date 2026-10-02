import uuid
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, GUID, TenantAwareModel, TimestampMixin

if TYPE_CHECKING:
    from app.tenants.models import Tenant


class User(Base, TenantAwareModel, TimestampMixin):
    """
    User entity belonging strictly to a Tenant.
    Roles: 'admin', 'manager', 'operator', 'read_only'
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} tenant_id={self.tenant_id}>"
