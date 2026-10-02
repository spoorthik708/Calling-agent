from typing import List
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_active_user,
    require_permission,
)
from app.auth.rbac import Permission, Role, can_manage_target_user
from app.database.session import get_db
from app.security.tenant_isolation import enforce_tenant_filter
from app.users.models import User
from app.users.schemas import (
    UserAdminUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Authenticated User Profile",
    description="Returns the profile details of the currently authenticated user.",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Authenticated User Profile",
    description="Allows updating first and last name. Email, role, and tenant cannot be modified here.",
)
async def update_me(
    update_data: UserUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    if update_data.first_name is not None:
        current_user.first_name = update_data.first_name.strip()
    if update_data.last_name is not None:
        current_user.last_name = update_data.last_name.strip()

    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.get(
    "",
    response_model=List[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List Tenant Users",
    description="Lists all users belonging to the caller's tenant. Requires 'users:read' permission.",
)
async def list_users(
    current_user: User = Depends(require_permission(Permission.USERS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[UserResponse]:
    # Strictly filtered to current user's tenant
    query = enforce_tenant_filter(select(User), User, current_user.tenant_id)
    result = await db.execute(query)
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Tenant User (Admin)",
    description="Updates role or status of another tenant user. Protected by Owner/Admin safety rules.",
)
async def update_tenant_user(
    user_id: uuid.UUID,
    update_data: UserAdminUpdateRequest,
    current_user: User = Depends(require_permission(Permission.USERS_UPDATE.value)),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    # Query target user strictly within tenant boundary
    stmt = select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found within your organization.",
        )

    # SECTION 16: OWNER PROTECTION CHECK
    if not can_manage_target_user(current_user.role, target_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot modify users with equal or higher administrative privileges.",
        )

    if update_data.role is not None:
        # Validate role
        try:
            new_role = Role(update_data.role.lower())
            # Non-owners cannot promote someone to owner
            if new_role == Role.OWNER and current_user.role != Role.OWNER.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the current Owner can assign the Owner role.",
                )
            target_user.role = new_role.value
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role '{update_data.role}'.",
            )

    if update_data.status is not None:
        if update_data.status not in ["active", "suspended", "disabled"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{update_data.status}'.",
            )
        # SEC-04: Prevent tenant OWNER from disabling or suspending their own account
        if (
            target_user.id == current_user.id
            and current_user.role == Role.OWNER.value
            and update_data.status in ["suspended", "disabled"]
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tenant owners cannot disable or suspend their own account.",
            )
        target_user.status = update_data.status
        target_user.is_active = (update_data.status == "active")

    await db.commit()
    await db.refresh(target_user)
    return UserResponse.model_validate(target_user)
