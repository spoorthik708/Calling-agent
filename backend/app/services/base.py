from typing import Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.context import get_current_tenant_context
from app.core.exceptions import TenantIsolationError


class BaseService:
    """Base class for all business domain services with mandatory tenant awareness."""
    def __init__(self, db: AsyncSession, tenant_id: Optional[uuid.UUID] = None):
        self.db = db
        if tenant_id:
            self.tenant_id = tenant_id
        else:
            context = get_current_tenant_context()
            self.tenant_id = context.tenant_id if context else None

    def require_tenant_id(self) -> uuid.UUID:
        """Ensures that a tenant ID is available or raises TenantIsolationError."""
        if not self.tenant_id:
            raise TenantIsolationError("Service operation requires active tenant boundary.")
        return self.tenant_id
