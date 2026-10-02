from typing import Any, Sequence, TypeVar, Union
import uuid
from sqlalchemy import Select
from app.auth.context import get_current_tenant_context
from app.core.exceptions import TenantIsolationError
from app.database.base import TenantAwareModel

T = TypeVar("T", bound=TenantAwareModel)


def enforce_tenant_filter(query: Select[Any], model: type[T], tenant_id: Union[uuid.UUID, str]) -> Select[Any]:
    """
    Guarantees that a SQLAlchemy select query strictly filters by the given tenant_id.
    Prevents cross-tenant data leakage.
    """
    tid = uuid.UUID(str(tenant_id))
    return query.where(model.tenant_id == tid)


def enforce_current_tenant_filter(query: Select[Any], model: type[T]) -> Select[Any]:
    """
    Applies tenant isolation filter based on active request TenantContext.
    Raises TenantIsolationError if no active tenant context is set.
    """
    context = get_current_tenant_context()
    if not context or not context.tenant_id:
        raise TenantIsolationError("Operation attempted without active tenant context.")
    return enforce_tenant_filter(query, model, context.tenant_id)


def assert_entity_tenant(entity: TenantAwareModel, expected_tenant_id: Union[uuid.UUID, str]) -> None:
    """Verifies that an entity instance belongs to the expected tenant."""
    if str(entity.tenant_id) != str(expected_tenant_id):
        raise TenantIsolationError(
            f"Cross-tenant access violation: resource belongs to {entity.tenant_id}, access attempted by {expected_tenant_id}"
        )
