from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.models import Agent
from app.auth.dependencies import require_permission
from app.auth.rbac import Permission
from app.core.exceptions import (
    AgentNotFoundError,
    EntityNotFoundError,
    TenantIsolationError,
    ToolNotFoundError,
    http_exception_from_domain,
)
from app.core.logging import get_logger
from app.database.session import get_db
from app.models.audit import AuditLog
from app.tools.credentials import scrub_secrets
from app.tools.models import AgentTool, ToolDefinition, ToolExecution
from app.tools.schemas import (
    AgentToolAssignRequest,
    AgentToolResponse,
    ToolDefinitionCreateRequest,
    ToolDefinitionResponse,
    ToolDefinitionUpdateRequest,
    ToolDirectExecuteRequest,
    ToolExecutionResponse,
)
from app.tools.service import ToolExecutionService
from app.users.models import User

logger = get_logger("yavura.tools.api")

router = APIRouter(tags=["AI Tools & Actions"])


# ==========================================
# Tool Definitions CRUD
# ==========================================

@router.post(
    "/tools",
    response_model=ToolDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Tool Definition",
    description="Creates a new approved business capability/tool for the tenant.",
)
async def create_tool(
    request: ToolDefinitionCreateRequest,
    current_user: User = Depends(require_permission(Permission.TOOLS_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> ToolDefinitionResponse:
    # Check duplicate tool name within tenant
    stmt = select(ToolDefinition).where(
        ToolDefinition.tenant_id == current_user.tenant_id,
        ToolDefinition.name == request.name,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tool with name '{request.name}' already exists in your organization.",
        )

    # Sanitize configuration (No plaintext secrets)
    clean_config = scrub_secrets(request.configuration or {})

    tool = ToolDefinition(
        tenant_id=current_user.tenant_id,
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        tool_type=request.tool_type.value,
        version=request.version,
        input_schema=request.input_schema,
        output_schema=request.output_schema,
        configuration=clean_config,
        is_active=request.is_active,
    )
    db.add(tool)

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="tool.created",
        resource_type="tool_definition",
        resource_id=str(tool.id),
        details={"name": tool.name, "tool_type": tool.tool_type},
    )
    db.add(audit)

    await db.commit()
    await db.refresh(tool)
    return ToolDefinitionResponse.model_validate(tool)


@router.get(
    "/tools",
    response_model=List[ToolDefinitionResponse],
    summary="List Tool Definitions",
    description="Lists all approved tool definitions for the authenticated tenant.",
)
async def list_tools(
    is_active: Optional[bool] = None,
    current_user: User = Depends(require_permission(Permission.TOOLS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[ToolDefinitionResponse]:
    stmt = select(ToolDefinition).where(
        ToolDefinition.tenant_id == current_user.tenant_id
    )
    if is_active is not None:
        stmt = stmt.where(ToolDefinition.is_active == is_active)

    stmt = stmt.order_by(ToolDefinition.name.asc())
    tools = (await db.execute(stmt)).scalars().all()
    return [ToolDefinitionResponse.model_validate(t) for t in tools]


@router.get(
    "/tools/{tool_id}",
    response_model=ToolDefinitionResponse,
    summary="Get Tool Definition",
    description="Retrieves a specific tool definition by ID within the tenant.",
)
async def get_tool(
    tool_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TOOLS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> ToolDefinitionResponse:
    stmt = select(ToolDefinition).where(
        ToolDefinition.id == tool_id,
        ToolDefinition.tenant_id == current_user.tenant_id,
    )
    tool = (await db.execute(stmt)).scalar_one_or_none()
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found in your organization.",
        )
    return ToolDefinitionResponse.model_validate(tool)


@router.patch(
    "/tools/{tool_id}",
    response_model=ToolDefinitionResponse,
    summary="Update Tool Definition",
    description="Updates tool metadata, schemas, or status within the tenant.",
)
async def update_tool(
    tool_id: uuid.UUID,
    request: ToolDefinitionUpdateRequest,
    current_user: User = Depends(require_permission(Permission.TOOLS_UPDATE.value)),
    db: AsyncSession = Depends(get_db),
) -> ToolDefinitionResponse:
    stmt = select(ToolDefinition).where(
        ToolDefinition.id == tool_id,
        ToolDefinition.tenant_id == current_user.tenant_id,
    )
    tool = (await db.execute(stmt)).scalar_one_or_none()
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found in your organization.",
        )

    if request.display_name is not None:
        tool.display_name = request.display_name
    if request.description is not None:
        tool.description = request.description
    if request.input_schema is not None:
        tool.input_schema = request.input_schema
    if request.output_schema is not None:
        tool.output_schema = request.output_schema
    if request.configuration is not None:
        tool.configuration = scrub_secrets(request.configuration)
    if request.is_active is not None:
        tool.is_active = request.is_active

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="tool.updated",
        resource_type="tool_definition",
        resource_id=str(tool.id),
        details={"name": tool.name, "is_active": tool.is_active},
    )
    db.add(audit)

    await db.commit()
    await db.refresh(tool)
    return ToolDefinitionResponse.model_validate(tool)


@router.delete(
    "/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Tool Definition",
    description="Deletes a tool definition and its assignments within the tenant.",
)
async def delete_tool(
    tool_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TOOLS_DELETE.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = select(ToolDefinition).where(
        ToolDefinition.id == tool_id,
        ToolDefinition.tenant_id == current_user.tenant_id,
    )
    tool = (await db.execute(stmt)).scalar_one_or_none()
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found in your organization.",
        )

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="tool.deleted",
        resource_type="tool_definition",
        resource_id=str(tool.id),
        details={"name": tool.name},
    )
    db.add(audit)
    await db.delete(tool)
    await db.commit()


# ==========================================
# Agent Tool Assignments
# ==========================================

@router.post(
    "/agents/{agent_id}/tools",
    response_model=AgentToolResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign Tool to Agent",
    description="Explicitly grants an agent permission to invoke a tool.",
)
async def assign_tool_to_agent(
    agent_id: uuid.UUID,
    request: AgentToolAssignRequest,
    current_user: User = Depends(require_permission(Permission.TOOLS_ASSIGN.value)),
    db: AsyncSession = Depends(get_db),
) -> AgentToolResponse:
    # 1. Verify agent belongs to tenant
    stmt_agent = select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt_agent)).scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found in your organization.",
        )

    # 2. Verify tool belongs to tenant
    stmt_tool = select(ToolDefinition).where(
        ToolDefinition.id == request.tool_id,
        ToolDefinition.tenant_id == current_user.tenant_id,
    )
    tool = (await db.execute(stmt_tool)).scalar_one_or_none()
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {request.tool_id} not found in your organization.",
        )

    # 3. Check duplicate assignment
    stmt_link = select(AgentTool).where(
        AgentTool.agent_id == agent_id,
        AgentTool.tool_id == request.tool_id,
        AgentTool.tenant_id == current_user.tenant_id,
    )
    existing_link = (await db.execute(stmt_link)).scalar_one_or_none()
    if existing_link:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tool '{tool.name}' is already assigned to agent '{agent.name}'.",
        )

    assignment = AgentTool(
        tenant_id=current_user.tenant_id,
        agent_id=agent_id,
        tool_id=request.tool_id,
        enabled=request.enabled,
    )
    db.add(assignment)

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="agent.tool_assigned",
        resource_type="agent_tool",
        resource_id=str(assignment.id),
        details={"agent_id": str(agent.id), "tool_id": str(tool.id), "tool_name": tool.name},
    )
    db.add(audit)

    await db.commit()
    await db.refresh(assignment)

    return AgentToolResponse(
        id=assignment.id,
        tenant_id=assignment.tenant_id,
        agent_id=assignment.agent_id,
        tool_id=assignment.tool_id,
        enabled=assignment.enabled,
        tool_name=tool.name,
        tool_display_name=tool.display_name,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


@router.get(
    "/agents/{agent_id}/tools",
    response_model=List[AgentToolResponse],
    summary="List Tools Assigned to Agent",
    description="Lists all tools explicitly assigned to an agent.",
)
async def list_agent_tools(
    agent_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TOOLS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[AgentToolResponse]:
    # Verify agent belongs to tenant
    stmt_agent = select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt_agent)).scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found in your organization.",
        )

    stmt_links = select(AgentTool, ToolDefinition).join(
        ToolDefinition, AgentTool.tool_id == ToolDefinition.id
    ).where(
        AgentTool.agent_id == agent_id,
        AgentTool.tenant_id == current_user.tenant_id,
    ).order_by(ToolDefinition.name.asc())

    results = (await db.execute(stmt_links)).all()
    resp = []
    for link, tool_def in results:
        resp.append(
            AgentToolResponse(
                id=link.id,
                tenant_id=link.tenant_id,
                agent_id=link.agent_id,
                tool_id=link.tool_id,
                enabled=link.enabled,
                tool_name=tool_def.name,
                tool_display_name=tool_def.display_name,
                created_at=link.created_at,
                updated_at=link.updated_at,
            )
        )
    return resp


@router.delete(
    "/agents/{agent_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Tool Assignment from Agent",
    description="Revokes an agent's access to invoke a tool.",
)
async def unassign_tool_from_agent(
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TOOLS_ASSIGN.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = select(AgentTool).where(
        AgentTool.agent_id == agent_id,
        AgentTool.tool_id == tool_id,
        AgentTool.tenant_id == current_user.tenant_id,
    )
    link = (await db.execute(stmt)).scalar_one_or_none()
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool assignment not found for agent {agent_id}.",
        )

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="agent.tool_unassigned",
        resource_type="agent_tool",
        resource_id=str(link.id),
        details={"agent_id": str(agent_id), "tool_id": str(tool_id)},
    )
    db.add(audit)
    await db.delete(link)
    await db.commit()


# ==========================================
# Tool Execution Audit Logs
# ==========================================

@router.get(
    "/tool-executions",
    response_model=List[ToolExecutionResponse],
    summary="List Tool Execution Logs",
    description="Retrieves sanitized audit logs for tool executions within the tenant.",
)
async def list_tool_executions(
    agent_id: Optional[uuid.UUID] = None,
    tool_name: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission(Permission.TOOLS_READ_EXECUTIONS.value)),
    db: AsyncSession = Depends(get_db),
) -> List[ToolExecutionResponse]:
    stmt = select(ToolExecution).where(
        ToolExecution.tenant_id == current_user.tenant_id
    )
    if agent_id:
        stmt = stmt.where(ToolExecution.agent_id == agent_id)
    if tool_name:
        stmt = stmt.where(ToolExecution.tool_name == tool_name)
    if status_filter:
        stmt = stmt.where(ToolExecution.status == status_filter)

    stmt = stmt.order_by(ToolExecution.created_at.desc()).limit(limit).offset(offset)
    executions = (await db.execute(stmt)).scalars().all()
    return [ToolExecutionResponse.model_validate(e) for e in executions]


@router.get(
    "/tool-executions/{execution_id}",
    response_model=ToolExecutionResponse,
    summary="Get Tool Execution Log",
    description="Retrieves a single sanitized tool execution audit record.",
)
async def get_tool_execution(
    execution_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TOOLS_READ_EXECUTIONS.value)),
    db: AsyncSession = Depends(get_db),
) -> ToolExecutionResponse:
    stmt = select(ToolExecution).where(
        ToolExecution.id == execution_id,
        ToolExecution.tenant_id == current_user.tenant_id,
    )
    execution = (await db.execute(stmt)).scalar_one_or_none()
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool execution record {execution_id} not found.",
        )
    return ToolExecutionResponse.model_validate(execution)


# ==========================================
# Direct Tool Execution Endpoint (Testing/Admin)
# ==========================================

@router.post(
    "/tools/{tool_id}/execute",
    summary="Execute Tool Directly",
    description="Executes a tool directly through the full 15-step security pipeline. Requires 'tools:execute'.",
)
async def execute_tool_directly(
    tool_id: uuid.UUID,
    request: ToolDirectExecuteRequest,
    current_user: User = Depends(require_permission(Permission.TOOLS_EXECUTE.value)),
    db: AsyncSession = Depends(get_db),
):
    service = ToolExecutionService(db)
    try:
        result = await service.execute_tool(
            tenant_id=current_user.tenant_id,
            tool_identifier=tool_id,
            arguments=request.arguments,
            agent_id=request.agent_id,
            actor_id=current_user.id,
            actor_role=current_user.role,
            idempotency_key=request.idempotency_key,
        )
        return result.to_dict()
    except Exception as exc:
        raise http_exception_from_domain(exc)
