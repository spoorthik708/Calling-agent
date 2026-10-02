import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.throttling import InMemoryRateLimiter
from app.core.exceptions import (
    InactiveAgentExecutionError,
    TenantIsolationError,
    ToolDisabledError,
    ToolNotFoundError,
    ToolRateLimitError,
)
from app.core.security import create_access_token, get_password_hash
from app.models import Agent, Tenant, User
from app.tools.models import AgentTool, ToolDefinition, ToolExecution, ToolExecutionStatus
from app.tools.service import ToolExecutionService


@pytest.fixture
async def pipeline_setup(db_session: AsyncSession):
    tenant = Tenant(
        id=uuid.UUID("11112222-3333-4444-5555-666677778888"),
        name="Pipeline Tenant",
        slug="pipeline-tenant",
        status="active",
        is_active=True,
    )
    db_session.add(tenant)

    owner = User(
        id=uuid.UUID("11112222-0000-0000-0000-000000000001"),
        tenant_id=tenant.id,
        email="owner@pipeline.com",
        hashed_password=get_password_hash("Password123!"),
        role="owner",
        status="active",
        is_active=True,
    )
    db_session.add(owner)

    agent = Agent(
        id=uuid.UUID("11112222-0000-0000-0000-000000000002"),
        tenant_id=tenant.id,
        name="Customer Service Agent",
        system_prompt="Support agent",
        status="active",
    )
    inactive_agent = Agent(
        id=uuid.UUID("11112222-0000-0000-0000-000000000003"),
        tenant_id=tenant.id,
        name="Deactivated Agent",
        system_prompt="Inactive agent",
        status="inactive",
    )
    db_session.add_all([agent, inactive_agent])

    # Tool 1: lookup_customer (Internal)
    tool1 = ToolDefinition(
        id=uuid.UUID("11112222-0000-0000-0000-000000000004"),
        tenant_id=tenant.id,
        name="lookup_customer",
        display_name="Lookup Customer",
        description="Looks up customer profile.",
        tool_type="internal",
        input_schema={"type": "object", "properties": {"customer_id": {"type": "string"}}},
        output_schema={"type": "object"},
        configuration={},
        is_active=True,
    )
    # Tool 2: create_followup (Internal side-effecting)
    tool2 = ToolDefinition(
        id=uuid.UUID("11112222-0000-0000-0000-000000000005"),
        tenant_id=tenant.id,
        name="create_followup",
        display_name="Create Followup",
        description="Creates followup ticket.",
        tool_type="internal",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        configuration={},
        is_active=True,
    )
    # Tool 3: disabled_tool
    tool3 = ToolDefinition(
        id=uuid.UUID("11112222-0000-0000-0000-000000000006"),
        tenant_id=tenant.id,
        name="disabled_tool",
        display_name="Disabled Tool",
        description="Archived tool.",
        tool_type="internal",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        configuration={},
        is_active=False,
    )
    db_session.add_all([tool1, tool2, tool3])

    # Assignments to agent
    assign1 = AgentTool(tenant_id=tenant.id, agent_id=agent.id, tool_id=tool1.id, enabled=True)
    assign2 = AgentTool(tenant_id=tenant.id, agent_id=agent.id, tool_id=tool2.id, enabled=True)
    assign3 = AgentTool(tenant_id=tenant.id, agent_id=agent.id, tool_id=tool3.id, enabled=True)
    assign_inactive = AgentTool(tenant_id=tenant.id, agent_id=inactive_agent.id, tool_id=tool1.id, enabled=True)
    db_session.add_all([assign1, assign2, assign3, assign_inactive])

    await db_session.commit()

    return {
        "tenant": tenant,
        "owner": owner,
        "agent": agent,
        "inactive_agent": inactive_agent,
        "tool1": tool1,
        "tool2": tool2,
        "tool3": tool3,
    }


@pytest.mark.asyncio
async def test_tool_execution_success_and_audit_persistence(db_session: AsyncSession, pipeline_setup):
    """Verifies internal tool execution and persistence of immutable audit log."""
    tenant = pipeline_setup["tenant"]
    agent = pipeline_setup["agent"]
    tool1 = pipeline_setup["tool1"]

    service = ToolExecutionService(db_session)
    result = await service.execute_tool(
        tenant_id=tenant.id,
        tool_identifier=tool1.name,
        arguments={"customer_id": "cust_9988"},
        agent_id=agent.id,
    )

    assert result.success is True
    assert result.tool_name == "lookup_customer"
    assert result.data["customer_id"] == "cust_9988"
    assert "found in tenant" in result.data["status"]

    # Verify ToolExecution record in database
    stmt = select(ToolExecution).where(
        ToolExecution.tenant_id == tenant.id,
        ToolExecution.tool_name == "lookup_customer",
    )
    exec_record = (await db_session.execute(stmt)).scalar_one_or_none()
    assert exec_record is not None
    assert exec_record.status == ToolExecutionStatus.SUCCESS.value
    assert exec_record.agent_id == agent.id
    assert exec_record.validated_input["customer_id"] == "cust_9988"
    assert exec_record.duration_ms > 0


@pytest.mark.asyncio
async def test_direct_execute_api_endpoint(async_client: AsyncClient, pipeline_setup):
    """Verifies POST /api/v1/tools/{id}/execute with RBAC and validation."""
    owner = pipeline_setup["owner"]
    agent = pipeline_setup["agent"]
    tool1 = pipeline_setup["tool1"]

    token = create_access_token(subject=owner.id, tenant_id=owner.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await async_client.post(
        f"/api/v1/tools/{tool1.id}/execute",
        json={"arguments": {"customer_id": "cust_api_123"}, "agent_id": str(agent.id)},
        headers=headers,
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["tool_name"] == "lookup_customer"
    assert res_data["data"]["customer_id"] == "cust_api_123"


@pytest.mark.asyncio
async def test_disabled_tool_execution_rejected(db_session: AsyncSession, pipeline_setup):
    """Verifies executing a disabled tool raises ToolDisabledError."""
    tenant = pipeline_setup["tenant"]
    agent = pipeline_setup["agent"]
    tool3 = pipeline_setup["tool3"]

    service = ToolExecutionService(db_session)
    with pytest.raises(ToolDisabledError):
        await service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool3.name,
            arguments={},
            agent_id=agent.id,
        )


@pytest.mark.asyncio
async def test_inactive_agent_cannot_execute_tools(db_session: AsyncSession, pipeline_setup):
    """Verifies an inactive agent attempting to use tools raises InactiveAgentExecutionError."""
    tenant = pipeline_setup["tenant"]
    inactive_agent = pipeline_setup["inactive_agent"]
    tool1 = pipeline_setup["tool1"]

    service = ToolExecutionService(db_session)
    with pytest.raises(InactiveAgentExecutionError):
        await service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool1.name,
            arguments={"customer_id": "cust_123"},
            agent_id=inactive_agent.id,
        )


@pytest.mark.asyncio
async def test_tool_rate_limiting_enforced_per_tenant(db_session: AsyncSession, pipeline_setup):
    """Verifies rate limiting quota per tenant raises ToolRateLimitError."""
    tenant = pipeline_setup["tenant"]
    agent = pipeline_setup["agent"]
    tool1 = pipeline_setup["tool1"]

    # Use a custom rate limiter with low quota (max 2 attempts per minute)
    custom_limiter = InMemoryRateLimiter()
    service = ToolExecutionService(db_session, rate_limiter=custom_limiter)
    orig_rate = service.settings.TOOL_RATE_LIMIT_PER_MINUTE
    service.settings.TOOL_RATE_LIMIT_PER_MINUTE = 2

    try:
        # Attempt 1 -> OK
        await service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool1.name,
            arguments={"customer_id": "cust_1"},
            agent_id=agent.id,
        )
        # Attempt 2 -> OK
        await service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool1.name,
            arguments={"customer_id": "cust_2"},
            agent_id=agent.id,
        )
        # Attempt 3 -> Exceeded!
        with pytest.raises(ToolRateLimitError):
            await service.execute_tool(
                tenant_id=tenant.id,
                tool_identifier=tool1.name,
                arguments={"customer_id": "cust_3"},
                agent_id=agent.id,
            )
    finally:
        service.settings.TOOL_RATE_LIMIT_PER_MINUTE = orig_rate


@pytest.mark.asyncio
async def test_tool_execution_logs_retrieval_api(async_client: AsyncClient, pipeline_setup, db_session: AsyncSession):
    """Verifies GET /api/v1/tool-executions lists sanitized execution logs."""
    owner = pipeline_setup["owner"]
    agent = pipeline_setup["agent"]
    tool1 = pipeline_setup["tool1"]
    tenant = pipeline_setup["tenant"]

    # Run an execution
    service = ToolExecutionService(db_session)
    await service.execute_tool(
        tenant_id=tenant.id,
        tool_identifier=tool1.name,
        arguments={"customer_id": "cust_audit_test"},
        agent_id=agent.id,
    )

    token = create_access_token(subject=owner.id, tenant_id=owner.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await async_client.get("/api/v1/tool-executions", headers=headers)
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 1
    assert logs[0]["tool_name"] == "lookup_customer"
    assert logs[0]["status"] == "success"
    assert logs[0]["validated_input"]["customer_id"] == "cust_audit_test"
