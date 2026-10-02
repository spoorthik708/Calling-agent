from enum import Enum
from typing import Dict, FrozenSet, Set


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Permission(str, Enum):
    # Tenant permissions
    TENANT_READ = "tenant:read"
    TENANT_UPDATE = "tenant:update"

    # User management permissions
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DISABLE = "users:disable"

    # Role & Security permissions
    ROLES_READ = "roles:read"
    ROLES_MANAGE = "roles:manage"

    # Profile self-management permissions
    PROFILE_READ = "profile:read"
    PROFILE_UPDATE = "profile:update"


# Definitive Role -> Permissions Mapping
ROLE_PERMISSIONS: Dict[Role, FrozenSet[Permission]] = {
    Role.OWNER: frozenset({
        Permission.TENANT_READ,
        Permission.TENANT_UPDATE,
        Permission.USERS_READ,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        Permission.USERS_DISABLE,
        Permission.ROLES_READ,
        Permission.ROLES_MANAGE,
        Permission.PROFILE_READ,
        Permission.PROFILE_UPDATE,
    }),
    Role.ADMIN: frozenset({
        Permission.TENANT_READ,
        Permission.USERS_READ,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        Permission.USERS_DISABLE,
        Permission.ROLES_READ,
        Permission.PROFILE_READ,
        Permission.PROFILE_UPDATE,
        # Note: ADMIN does NOT have TENANT_UPDATE or ROLES_MANAGE
    }),
    Role.MEMBER: frozenset({
        Permission.TENANT_READ,
        Permission.PROFILE_READ,
        Permission.PROFILE_UPDATE,
    }),
}


def get_role_permissions(role_str: str) -> Set[str]:
    """Returns the set of permission strings granted to a role."""
    try:
        role = Role(role_str.lower())
        return {perm.value for perm in ROLE_PERMISSIONS.get(role, frozenset())}
    except ValueError:
        return set()


def has_permission(role_str: str, permission_str: str) -> bool:
    """Verifies whether a role possesses a specific permission."""
    return permission_str in get_role_permissions(role_str)


def can_manage_target_user(actor_role_str: str, target_role_str: str) -> bool:
    """
    SECTION 16: OWNER PROTECTION
    Enforces rules on which roles can modify/disable/update another user:
    - OWNER can manage any user.
    - ADMIN can only manage MEMBER. ADMIN cannot modify/disable another ADMIN or an OWNER.
    - MEMBER cannot manage any other user.
    """
    try:
        actor_role = Role(actor_role_str.lower())
        target_role = Role(target_role_str.lower())
    except ValueError:
        return False

    if actor_role == Role.OWNER:
        return True
    elif actor_role == Role.ADMIN:
        # Admin can only manage members, never owners or other admins
        return target_role == Role.MEMBER
    return False
