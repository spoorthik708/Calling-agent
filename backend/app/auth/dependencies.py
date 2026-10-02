from typing import Callable, Optional
import uuid
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import (
    TenantContext,
    UserContext,
    get_current_tenant_context,
    get_current_user_context,
    set_current_tenant_context,
    set_current_user_context,
)
from app.auth.rbac import Role, has_permission
from app.core.exceptions import TenantIsolationError
from app.core.security import decode_access_token
from app.database.session import get_db
from app.tenants.models import Tenant
from app.users.models import User

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Core authentication dependency.
    1. Extracts credentials.
    2. Validates JWT access token signature, type, and expiration.
    3. Resolves authenticated user and tenant.
    4. Enforces user and tenant lifecycle states.
    5. Sets ContextVar tenant and user scoping.
    """
    if not auth_creds or not auth_creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(auth_creds.credentials)
        user_id_str = payload.get("sub")
        tenant_id_str = payload.get("tenant_id")
        if not user_id_str or not tenant_id_str:
            raise ValueError("Token missing required subject or tenant identifier.")
        user_uuid = uuid.UUID(user_id_str)
        tenant_uuid = uuid.UUID(tenant_id_str)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Resolve user and tenant from database
    stmt = (
        select(User)
        .options(selectinload(User.tenant))
        .where(User.id == user_uuid, User.tenant_id == tenant_uuid)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User session invalid or user no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended or inactive.",
        )

    tenant = user.tenant
    if not tenant or not tenant.is_active or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant account is suspended or inactive.",
        )

    # Securely set request context
    tenant_context = TenantContext(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
    )
    user_context = UserContext(
        user_id=user.id,
        tenant_id=tenant.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
    )
    set_current_tenant_context(tenant_context)
    set_current_user_context(user_context)

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensures current user is fully active."""
    return current_user


def require_permission(permission_str: str) -> Callable:
    """
    Factory creating FastAPI dependency that asserts current user possesses the required permission.
    Returns HTTP 403 Forbidden if not authorized.
    """
    async def permission_dependency(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if not has_permission(current_user.role, permission_str):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Missing required permission '{permission_str}'.",
            )
        return current_user

    return permission_dependency


def require_role(allowed_roles: list[Role]) -> Callable:
    """
    Factory asserting that the user's role is in the allowed roles list.
    """
    role_values = [r.value for r in allowed_roles]

    async def role_dependency(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in role_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Role unauthorized for this operation.",
            )
        return current_user

    return role_dependency


async def get_tenant_context_from_header_or_token(
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """
    Legacy tenant resolver supporting webhook/service calls with validation.
    For standard authenticated user endpoints, use `get_current_user` instead.
    """
    context = get_current_tenant_context()
    if context:
        return context

    if auth_creds and auth_creds.credentials:
        try:
            payload = decode_access_token(auth_creds.credentials)
            tenant_uuid = uuid.UUID(payload["tenant_id"])
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token invalid.",
            )
    elif x_tenant_id:
        try:
            tenant_uuid = uuid.UUID(x_tenant_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tenant UUID format.",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required.",
        )

    stmt = select(Tenant).where(Tenant.id == tenant_uuid)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant invalid or inactive.",
        )

    ctx = TenantContext(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
    )
    set_current_tenant_context(ctx)
    return ctx
