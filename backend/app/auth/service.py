from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import uuid
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import RefreshToken
from app.auth.password import validate_password, PasswordPolicyError
from app.auth.rbac import Role
from app.auth.schemas import TenantRegisterRequest
from app.core.config import get_settings
from app.core.exceptions import (
    PasswordPolicyViolationError,
    TenantIsolationError,
)
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token_pair,
    get_password_hash,
    hash_token,
    verify_password,
)
from app.models.audit import AuditLog
from app.tenants.models import Tenant
from app.users.models import User

logger = get_logger("yavura.auth")

# Fixed, safe, static dummy bcrypt hash for anti-timing analysis when a user does not exist.
# Prevents user-enumeration timing side channels without generating hashes per request.
STATIC_DUMMY_BCRYPT_HASH = "$2b$12$69g0J5UbR69J7jbW8agpLuifbi//CcE5kwMHKJjckUXybrNuD7yHu"


class AuthService:
    """Production authentication service managing onboarding, credentials, tokens, and sessions."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def register_tenant_and_owner(
        self,
        request: TenantRegisterRequest,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[Tenant, User, str, str]:
        """
        Atomically registers a new Tenant, its initial Owner user, and session tokens.
        Rolls back completely if any step fails.
        """
        # 1. Enforce password policy
        try:
            validate_password(request.password)
        except PasswordPolicyError as e:
            raise PasswordPolicyViolationError(str(e))

        # 2. Normalize identifiers
        normalized_email = request.email.strip().lower()
        normalized_slug = request.tenant_slug.strip().lower()

        # 3. Check tenant slug uniqueness
        slug_check = await self.db.execute(select(Tenant).where(Tenant.slug == normalized_slug))
        if slug_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A company with this identifier is already registered.",
            )

        # 4. Hash password
        password_hash = get_password_hash(request.password)

        try:
            # 5. Create Tenant entity
            tenant = Tenant(
                name=request.tenant_name.strip(),
                slug=normalized_slug,
                status="active",
                is_active=True,
                tier="standard",
            )
            self.db.add(tenant)
            await self.db.flush()

            # 6. Create Initial User as OWNER (forced server-side)
            owner_user = User(
                tenant_id=tenant.id,
                email=normalized_email,
                hashed_password=password_hash,
                first_name=request.first_name.strip() if request.first_name else None,
                last_name=request.last_name.strip() if request.last_name else None,
                role=Role.OWNER.value,
                status="active",
                is_active=True,
            )
            self.db.add(owner_user)
            await self.db.flush()

            # 7. Audit log creation
            audit = AuditLog(
                tenant_id=tenant.id,
                actor_id=owner_user.id,
                action="tenant.registered",
                resource_type="tenant",
                resource_id=str(tenant.id),
                details={
                    "tenant_slug": tenant.slug,
                    "owner_email": owner_user.email,
                    "ip_address": client_ip,
                },
            )
            self.db.add(audit)

            # 8. Create initial refresh token session
            raw_refresh, token_hash = create_refresh_token_pair()
            refresh_record = RefreshToken(
                tenant_id=tenant.id,
                user_id=owner_user.id,
                family_id=uuid.uuid4(),
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(days=self.settings.refresh_token_expire_days),
                user_agent=user_agent,
                ip_address=client_ip,
            )
            self.db.add(refresh_record)

            await self.db.commit()
            await self.db.refresh(tenant)
            await self.db.refresh(owner_user)

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Tenant registration failed, transaction rolled back: {str(e)}", exc_info=True)
            raise

        # 9. Generate access token
        access_token = create_access_token(
            subject=owner_user.id,
            tenant_id=tenant.id,
            role=owner_user.role,
        )

        return tenant, owner_user, access_token, raw_refresh

    async def authenticate_user(
        self,
        email: str,
        password: str,
        tenant_slug: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[Tenant, User, str, str]:
        """
        Authenticates a user via email and password with anti-enumeration security.
        """
        normalized_email = email.strip().lower()

        # Query user with tenant
        query = select(User).options(selectinload(User.tenant)).where(User.email == normalized_email)
        if tenant_slug:
            query = query.join(Tenant).where(Tenant.slug == tenant_slug.strip().lower())

        result = await self.db.execute(query)
        users = result.scalars().all()

        # Anti-enumeration: Generic failure message regardless of whether user exists
        generic_auth_failure = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

        if not users:
            # SEC-05: Timing side channel mitigation - run static dummy bcrypt verification
            verify_password(password, STATIC_DUMMY_BCRYPT_HASH)
            raise generic_auth_failure

        if len(users) > 1 and not tenant_slug:
            # Ambiguous account across multiple tenants: ask for tenant slug without leaking passwords
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multiple accounts found for this email. Please specify your company identifier (tenant_slug).",
            )

        user = users[0]
        tenant = user.tenant

        # Verify password
        if not verify_password(password, user.hashed_password):
            raise generic_auth_failure

        # Verify user and tenant lifecycle status
        if user.status != "active" or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive or suspended.",
            )

        if tenant.status != "active" or not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company account is inactive or suspended.",
            )

        # Update last login time
        user.last_login_at = datetime.now(timezone.utc)

        # Generate refresh token
        raw_refresh, token_hash = create_refresh_token_pair()
        refresh_record = RefreshToken(
            tenant_id=tenant.id,
            user_id=user.id,
            family_id=uuid.uuid4(),
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=self.settings.refresh_token_expire_days),
            user_agent=user_agent,
            ip_address=client_ip,
        )
        self.db.add(refresh_record)

        # Log audit
        audit = AuditLog(
            tenant_id=tenant.id,
            actor_id=user.id,
            action="user.login",
            resource_type="session",
            resource_id=str(refresh_record.id),
            details={"ip_address": client_ip},
        )
        self.db.add(audit)

        await self.db.commit()
        await self.db.refresh(user)

        # Generate access token
        access_token = create_access_token(
            subject=user.id,
            tenant_id=tenant.id,
            role=user.role,
        )

        return tenant, user, access_token, raw_refresh

    async def rotate_refresh_token(
        self,
        raw_refresh_token: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[Tenant, User, str, str]:
        """
        Rotates refresh token. Implements strict reuse detection:
        If an already rotated or revoked token is reused, revokes the entire token family.
        """
        token_hash = hash_token(raw_refresh_token)

        # SEC-02: Row-level locking for PostgreSQL concurrency safety
        # Locks the refresh token row during rotation to serialize concurrent refresh requests.
        # If two simultaneous requests hit this section, the second request blocks until the first
        # commits, then reads the revoked token and triggers token compromise detection.
        # On SQLite, with_for_update() is a safe no-op.
        stmt = (
            select(RefreshToken)
            .options(selectinload(RefreshToken.user).selectinload(User.tenant))
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
            )

        # REUSE DETECTION: If token was already revoked or replaced, treat as potential compromise
        if token_record.revoked_at is not None or token_record.replaced_by_token_id is not None:
            logger.warning(
                f"POTENTIAL COMPROMISE: Revoked refresh token reuse detected for family {token_record.family_id}"
            )
            # Revoke entire token family
            await self.db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == token_record.family_id)
                .values(revoked_at=datetime.now(timezone.utc))
            )
            # Record security audit log
            audit = AuditLog(
                tenant_id=token_record.tenant_id,
                actor_id=token_record.user_id,
                action="security.token_compromise_detected",
                resource_type="token_family",
                resource_id=str(token_record.family_id),
                details={"ip_address": client_ip, "user_agent": user_agent},
            )
            self.db.add(audit)
            await self.db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Compromised refresh token session detected. All associated sessions have been revoked.",
            )

        # Check expiration
        now = datetime.now(timezone.utc)
        if token_record.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has expired.",
            )

        user = token_record.user
        tenant = user.tenant

        # Check active status
        if not user.is_active or user.status != "active" or not tenant.is_active or tenant.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive or suspended.",
            )

        # Revoke the current token
        token_record.revoked_at = now

        # Create new rotated token in the same family
        new_raw_token, new_token_hash = create_refresh_token_pair()
        new_token_record = RefreshToken(
            tenant_id=tenant.id,
            user_id=user.id,
            family_id=token_record.family_id,
            token_hash=new_token_hash,
            expires_at=now + timedelta(days=self.settings.refresh_token_expire_days),
            user_agent=user_agent,
            ip_address=client_ip,
        )
        self.db.add(new_token_record)
        await self.db.flush()

        # Link previous token to the replacement
        token_record.replaced_by_token_id = new_token_record.id

        await self.db.commit()

        # Issue new access token
        new_access_token = create_access_token(
            subject=user.id,
            tenant_id=tenant.id,
            role=user.role,
        )

        return tenant, user, new_access_token, new_raw_token

    async def logout_user(
        self,
        user_id: uuid.UUID,
        raw_refresh_token: Optional[str] = None,
        all_sessions: bool = False,
    ) -> None:
        """Revokes server-side refresh tokens for single session or all sessions."""
        now = datetime.now(timezone.utc)
        if all_sessions:
            await self.db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        elif raw_refresh_token:
            token_hash = hash_token(raw_refresh_token)
            # SEC-03: Scope logout by both token_hash AND authenticated user_id
            # Ensures an authenticated user can never revoke another user's session
            await self.db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.user_id == user_id,
                )
                .values(revoked_at=now)
            )
        await self.db.commit()
