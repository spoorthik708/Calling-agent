from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentKnowledgeBase, AgentStatus
from app.agents.schemas import (
    AgentCreateRequest,
    AgentKnowledgeBaseAssociationResponse,
    AgentResponse,
    AgentUpdateRequest,
)
from app.auth.dependencies import require_permission
from app.auth.rbac import Permission
from app.core.exceptions import (
    AgentNotFoundError,
    EntityNotFoundError,
    KnowledgeBaseNotFoundError,
    TenantIsolationError,
)
from app.core.logging import get_logger
from app.database.session import get_db
from app.knowledge.models import KnowledgeBase, KnowledgeBaseStatus
from app.models.audit import AuditLog
from app.users.models import User

logger = get_logger("yavura.agents.api")

router = APIRouter(prefix="/agents", tags=["AI Agents"])


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create AI Agent",
    description="Creates a new tenant-owned AI agent. Requires 'agents:create'.",
)
async def create_agent(
    request: AgentCreateRequest,
    current_user: User = Depends(require_permission(Permission.AGENTS_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    # Check duplicate agent name within tenant
    stmt = select(Agent).where(
        Agent.tenant_id == current_user.tenant_id,
        Agent.name == request.name,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{request.name}' already exists in your organization.",
        )

    agent = Agent(
        tenant_id=current_user.tenant_id,
        name=request.name,
        description=request.description,
        system_prompt=request.system_prompt,
        status=AgentStatus.ACTIVE.value,
        default_language=request.default_language,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        fallback_message=request.fallback_message,
        escalation_enabled=request.escalation_enabled,
    )
    db.add(agent)
    await db.flush()

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="agent.created",
        resource_type="agent",
        resource_id=str(agent.id),
        details={"name": agent.name, "llm_model": agent.llm_model},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.get(
    "",
    response_model=List[AgentResponse],
    status_code=status.HTTP_200_OK,
    summary="List Tenant AI Agents",
    description="Lists all AI agents belonging to the authenticated tenant. Requires 'agents:read'.",
)
async def list_agents(
    status_filter: Optional[str] = None,
    current_user: User = Depends(require_permission(Permission.AGENTS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[AgentResponse]:
    stmt = select(Agent).where(Agent.tenant_id == current_user.tenant_id)
    if status_filter:
        stmt = stmt.where(Agent.status == status_filter.lower().strip())
    stmt = stmt.order_by(Agent.created_at.desc())

    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentResponse.model_validate(a) for a in agents]


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Agent Details",
    description="Retrieves a specific AI agent strictly within tenant boundary. Requires 'agents:read'.",
)
async def get_agent(
    agent_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.AGENTS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    stmt = select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )
    return AgentResponse.model_validate(agent)


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Agent Configuration",
    description="Updates agent prompts, parameters, and status strictly within tenant boundary. Requires 'agents:update'.",
)
async def update_agent(
    agent_id: uuid.UUID,
    request: AgentUpdateRequest,
    current_user: User = Depends(require_permission(Permission.AGENTS_UPDATE.value)),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    stmt = select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )

    if request.name is not None:
        new_name = request.name.strip()
        if new_name != agent.name:
            dup_stmt = select(Agent).where(
                Agent.tenant_id == current_user.tenant_id,
                Agent.name == new_name,
                Agent.id != agent_id,
            )
            if (await db.execute(dup_stmt)).scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Agent with name '{new_name}' already exists.",
                )
            agent.name = new_name

    if request.description is not None:
        agent.description = request.description
    if request.system_prompt is not None:
        agent.system_prompt = request.system_prompt
    if request.status is not None:
        valid_statuses = [s.value for s in AgentStatus]
        if request.status.lower() not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{request.status}'. Allowed: {valid_statuses}",
            )
        agent.status = request.status.lower()
    if request.default_language is not None:
        agent.default_language = request.default_language
    if request.llm_provider is not None:
        agent.llm_provider = request.llm_provider
    if request.llm_model is not None:
        agent.llm_model = request.llm_model
    if request.temperature is not None:
        agent.temperature = request.temperature
    if request.max_output_tokens is not None:
        agent.max_output_tokens = request.max_output_tokens
    if request.fallback_message is not None:
        agent.fallback_message = request.fallback_message
    if request.escalation_enabled is not None:
        agent.escalation_enabled = request.escalation_enabled

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="agent.updated",
        resource_type="agent",
        resource_id=str(agent.id),
        details={"status": agent.status, "name": agent.name},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive Agent",
    description="Archives the agent preserving conversation history. Requires 'agents:delete'.",
)
async def delete_agent(
    agent_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.AGENTS_DELETE.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )

    # Soft-archive by default to preserve conversation audit logs and foreign keys
    agent.status = AgentStatus.ARCHIVED.value

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="agent.archived",
        resource_type="agent",
        resource_id=str(agent.id),
        details={"name": agent.name},
    )
    db.add(audit)
    await db.commit()


# ==============================================================================
# AGENT KNOWLEDGE BASE ASSOCIATIONS
# ==============================================================================

@router.post(
    "/{agent_id}/knowledge-bases/{kb_id}",
    response_model=AgentKnowledgeBaseAssociationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach Knowledge Base to Agent",
    description="Explicitly authorizes an Agent to search a specific Knowledge Base. Requires 'agents:manage_knowledge'.",
)
async def attach_knowledge_base(
    agent_id: uuid.UUID,
    kb_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.AGENTS_MANAGE_KNOWLEDGE.value)),
    db: AsyncSession = Depends(get_db),
) -> AgentKnowledgeBaseAssociationResponse:
    # 1. Verify agent belongs to caller's tenant
    stmt_agent = select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt_agent)).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    # 2. Verify knowledge base belongs to caller's tenant
    stmt_kb = select(KnowledgeBase).where(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.tenant_id == current_user.tenant_id,
    )
    kb = (await db.execute(stmt_kb)).scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found.")

    # 3. Check existing association
    stmt_assoc = select(AgentKnowledgeBase).where(
        AgentKnowledgeBase.agent_id == agent.id,
        AgentKnowledgeBase.knowledge_base_id == kb.id,
    )
    existing = (await db.execute(stmt_assoc)).scalar_one_or_none()
    if existing:
        return AgentKnowledgeBaseAssociationResponse.model_validate(existing)

    assoc = AgentKnowledgeBase(
        tenant_id=current_user.tenant_id,
        agent_id=agent.id,
        knowledge_base_id=kb.id,
    )
    db.add(assoc)

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="agent.knowledge_base_attached",
        resource_type="agent_knowledge_base",
        resource_id=str(assoc.id),
        details={"agent_id": str(agent.id), "knowledge_base_id": str(kb.id)},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(assoc)
    return AgentKnowledgeBaseAssociationResponse.model_validate(assoc)


@router.delete(
    "/{agent_id}/knowledge-bases/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach Knowledge Base from Agent",
    description="Revokes agent authorization to search the specified Knowledge Base. Requires 'agents:manage_knowledge'.",
)
async def detach_knowledge_base(
    agent_id: uuid.UUID,
    kb_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.AGENTS_MANAGE_KNOWLEDGE.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = select(AgentKnowledgeBase).where(
        AgentKnowledgeBase.agent_id == agent_id,
        AgentKnowledgeBase.knowledge_base_id == kb_id,
        AgentKnowledgeBase.tenant_id == current_user.tenant_id,
    )
    assoc = (await db.execute(stmt)).scalar_one_or_none()
    if not assoc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base association not found.")

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="agent.knowledge_base_detached",
        resource_type="agent_knowledge_base",
        resource_id=str(assoc.id),
        details={"agent_id": str(agent_id), "knowledge_base_id": str(kb_id)},
    )
    db.add(audit)
    await db.delete(assoc)
    await db.commit()


@router.get(
    "/{agent_id}/knowledge-bases",
    response_model=List[AgentKnowledgeBaseAssociationResponse],
    status_code=status.HTTP_200_OK,
    summary="List Attached Knowledge Bases",
    description="Lists all Knowledge Bases explicitly attached to an Agent. Requires 'agents:read'.",
)
async def list_attached_knowledge_bases(
    agent_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.AGENTS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[AgentKnowledgeBaseAssociationResponse]:
    # Verify agent belongs to tenant
    stmt_agent = select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt_agent)).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    stmt = select(AgentKnowledgeBase).where(
        AgentKnowledgeBase.agent_id == agent_id,
        AgentKnowledgeBase.tenant_id == current_user.tenant_id,
    ).order_by(AgentKnowledgeBase.created_at.desc())
    assocs = (await db.execute(stmt)).scalars().all()
    return [AgentKnowledgeBaseAssociationResponse.model_validate(a) for a in assocs]
