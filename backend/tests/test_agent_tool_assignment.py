import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ToolNotAssignedError
from app.core.security import create_access_token, get_password_hash
from app.models import Agent, Tenant, User
from app.tools.models import AgentTool, ToolDefinition
from app.tools.service import ToolExecutionService


@pytest.fixture
async def assignment_setup(db_session: AsyncSession):
    tenant_a = Tenant(
        id=uuid.UUID("11111111-1111-4444-5555-000000000001"),
        name="Assignment Tenant A",
        slug="assignment-tenant-a",
        status="active",
        is_active=True,
    )
    tenant_b = Tenant(
        id=uuid.UUID("22222222-2222-4444-5555-000000000002"),
        name="Assignment Tenant B",
        slug="assignment-tenant-b",
        status="active",
        is_active=True,
    )
    db_session.add_all([tenant_a, tenant_b])

    owner_a = User(
        id=uuid.UUID("33333333-0000-0000-0000-000000000001"),
        tenant_id=tenant_a.id,
        email="owner_a@assign.com",
        hashed_password=get_password_hash("Password123!"),
        role="owner",
        status="active",
        is_active=True,
    )
    owner_b = User(
        id=uuid.UUID("44444444-0000-0000-0000-000000000002"),
        tenant_id=tenant_b.id,
        email="owner_b@assign.com",
        hashed_password=get_password_hash("Password123!"),
        role="owner",
        status="active",
        is_active=True,
    )
    db_session.add_all([owner_a, owner_b])

    # Agent in Tenant A
    agent_a = Agent(
        id=uuid.UUID("55555555-0000-0000-0000-000000000001"),
        tenant_id=tenant_a.id,
        name="Support Agent Alpha",
        system_prompt="You are a helpful customer support agent.",
        status="active",
    )
    db_session.add(agent_a)

    # Tool in Tenant A
    tool_a = ToolDefinition(
        id=uuid.UUID("66666666-0000-0000-0000-000000000001"),
        tenant_id=tenant_a.id,
        name="lookup_customer",
        display_name="Lookup Customer",
        description="Looks up customer profile.",
        tool_type="internal",
        input_schema={"type": "object", "properties": {"customer_id": {"type": "string"}}},
        output_schema={"type": "object"},
        configuration={},
        is_active=True,
    )
    # Tool in Tenant B
    tool_b = ToolDefinition(
        id=uuid.UUID("77777777-0000-0000-0000-000000000002"),
        tenant_id=tenant_b.id,
        name="lookup_customer",
        display_name="Lookup Customer Beta",
        description="Tenant B tool.",
        tool_type="internal",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        configuration={},
        is_active=True,
    )
    db_session.add_all([tool_a, tool_b])
    await db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "owner_a": owner_a,
        "owner_b": owner_b,
        "agent_a": agent_a,
        "tool_a": tool_a,
        "tool_b": tool_b,
    }


@pytest.mark.asyncio
async def test_assign_and_unassign_tool_to_agent(async_client: AsyncClient, assignment_setup):
    """Verifies assigning a tool to an agent, listing assigned tools, and unassigning."""
    owner_a = assignment_setup["owner_a"]
    agent_a = assignment_setup["agent_a"]
    tool_a = assignment_setup["tool_a"]

    token = create_access_token(subject=owner_a.id, tenant_id=owner_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Assign tool to agent
    assign_resp = await async_client.post(
        f"/api/v1/agents/{agent_a.id}/tools",
        json={"tool_id": str(tool_a.id), "enabled": True},
        headers=headers,
    )
    assert assign_resp.status_code == 201
    assign_data = assign_resp.json()
    assert assign_data["agent_id"] == str(agent_a.id)
    assert assign_data["tool_id"] == str(tool_a.id)
    assert assign_data["tool_name"] == "lookup_customer"

    # 2. Duplicate assignment rejected (409)
    dup_resp = await async_client.post(
        f"/api/v1/agents/{agent_a.id}/tools",
        json={"tool_id": str(tool_a.id), "enabled": True},
        headers=headers,
    )
    assert dup_resp.status_code == 409

    # 3. List tools assigned to agent
    list_resp = await async_client.get(f"/api/v1/agents/{agent_a.id}/tools", headers=headers)
    assert list_resp.status_code == 200
    assigned = list_resp.json()
    assert len(assigned) == 1
    assert assigned[0]["tool_id"] == str(tool_a.id)

    # 4. Unassign tool from agent
    del_resp = await async_client.delete(f"/api/v1/agents/{agent_a.id}/tools/{tool_a.id}", headers=headers)
    assert del_resp.status_code == 204

    # 5. Verify list is now empty
    list_after = await async_client.get(f"/api/v1/agents/{agent_a.id}/tools", headers=headers)
    assert len(list_after.json()) == 0


@pytest.mark.asyncio
async def test_cross_tenant_tool_assignment_denied(async_client: AsyncClient, assignment_setup):
    """Enforces that Tenant A cannot assign Tenant B's tool to Tenant A's agent."""
    owner_a = assignment_setup["owner_a"]
    agent_a = assignment_setup["agent_a"]
    tool_b = assignment_setup["tool_b"]

    token_a = create_access_token(subject=owner_a.id, tenant_id=owner_a.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Attempt to attach Tenant B's tool to Tenant A's agent
    resp = await async_client.post(
        f"/api/v1/agents/{agent_a.id}/tools",
        json={"tool_id": str(tool_b.id), "enabled": True},
        headers=headers_a,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_cannot_execute_unassigned_tool(db_session: AsyncSession, assignment_setup):
    """
    CRITICAL SECURITY CHECK:
    An agent attempting to execute a tool that exists in tenant but is NOT explicitly assigned
    must fail immediately with ToolNotAssignedError.
    """
    tenant_a = assignment_setup["tenant_a"]
    agent_a = assignment_setup["agent_a"]
    tool_a = assignment_setup["tool_a"]

    service = ToolExecutionService(db_session)

    # Do not assign tool_a to agent_a
    with pytest.raises(ToolNotAssignedError):
        await service.execute_tool(
            tenant_id=tenant_a.id,
            tool_identifier=tool_a.name,
            arguments={"customer_id": "cust_123"},
            agent_id=agent_a.id,
        )
