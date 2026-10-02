from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
    TenantRegisterRequest,
    TokenResponse,
)
from app.auth.service import AuthService
from app.auth.throttling import enforce_rate_limit, get_client_ip
from app.core.config import get_settings
from app.database.session import get_db
from app.tenants.schemas import TenantResponse
from app.users.models import User
from app.users.schemas import UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register New Company & Owner Account",
    description=(
        "Transactionally provisions a new Tenant and its initial administrative Owner user. "
        "Returns active access and refresh token pair."
    ),
    responses={
        400: {"description": "Validation error or invalid password"},
        409: {"description": "Tenant identifier already registered"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def register(
    request: TenantRegisterRequest,
    http_req: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    enforce_rate_limit(http_req, action="register", max_attempts=10, window_seconds=60)
    auth_service = AuthService(db)
    client_ip = get_client_ip(http_req)
    user_agent = http_req.headers.get("user-agent")

    tenant, owner_user, access_token, raw_refresh = await auth_service.register_tenant_and_owner(
        request=request,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    settings = get_settings()

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(owner_user),
        tenant=TenantResponse.model_validate(tenant),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate User",
    description="Authenticates credentials using email and password with enumeration protections.",
    responses={
        401: {"description": "Invalid email or password"},
        403: {"description": "Account or tenant is inactive or suspended"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def login(
    request: LoginRequest,
    http_req: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    enforce_rate_limit(http_req, action="login", max_attempts=15, window_seconds=60)
    auth_service = AuthService(db)
    client_ip = get_client_ip(http_req)
    user_agent = http_req.headers.get("user-agent")

    tenant, user, access_token, raw_refresh = await auth_service.authenticate_user(
        email=request.email,
        password=request.password,
        tenant_slug=request.tenant_slug,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    settings = get_settings()

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
        tenant=TenantResponse.model_validate(tenant),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate Refresh Token",
    description=(
        "Obtains a new access/refresh token pair by rotating the existing refresh token. "
        "Enforces automatic token family revocation if reuse of an old token is detected."
    ),
    responses={
        401: {"description": "Invalid, expired, or compromised refresh token"},
        403: {"description": "Account is inactive"},
    },
)
async def refresh_token(
    request: RefreshTokenRequest,
    http_req: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    auth_service = AuthService(db)
    client_ip = get_client_ip(http_req)
    user_agent = http_req.headers.get("user-agent")

    tenant, user, access_token, new_raw_refresh = await auth_service.rotate_refresh_token(
        raw_refresh_token=request.refresh_token,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    settings = get_settings()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_raw_refresh,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
        tenant=TenantResponse.model_validate(tenant),
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout User",
    description="Server-side invalidation of refresh token session.",
)
async def logout(
    request: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    auth_service = AuthService(db)
    await auth_service.logout_user(
        user_id=current_user.id,
        raw_refresh_token=request.refresh_token,
        all_sessions=request.all_sessions,
    )
    return LogoutResponse(
        success=True,
        message="All sessions revoked." if request.all_sessions else "Successfully logged out.",
    )
