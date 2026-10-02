import uuid
from typing import List, TYPE_CHECKING
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, GUID, TimestampMixin

if TYPE_CHECKING:
    from app.users.models import User


class Tenant(Base, TimestampMixin):
    """
    Tenant entity representing an enterprise or business customer account.
    All business data, conversations, agents, and knowledge are isolated to a Tenant.
    """
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(50), default="standard", nullable=False)

    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug} active={self.is_active}>"
