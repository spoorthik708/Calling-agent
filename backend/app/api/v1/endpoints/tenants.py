from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_active_user,
    require_permission,
)
from app.auth.rbac import Permission
from app.database.session import get_db
from app.tenants.models import Tenant
from app.tenants.schemas import TenantResponse, TenantUpdateRequest
from app.users.models import User

router = APIRouter(prefix="/tenant", tags=["Tenants"])


@router.get(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Tenant Profile",
    description="Returns the organization profile for the authenticated caller's tenant.",
)
async def get_tenant_profile(
    current_user: User = Depends(require_permission(Permission.TENANT_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    return TenantResponse.model_validate(tenant)


@router.patch(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Tenant Profile",
    description="Updates permitted organization profile fields. Restricted to OWNER role via 'tenant:update' permission.",
)
async def update_tenant_profile(
    update_data: TenantUpdateRequest,
    current_user: User = Depends(require_permission(Permission.TENANT_UPDATE.value)),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    if update_data.name is not None:
        tenant.name = update_data.name.strip()

    await db.commit()
    await db.refresh(tenant)
    return TenantResponse.model_validate(tenant)
