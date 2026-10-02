from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class TenantBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    tier: str = Field(default="standard")


class TenantCreate(TenantBase):
    pass


class TenantUpdateRequest(BaseModel):
    """Safe tenant update schema. Prevents mass assignment of id, slug, status, tier."""
    name: Optional[str] = Field(None, min_length=2, max_length=255)


class TenantResponse(TenantBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
