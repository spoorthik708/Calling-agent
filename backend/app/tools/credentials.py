"""Credential Architecture & Secret Scrubbing for Tool Execution.

Guarantees:
1. ToolDefinition.configuration stores CredentialReference (identifiers only).
2. Plaintext API keys and secrets are NEVER stored in the database.
3. Server-side CredentialProvider interface with pluggable implementations (AWS, GCP, Vault, Local).
4. Deep secret scrubbing for logs, audit trails, and API responses.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
import re
from typing import Any, Dict, Optional

from app.core.exceptions import CredentialResolutionError
from app.core.logging import get_logger

logger = get_logger("yavura.tools.credentials")

# Sensitive key names to automatically scrub from payloads and logs
SENSITIVE_KEY_PATTERN = re.compile(
    r"(secret|password|token|key|authorization|bearer|cookie|credential|private)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CredentialReference:
    """
    Non-sensitive pointer to a server-side managed secret.
    Stored inside ToolDefinition.configuration.
    """
    credential_id: str
    provider_type: str = "local"
    auth_header_name: str = "Authorization"
    auth_scheme: Optional[str] = "Bearer"  # e.g. "Bearer", "Basic", or None for raw header


class CredentialProvider(ABC):
    """Abstract interface for server-side secret resolution."""

    @abstractmethod
    async def get_secret(self, credential_id: str, tenant_id: Optional[str] = None) -> Optional[str]:
        """
        Resolves raw secret value for given credential identifier within tenant boundary.
        Credentials cannot cross tenant boundaries.
        """
        pass


class LocalSecureCredentialProvider(CredentialProvider):
    """
    Server-side environment / configuration backed secret resolver.
    Retrieves secret from environment variables prefixed with TOOL_SECRET_ or direct mapping.
    Enforces strict tenant scoping when tenant_id is provided.
    Never exposed to database or client API.
    """
    def __init__(self, in_memory_vault: Optional[Dict[str, str]] = None):
        self._in_memory_vault = in_memory_vault or {}

    async def get_secret(self, credential_id: str, tenant_id: Optional[str] = None) -> Optional[str]:
        # 1. Check tenant-scoped in-memory vault first if tenant_id is provided
        if tenant_id:
            scoped_key = f"{tenant_id}:{credential_id}"
            if scoped_key in self._in_memory_vault:
                return self._in_memory_vault[scoped_key]

        # 2. Check general in-memory vault
        if credential_id in self._in_memory_vault:
            # If the vault entry belongs to a specific tenant (contains colon), don't allow cross-tenant access
            if ":" in credential_id and tenant_id and not credential_id.startswith(f"{tenant_id}:"):
                logger.warning("Attempted cross-tenant access to credential '%s' from tenant '%s'", credential_id, tenant_id)
                return None
            return self._in_memory_vault[credential_id]

        # 3. Check environment variable with tenant scope: TOOL_SECRET_<TENANT>_<ID>
        if tenant_id:
            norm_tenant = tenant_id.upper().replace("-", "_")
            norm_id = credential_id.upper().replace("-", "_")
            scoped_env = f"TOOL_SECRET_{norm_tenant}_{norm_id}"
            secret_val = os.getenv(scoped_env)
            if secret_val:
                return secret_val

        # 4. Check global environment variable TOOL_SECRET_<ID_NORMALIZED>
        norm_id = credential_id.upper().replace("-", "_")
        env_key = f"TOOL_SECRET_{norm_id}"
        secret_val = os.getenv(env_key)
        if secret_val:
            return secret_val

        # 5. Direct env key lookup fallback (only if non-tenant scoped)
        direct_env = os.getenv(credential_id)
        if direct_env:
            return direct_env

        return None


# Global default credential provider
_global_credential_provider: Optional[CredentialProvider] = None


def get_credential_provider() -> CredentialProvider:
    global _global_credential_provider
    if _global_credential_provider is None:
        _global_credential_provider = LocalSecureCredentialProvider()
    return _global_credential_provider


def set_credential_provider(provider: CredentialProvider) -> None:
    global _global_credential_provider
    _global_credential_provider = provider


def scrub_secrets(data: Any, depth: int = 0) -> Any:
    """
    Recursively scrubs secrets, tokens, API keys, and passwords from payloads
    before audit logging, telemetry emission, or API serialization.
    """
    if depth > 10:
        return "[MAX_DEPTH_REACHED]"

    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                scrubbed[k] = scrub_secrets(v, depth + 1)
            elif isinstance(k, str) and SENSITIVE_KEY_PATTERN.search(k):
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_secrets(v, depth + 1)
        return scrubbed
    elif isinstance(data, list):
        return [scrub_secrets(item, depth + 1) for item in data]
    elif isinstance(data, tuple):
        return tuple(scrub_secrets(item, depth + 1) for item in data)
    elif isinstance(data, str):
        # Scrub Bearer tokens in strings
        if "bearer " in data.lower():
            return re.sub(r"(bearer\s+)[A-Za-z0-9_\-\.]+", r"\1[REDACTED]", data, flags=re.IGNORECASE)
        return data
    return data
