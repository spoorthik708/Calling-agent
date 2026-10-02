from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    role: str = Field(default="member")
    status: str = Field(default="active")
    is_active: bool = Field(default=True)


class UserCreate(UserBase):
    password: str = Field(..., min_length=12)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdateRequest(BaseModel):
    """User self-update schema. Cannot modify email, role, status, or tenant_id."""
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)


class UserAdminUpdateRequest(BaseModel):
    """Admin update schema for managing other users."""
    role: Optional[str] = None
    status: Optional[str] = None


class UserResponse(BaseModel):
    """
    Safe user response model.
    CRITICAL: password and hashed_password are NEVER exposed.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    status: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
