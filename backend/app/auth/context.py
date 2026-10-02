from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional
import uuid

@dataclass
class TenantContext:
    """Holds active tenant context throughout the async execution chain."""
    tenant_id: uuid.UUID
    name: str
    slug: str
    is_active: bool = True


@dataclass
class UserContext:
    """Holds active authenticated user context throughout the async execution chain."""
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: str
    is_active: bool = True


# Context variables isolated to the current asynchronous task execution context
_current_tenant_context: ContextVar[Optional[TenantContext]] = ContextVar("current_tenant_context", default=None)
_current_user_context: ContextVar[Optional[UserContext]] = ContextVar("current_user_context", default=None)


def get_current_tenant_context() -> Optional[TenantContext]:
    """Retrieves the active tenant context for the current request task."""
    return _current_tenant_context.get()


def set_current_tenant_context(context: TenantContext) -> None:
    """Sets the active tenant context for the current request task."""
    _current_tenant_context.set(context)


def clear_current_tenant_context() -> None:
    """Clears tenant context at request boundary."""
    _current_tenant_context.set(None)


def get_current_user_context() -> Optional[UserContext]:
    """Retrieves the active user context for the current request task."""
    return _current_user_context.get()


def set_current_user_context(context: UserContext) -> None:
    """Sets the active user context for the current request task."""
    _current_user_context.set(context)


def clear_current_user_context() -> None:
    """Clears user context at request boundary."""
    _current_user_context.set(None)
