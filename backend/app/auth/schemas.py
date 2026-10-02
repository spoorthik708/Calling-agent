from typing import Optional
from pydantic import BaseModel, EmailStr, Field

from app.tenants.schemas import TenantResponse
from app.users.schemas import UserResponse


class TenantRegisterRequest(BaseModel):
    """
    Tenant registration request payload.
    Creates Tenant and initial administrative Owner user atomically.
    Role is fixed by the system to 'owner' and cannot be specified by the client.
    """
    tenant_name: str = Field(..., min_length=2, max_length=255, description="Business or company name")
    tenant_slug: str = Field(
        ...,
        min_length=2,
        max_length=100,
        pattern=r"^[a-z0-9-]+$",
        description="Unique URL-friendly tenant identifier",
    )
    email: EmailStr = Field(..., description="Administrator email address")
    password: str = Field(..., min_length=12, description="Secure account password (min 12 characters)")
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)


class LoginRequest(BaseModel):
    """Credentials for authentication."""
    email: EmailStr
    password: str
    tenant_slug: Optional[str] = Field(None, description="Optional tenant slug to disambiguate accounts")


class TokenResponse(BaseModel):
    """Authentication token response containing access token and refresh token."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    tenant: TenantResponse


class RefreshTokenRequest(BaseModel):
    """Payload to rotate and obtain a new access/refresh token pair."""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Logout request payload."""
    refresh_token: Optional[str] = None
    all_sessions: bool = False


class LogoutResponse(BaseModel):
    success: bool = True
    message: str = "Successfully logged out."
