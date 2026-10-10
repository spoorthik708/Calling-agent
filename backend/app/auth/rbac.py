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

    # Knowledge & RAG permissions
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_CREATE = "knowledge:create"
    KNOWLEDGE_UPDATE = "knowledge:update"
    KNOWLEDGE_DELETE = "knowledge:delete"
    KNOWLEDGE_RETRIEVE = "knowledge:retrieve"

    # Agent permissions (Phase 4)
    AGENTS_READ = "agents:read"
    AGENTS_CREATE = "agents:create"
    AGENTS_UPDATE = "agents:update"
    AGENTS_DELETE = "agents:delete"
    AGENTS_MANAGE_KNOWLEDGE = "agents:manage_knowledge"
    AGENTS_RUN = "agents:run"

    # Conversation permissions (Phase 4)
    CONVERSATIONS_READ = "conversations:read"
    CONVERSATIONS_CREATE = "conversations:create"
    CONVERSATIONS_DELETE = "conversations:delete"

    # Tool & Action permissions (Phase 5)
    TOOLS_READ = "tools:read"
    TOOLS_CREATE = "tools:create"
    TOOLS_UPDATE = "tools:update"
    TOOLS_DELETE = "tools:delete"
    TOOLS_ASSIGN = "tools:assign"
    TOOLS_EXECUTE = "tools:execute"
    TOOLS_READ_EXECUTIONS = "tools:read_executions"

    # Voice Layer permissions (Phase 6)
    # Voice Layer permissions (Phase 6)
    VOICE_READ = "voice:read"
    VOICE_CREATE = "voice:create"
    VOICE_MANAGE = "voice:manage"
    VOICE_INTERRUPT = "voice:interrupt"
    VOICE_END = "voice:end"

    # Telephony Layer permissions (Phase 7)
    TELEPHONY_READ = "telephony:read"
    TELEPHONY_CREATE = "telephony:create"
    TELEPHONY_DISPATCH = "telephony:dispatch"
    TELEPHONY_MANAGE = "telephony:manage"


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
        Permission.KNOWLEDGE_READ,
        Permission.KNOWLEDGE_CREATE,
        Permission.KNOWLEDGE_UPDATE,
        Permission.KNOWLEDGE_DELETE,
        Permission.KNOWLEDGE_RETRIEVE,
        Permission.AGENTS_READ,
        Permission.AGENTS_CREATE,
        Permission.AGENTS_UPDATE,
        Permission.AGENTS_DELETE,
        Permission.AGENTS_MANAGE_KNOWLEDGE,
        Permission.AGENTS_RUN,
        Permission.CONVERSATIONS_READ,
        Permission.CONVERSATIONS_CREATE,
        Permission.CONVERSATIONS_DELETE,
        Permission.TOOLS_READ,
        Permission.TOOLS_CREATE,
        Permission.TOOLS_UPDATE,
        Permission.TOOLS_DELETE,
        Permission.TOOLS_ASSIGN,
        Permission.TOOLS_EXECUTE,
        Permission.TOOLS_READ_EXECUTIONS,
        Permission.VOICE_READ,
        Permission.VOICE_CREATE,
        Permission.VOICE_MANAGE,
        Permission.VOICE_INTERRUPT,
        Permission.VOICE_END,
        Permission.TELEPHONY_READ,
        Permission.TELEPHONY_CREATE,
        Permission.TELEPHONY_DISPATCH,
        Permission.TELEPHONY_MANAGE,
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
        Permission.KNOWLEDGE_READ,
        Permission.KNOWLEDGE_CREATE,
        Permission.KNOWLEDGE_UPDATE,
        Permission.KNOWLEDGE_DELETE,
        Permission.KNOWLEDGE_RETRIEVE,
        Permission.AGENTS_READ,
        Permission.AGENTS_CREATE,
        Permission.AGENTS_UPDATE,
        Permission.AGENTS_DELETE,
        Permission.AGENTS_MANAGE_KNOWLEDGE,
        Permission.AGENTS_RUN,
        Permission.CONVERSATIONS_READ,
        Permission.CONVERSATIONS_CREATE,
        Permission.CONVERSATIONS_DELETE,
        Permission.TOOLS_READ,
        Permission.TOOLS_CREATE,
        Permission.TOOLS_UPDATE,
        Permission.TOOLS_DELETE,
        Permission.TOOLS_ASSIGN,
        Permission.TOOLS_EXECUTE,
        Permission.TOOLS_READ_EXECUTIONS,
        Permission.VOICE_READ,
        Permission.VOICE_CREATE,
        Permission.VOICE_MANAGE,
        Permission.VOICE_INTERRUPT,
        Permission.VOICE_END,
        Permission.TELEPHONY_READ,
        Permission.TELEPHONY_CREATE,
        Permission.TELEPHONY_DISPATCH,
        Permission.TELEPHONY_MANAGE,
    }),
    Role.MEMBER: frozenset({
        Permission.TENANT_READ,
        Permission.PROFILE_READ,
        Permission.PROFILE_UPDATE,
        Permission.KNOWLEDGE_READ,
        Permission.KNOWLEDGE_RETRIEVE,
        Permission.AGENTS_READ,
        Permission.AGENTS_RUN,
        Permission.CONVERSATIONS_READ,
        Permission.CONVERSATIONS_CREATE,
        Permission.TOOLS_READ,
        Permission.TOOLS_READ_EXECUTIONS,
        Permission.VOICE_READ,
        Permission.VOICE_CREATE,
        Permission.VOICE_INTERRUPT,
        Permission.VOICE_END,
        Permission.TELEPHONY_READ,
        Permission.TELEPHONY_CREATE,
        Permission.TELEPHONY_DISPATCH,
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
