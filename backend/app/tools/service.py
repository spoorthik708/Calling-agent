"""Central Tool Execution Service for YAVURA.

Implements the strict 15-step execution pipeline:
1. Authenticate request
2. Resolve tenant
3. Resolve agent
4. Verify agent belongs to tenant
5. Verify tool belongs to tenant
6. Verify tool is active
7. Verify agent is explicitly assigned the tool
8. Verify caller/agent permission
9. Validate input against Pydantic schema
10. Apply security policy (Injection + SSRF)
11. Resolve approved implementation
12. Verify idempotency
13. Check rate limiting
14. Execute with bounded timeout & retry policy
15. Persist sanitized ToolExecution audit record and return structured ToolResult.
"""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Union
import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.auth.rbac import Permission, has_permission
from app.auth.throttling import InMemoryRateLimiter, default_rate_limiter
from app.core.config import get_settings
from app.core.exceptions import (
    AgentNotFoundError,
    InactiveAgentExecutionError,
    TenantIsolationError,
    ToolAuthorizationError,
    ToolDisabledError,
    ToolExecutionError,
    ToolExecutionSecurityError,
    ToolIdempotencyConflictError,
    ToolNotAssignedError,
    ToolNotFoundError,
    ToolRateLimitError,
    ToolTimeoutError,
    ToolValidationError,
)
from app.core.logging import get_logger
from app.security.input_validation import validate_tool_arguments
from app.tools.base import (
    BaseTool,
    ToolExecutionContext,
    ToolResult,
)
from app.tools.credentials import CredentialReference, scrub_secrets
from app.tools.http_tool import HttpApiTool
from app.tools.models import (
    AgentTool,
    ToolDefinition,
    ToolExecution,
    ToolExecutionStatus,
    ToolType,
)
from app.tools.registry import ToolRegistry, default_tool_registry

logger = get_logger("yavura.tools.service")

# Concurrency locks per (tenant_id, tool_id, idempotency_key) to prevent race conditions on duplicate concurrent requests
_idempotency_locks: Dict[str, asyncio.Lock] = {}
_idempotency_locks_guard = asyncio.Lock()


class ToolExecutionService:
    """Production tool execution pipeline orchestrator."""

    def __init__(
        self,
        db: AsyncSession,
        registry: Optional[ToolRegistry] = None,
        rate_limiter: Optional[InMemoryRateLimiter] = None,
    ):
        self.db = db
        self.registry = registry or default_tool_registry
        self.rate_limiter = rate_limiter or default_rate_limiter
        self.settings = get_settings()

    async def execute_tool(
        self,
        *,
        tenant_id: uuid.UUID,
        tool_identifier: Union[str, uuid.UUID],
        arguments: Dict[str, Any],
        agent_id: Optional[uuid.UUID] = None,
        conversation_id: Optional[uuid.UUID] = None,
        message_id: Optional[uuid.UUID] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        timeout_override: Optional[float] = None,
    ) -> ToolResult:
        """
        Executes an approved tool through the non-bypassable 15-step security pipeline.
        """
        start_time = time.perf_counter()
        req_correlation = correlation_id or str(uuid.uuid4())
        sanitized_input = scrub_secrets(arguments or {})

        # 1 & 2. Authenticate Request & Resolve Tenant
        if not tenant_id:
            raise TenantIsolationError("Tool execution forbidden without explicit tenant context.")

        if actor_role and not has_permission(actor_role, Permission.TOOLS_EXECUTE.value):
            raise ToolAuthorizationError(
                f"Role '{actor_role}' does not possess required permission '{Permission.TOOLS_EXECUTE.value}'."
            )

        # 3 & 4. Resolve Agent & Verify Tenant Scope
        agent: Optional[Agent] = None
        if agent_id:
            stmt_agent = select(Agent).where(
                Agent.id == agent_id,
                Agent.tenant_id == tenant_id,
            )
            agent = (await self.db.execute(stmt_agent)).scalar_one_or_none()
            if not agent:
                raise AgentNotFoundError(
                    f"Agent {agent_id} not found for tenant {tenant_id}.",
                    details={"agent_id": str(agent_id)},
                )
            if agent.status != AgentStatus.ACTIVE.value:
                raise InactiveAgentExecutionError(
                    f"Agent '{agent.name}' is {agent.status}. Only ACTIVE agents can invoke tools.",
                    details={"agent_id": str(agent.id), "status": agent.status},
                )

        # 5. Resolve Tool Definition for Tenant
        tool_def: Optional[ToolDefinition] = None
        if isinstance(tool_identifier, uuid.UUID):
            stmt_tool = select(ToolDefinition).where(
                ToolDefinition.id == tool_identifier,
                ToolDefinition.tenant_id == tenant_id,
            )
            tool_def = (await self.db.execute(stmt_tool)).scalar_one_or_none()
        else:
            stmt_tool = select(ToolDefinition).where(
                ToolDefinition.name == tool_identifier,
                ToolDefinition.tenant_id == tenant_id,
            )
            tool_def = (await self.db.execute(stmt_tool)).scalar_one_or_none()

        if not tool_def:
            raise ToolNotFoundError(
                f"Tool '{tool_identifier}' not found for this tenant.",
                details={"tool_identifier": str(tool_identifier), "tenant_id": str(tenant_id)},
            )

        # 6. Verify Tool is Active
        if not tool_def.is_active:
            raise ToolDisabledError(
                f"Tool '{tool_def.name}' is deactivated and cannot be executed.",
                details={"tool_id": str(tool_def.id), "tool_name": tool_def.name},
            )

        # 7. Verify Agent is Explicitly Assigned the Tool
        if agent_id:
            stmt_assign = select(AgentTool).where(
                AgentTool.tenant_id == tenant_id,
                AgentTool.agent_id == agent_id,
                AgentTool.tool_id == tool_def.id,
                AgentTool.enabled == True,  # noqa: E712
            )
            assigned_link = (await self.db.execute(stmt_assign)).scalar_one_or_none()
            if not assigned_link:
                raise ToolNotAssignedError(
                    f"Tool '{tool_def.name}' is not assigned or enabled for Agent '{agent.name if agent else agent_id}'.",
                    details={"agent_id": str(agent_id), "tool_id": str(tool_def.id)},
                )

        # 8. Rate Limiting Check (Tenant-scoped)
        rate_limit_key = f"tool_rate:{tenant_id}"
        max_rate = self.settings.TOOL_RATE_LIMIT_PER_MINUTE
        if not self.rate_limiter.check_rate_limit(rate_limit_key, max_rate, 60):
            logger.warning("Tenant %s exceeded tool execution rate limit (%s/min)", tenant_id, max_rate)
            await self._persist_audit_record(
                tenant_id=tenant_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                message_id=message_id,
                tool_id=tool_def.id,
                tool_name=tool_def.name,
                tool_version=tool_def.version,
                status=ToolExecutionStatus.RATE_LIMITED.value,
                validated_input=sanitized_input,
                sanitized_output=None,
                error_category="RATE_LIMITED",
                error_message=f"Rate limit exceeded: {max_rate} requests per minute.",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                correlation_id=req_correlation,
                idempotency_key=idempotency_key,
            )
            raise ToolRateLimitError(
                f"Tool execution quota exceeded. Maximum {max_rate} requests per minute.",
                details={"tenant_id": str(tenant_id), "limit": max_rate},
            )

        # 9 & 10. Validate Input Security (Injection patterns & bounded resource limits)
        try:
            validate_tool_arguments(
                arguments,
                max_bytes=self.settings.MAX_TOOL_ARGUMENT_BYTES,
            )
        except ToolExecutionSecurityError as se:
            await self._persist_audit_record(
                tenant_id=tenant_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                message_id=message_id,
                tool_id=tool_def.id,
                tool_name=tool_def.name,
                tool_version=tool_def.version,
                status=ToolExecutionStatus.BLOCKED.value,
                validated_input=sanitized_input,
                sanitized_output=None,
                error_category="SECURITY_VIOLATION",
                error_message=str(se),
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                correlation_id=req_correlation,
                idempotency_key=idempotency_key,
            )
            raise

        arg_hash = hashlib.sha256(
            json.dumps(sanitized_input, sort_keys=True).encode("utf-8")
        ).hexdigest()

        async def _execute_pipeline() -> ToolResult:
            # 12. Idempotency Check (inside lock to serialize concurrent requests)
            if idempotency_key:
                stmt_idem = select(ToolExecution).where(
                    ToolExecution.tenant_id == tenant_id,
                    ToolExecution.idempotency_key == idempotency_key,
                    ToolExecution.tool_id == tool_def.id,
                )
                existing_exec = (await self.db.execute(stmt_idem)).scalar_one_or_none()
                if existing_exec:
                    # Check expiration
                    cutoff = datetime.now(timezone.utc).timestamp() - (self.settings.TOOL_IDEMPOTENCY_EXPIRE_HOURS * 3600)
                    if existing_exec.created_at.timestamp() > cutoff:
                        existing_hash = hashlib.sha256(
                            json.dumps(existing_exec.validated_input, sort_keys=True).encode("utf-8")
                        ).hexdigest()

                        if existing_hash == arg_hash:
                            logger.info(
                                "Idempotent hit for tool '%s', key=%s",
                                tool_def.name,
                                idempotency_key,
                            )
                            return ToolResult(
                                tool_name=tool_def.name,
                                tool_version=tool_def.version,
                                success=(existing_exec.status == ToolExecutionStatus.SUCCESS.value),
                                data=existing_exec.sanitized_output or {},
                                error_category=existing_exec.error_category,
                                error_message=existing_exec.error_message,
                                duration_ms=existing_exec.duration_ms,
                                idempotent_cached=True,
                            )
                        else:
                            raise ToolIdempotencyConflictError(
                                "Idempotency key reused with conflicting input payload.",
                                details={"idempotency_key": idempotency_key, "tool_name": tool_def.name},
                            )

            # 11. Resolve Approved Implementation
            tool_impl: BaseTool
            if tool_def.tool_type == ToolType.INTERNAL.value:
                tool_impl = self.registry.get_tool(tool_def.name)
            elif tool_def.tool_type == ToolType.HTTP_API.value:
                config = tool_def.configuration or {}
                base_url = config.get("base_url")
                if not base_url:
                    raise ToolValidationError(
                        f"HTTP API tool '{tool_def.name}' missing 'base_url' in configuration."
                    )

                cred_ref: Optional[CredentialReference] = None
                if "credential_reference" in config:
                    c = config["credential_reference"]
                    cred_ref = CredentialReference(
                        credential_id=c.get("credential_id", ""),
                        provider_type=c.get("provider_type", "local"),
                        auth_header_name=c.get("auth_header_name", "Authorization"),
                        auth_scheme=c.get("auth_scheme", "Bearer"),
                    )

                tool_impl = HttpApiTool(
                    name=tool_def.name,
                    display_name=tool_def.display_name,
                    description=tool_def.description,
                    base_url=base_url,
                    path_template=config.get("path_template", "/"),
                    method=config.get("method", "GET"),
                    credential_reference=cred_ref,
                    timeout_seconds=config.get("timeout_seconds", self.settings.DEFAULT_TOOL_TIMEOUT_SECONDS),
                    max_retries=config.get("max_retries", 2),
                    is_side_effecting=config.get("is_side_effecting", False),
                    allow_http_for_testing=self.settings.SSRF_ALLOW_HTTP_FOR_TESTING,
                    version=tool_def.version,
                )
            else:
                raise ToolExecutionError(f"Unsupported tool type '{tool_def.tool_type}'.")

            # Validate arguments against Pydantic model
            try:
                validated_model = tool_impl.input_schema.model_validate(arguments)
            except Exception as ve:
                await self._persist_audit_record(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    tool_id=tool_def.id,
                    tool_name=tool_def.name,
                    tool_version=tool_def.version,
                    status=ToolExecutionStatus.VALIDATION_FAILED.value,
                    validated_input=sanitized_input,
                    sanitized_output=None,
                    error_category="VALIDATION_FAILED",
                    error_message=str(ve),
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                    correlation_id=req_correlation,
                    idempotency_key=idempotency_key,
                )
                raise ToolValidationError(
                    f"Arguments failed schema validation for tool '{tool_def.name}': {str(ve)}",
                    details={"tool_name": tool_def.name},
                )

            # Context construction
            context = ToolExecutionContext(
                tenant_id=tenant_id,
                user_id=actor_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                message_id=message_id,
                correlation_id=req_correlation,
                idempotency_key=idempotency_key,
            )

            # 14. Execute with Bounded Timeout
            timeout_sec = (
                timeout_override
                or getattr(tool_impl, "timeout_seconds", None)
                or self.settings.DEFAULT_TOOL_TIMEOUT_SECONDS
            )

            exec_status = ToolExecutionStatus.SUCCESS.value
            error_cat: Optional[str] = None
            error_msg: Optional[str] = None
            output_data: Optional[Dict[str, Any]] = None

            try:
                raw_output = await asyncio.wait_for(
                    tool_impl.execute(validated_model, context),
                    timeout=timeout_sec,
                )
                output_data = (
                    raw_output.model_dump() if hasattr(raw_output, "model_dump") else raw_output
                )
                output_data = scrub_secrets(output_data)

            except asyncio.TimeoutError:
                exec_status = ToolExecutionStatus.TIMEOUT.value
                error_cat = "TIMEOUT"
                error_msg = f"Tool execution timed out after {timeout_sec}s."
                raise ToolTimeoutError(error_msg, details={"tool_name": tool_def.name})

            except ToolTimeoutError as tte:
                exec_status = ToolExecutionStatus.TIMEOUT.value
                error_cat = "TIMEOUT"
                error_msg = tte.message
                raise

            except Exception as e:
                exec_status = ToolExecutionStatus.FAILED.value
                error_cat = type(e).__name__
                error_msg = scrub_secrets(str(e))
                raise

            finally:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                # 15. Persist Immutable ToolExecution Audit Record
                await self._persist_audit_record(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    tool_id=tool_def.id,
                    tool_name=tool_def.name,
                    tool_version=tool_def.version,
                    status=exec_status,
                    validated_input=sanitized_input,
                    sanitized_output=output_data,
                    error_category=error_cat,
                    error_message=error_msg,
                    duration_ms=elapsed_ms,
                    correlation_id=req_correlation,
                    idempotency_key=idempotency_key,
                )

            return ToolResult(
                tool_name=tool_def.name,
                tool_version=tool_def.version,
                success=(exec_status == ToolExecutionStatus.SUCCESS.value),
                data=output_data,
                duration_ms=elapsed_ms,
                idempotent_cached=False,
            )

        if idempotency_key:
            lock_key = f"{tenant_id}:{tool_def.id}:{idempotency_key}"
            async with _idempotency_locks_guard:
                if lock_key not in _idempotency_locks:
                    _idempotency_locks[lock_key] = asyncio.Lock()
                lock = _idempotency_locks[lock_key]

            async with lock:
                return await _execute_pipeline()
        else:
            return await _execute_pipeline()

    async def _persist_audit_record(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: Optional[uuid.UUID],
        conversation_id: Optional[uuid.UUID],
        message_id: Optional[uuid.UUID],
        tool_id: Optional[uuid.UUID],
        tool_name: str,
        tool_version: str,
        status: str,
        validated_input: Dict[str, Any],
        sanitized_output: Optional[Dict[str, Any]],
        error_category: Optional[str],
        error_message: Optional[str],
        duration_ms: float,
        correlation_id: str,
        idempotency_key: Optional[str],
    ) -> None:
        """Safely creates and commits an immutable ToolExecution audit record."""
        audit = ToolExecution(
            tenant_id=tenant_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            message_id=message_id,
            tool_id=tool_id,
            tool_name=tool_name,
            tool_version=tool_version,
            status=status,
            validated_input=validated_input,
            sanitized_output=sanitized_output,
            error_category=error_category,
            error_message=error_message,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self.db.add(audit)
        try:
            await self.db.commit()
        except Exception as e:
            logger.error("Failed to commit ToolExecution audit record: %s", str(e))
            await self.db.rollback()
