from typing import Optional
import uuid
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import (
    TenantContext,
    UserContext,
    set_current_tenant_context,
    set_current_user_context,
)
from app.core.exceptions import TenantIsolationError
from app.core.security import decode_token
from app.database.session import get_db

security_scheme = HTTPBearer(auto_error=False)


async def get_tenant_context_from_header_or_token(
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """
    Enforces tenant context resolution.
    Resolution order:
    1. Verified JWT claims ('tenant_id').
    2. Explicit 'X-Tenant-ID' header (for machine-to-machine/webhook workflows with authorization).
    """
    tenant_id_str: Optional[str] = None
    user_context: Optional[UserContext] = None

    if auth_creds and auth_creds.credentials:
        try:
            payload = decode_token(auth_creds.credentials)
            tenant_id_str = payload.get("tenant_id")
            user_id_str = payload.get("sub")
            if user_id_str and tenant_id_str:
                user_context = UserContext(
                    user_id=uuid.UUID(user_id_str),
                    tenant_id=uuid.UUID(tenant_id_str),
                    email=payload.get("email", ""),
                    role=payload.get("role", "member"),
                    is_active=True,
                )
                set_current_user_context(user_context)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication token invalid: {str(e)}",
            )

    # Fallback to explicit header if not resolved via token
    if not tenant_id_str and x_tenant_id:
        tenant_id_str = x_tenant_id

    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required. Provide valid JWT or X-Tenant-ID header.",
        )

    try:
        tenant_uuid = uuid.UUID(tenant_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant UUID format.",
        )

    # In production, query the tenant to verify existence and active status
    # Import locally to avoid circular dependencies
    from app.tenants.models import Tenant
    stmt = select(Tenant).where(Tenant.id == tenant_uuid)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_uuid}' does not exist or has been decommissioned.",
        )

    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{tenant.name}' is suspended or inactive.",
        )

    # If user context was established, verify tenant match
    if user_context and user_context.tenant_id != tenant.id:
        raise TenantIsolationError(
            f"Cross-tenant access violation: user tenant {user_context.tenant_id} != target tenant {tenant.id}"
        )

    context = TenantContext(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
    )
    set_current_tenant_context(context)
    return context
